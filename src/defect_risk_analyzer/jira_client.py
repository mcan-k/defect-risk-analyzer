"""
Jira Client — REST API v3 integration with ADF parser.

Fetches bug issues from Jira Cloud or Server instances.
Parses Atlassian Document Format (ADF) descriptions to plain text.
Supports mock data mode for demo/evaluation without Jira credentials.
"""

import contextlib
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple

import requests

from defect_risk_analyzer import config

logger = logging.getLogger(__name__)


class JiraFetchError(Exception):
    """A page of the Jira search failed, so the fetch was abandoned.

    Nothing was saved: fetch_and_save() raises this before bugs.json is touched,
    so the previous file survives byte for byte. The request error is chained
    as `__cause__` and logged; the message itself carries no URL or credential.

    Deliberately NOT a subclass of OSError. requests.RequestException is one,
    and the dashboard's error boundary (ui/service.call) reports OSError as a
    file or disk problem — the wrong message for an unreachable Jira.
    """

    def __init__(self, page: int) -> None:
        super().__init__(f"Jira search failed on page {page}; nothing was saved.")
        self.page = page


class FetchResult(NamedTuple):
    """The bugs a fetch returned, and whether the page cap cut it short."""

    bugs: list[dict[str, Any]]
    truncated: bool = False


def _write_json_atomically(path: Path, data: Any) -> None:
    """Write `data` as JSON to `path` so a failed write never damages the old file.

    The JSON goes to a temporary file next to `path` and replaces it in one step
    (os.replace). A write that fails part way — disk full, a killed process —
    leaves the previous file exactly as it was, and the temporary file is
    removed. The temporary name is unique, so two writers cannot share one, and
    plain open() gives the new file the same permissions a direct write did.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp, "x", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise


# =============================================================================
# ADF (Atlassian Document Format) Parser
# =============================================================================

def parse_adf_to_text(adf_node: dict | list | str | None) -> str:
    """
    Recursively parse Atlassian Document Format (ADF) to plain text.

    ADF is a nested JSON structure used by Jira Cloud for rich-text fields.
    This extracts readable text from all node types.

    Args:
        adf_node: ADF node (dict, list, string, or None).

    Returns:
        Plain text string.
    """
    if adf_node is None:
        return ""

    if isinstance(adf_node, str):
        return adf_node

    if isinstance(adf_node, list):
        return " ".join(parse_adf_to_text(item) for item in adf_node)

    if not isinstance(adf_node, dict):
        return ""

    node_type = adf_node.get("type", "")
    text = adf_node.get("text", "")
    content = adf_node.get("content", [])

    # Text node — return directly
    if node_type == "text":
        return text

    # Container nodes — recurse into content
    parts = []
    if content:
        for child in content:
            child_text = parse_adf_to_text(child)
            if child_text:
                parts.append(child_text)

    # Add formatting based on node type
    if node_type == "paragraph":
        return " ".join(parts)
    elif node_type == "heading":
        return " ".join(parts)
    elif node_type == "bulletList" or node_type == "orderedList":
        return " ".join(parts)
    elif node_type == "listItem":
        return " ".join(parts)
    elif node_type == "codeBlock":
        return " ".join(parts)
    elif node_type == "blockquote":
        return " ".join(parts)
    elif node_type == "table":
        return " ".join(parts)
    elif node_type == "tableRow":
        return " ".join(parts)
    elif node_type == "tableCell" or node_type == "tableHeader":
        return " ".join(parts)
    elif node_type == "mention":
        return adf_node.get("attrs", {}).get("text", "")
    elif node_type == "inlineCard":
        return adf_node.get("attrs", {}).get("url", "")
    elif node_type == "emoji":
        return adf_node.get("attrs", {}).get("shortName", "")

    # Default: join all parts
    return " ".join(parts) if parts else text


# =============================================================================
# Jira Client Class
# =============================================================================

class JiraClient:
    """Jira REST API v3 client for fetching bug issues."""

    # Safety cap against endless pagination: with the default page size of 200,
    # at most 10,000 issues. Reaching it is reported (FetchResult.truncated and a
    # WARNING line), not silent. A class constant so tests can lower it; it is
    # not a setting.
    MAX_PAGES = 50

    def __init__(
        self,
        url: str | None = None,
        email: str | None = None,
        api_token: str | None = None,
        project_key: str | None = None,
    ) -> None:
        self._url = (url or config.JIRA_URL).rstrip("/")
        self._email = email or config.JIRA_EMAIL
        self._api_token = api_token or config.JIRA_API_TOKEN
        self._project_key = project_key or config.JIRA_PROJECT_KEY
        self._session = requests.Session()
        self._session.auth = (self._email, self._api_token)
        self._session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

    def test_connection(self) -> bool:
        """
        Test Jira connection by fetching server info.

        Returns:
            True if connection is successful.
        """
        try:
            response = self._session.get(
                f"{self._url}/rest/api/3/myself",
                timeout=10,
            )
            if response.status_code == 200:
                user = response.json()
                logger.info("Jira connection OK. User: %s", user.get("displayName", "?"))
                return True
            else:
                logger.error("Jira connection failed. Status: %d", response.status_code)
                return False
        except requests.RequestException as e:
            logger.error("Jira connection error: %s", e)
            return False

    def fetch_bugs(self, max_results: int = 200) -> FetchResult:
        """
        Fetch all bug issues from the configured Jira project.

        Uses JQL: project = {KEY} AND issuetype = Bug ORDER BY created DESC
        Paginates automatically if there are more than `max_results` per page,
        up to MAX_PAGES pages.

        Args:
            max_results: Maximum results per API call (Jira paginates).

        Returns:
            FetchResult: the normalized bugs, and `truncated` = True when the
            page cap stopped the fetch while Jira still had more.

        Raises:
            JiraFetchError: any page failed. The pages fetched before it are
                dropped: a partial list must not pass for the whole project.
        """
        jql = (
            f"project = {self._project_key} "
            f"AND issuetype = Bug "
            f"ORDER BY created DESC"
        )

        fields = [
            "summary",
            "description",
            "priority",
            "status",
            "components",
            "created",
            "updated",
            "assignee",
            "reporter",
            "resolution",
            "labels",
        ]

        all_bugs: list[dict[str, Any]] = []
        next_page_token: str | None = None
        page_count = 0
        truncated = False

        while page_count < self.MAX_PAGES:
            page_count += 1
            body: dict[str, Any] = {
                "jql": jql,
                "maxResults": max_results,
                "fields": fields,
            }
            if next_page_token:
                body["nextPageToken"] = next_page_token

            try:
                response = self._session.post(
                    f"{self._url}/rest/api/3/search/jql",
                    json=body,
                    timeout=30,
                )
                response.raise_for_status()
                data = response.json()

            except requests.RequestException as e:
                logger.error("Jira API error on page %d: %s", page_count, e)
                raise JiraFetchError(page_count) from e

            issues = data.get("issues", [])
            if not issues:
                break

            for issue in issues:
                bug = self._normalize_issue(issue)
                all_bugs.append(bug)

            # New pagination: use nextPageToken and isLast
            is_last = data.get("isLast", True)
            if is_last:
                break

            next_page_token = data.get("nextPageToken")
            if not next_page_token:
                break
        else:
            # The loop ran out of pages, not out of issues: Jira still had more.
            truncated = True
            logger.warning(
                "Jira page cap reached: %d pages of %d issues; %d bugs fetched and older "
                "issues left out. Narrow the JQL.",
                self.MAX_PAGES, max_results, len(all_bugs),
            )

        logger.info("Fetched %d bugs from Jira project %s.", len(all_bugs), self._project_key)
        return FetchResult(all_bugs, truncated)

    def fetch_and_save(self) -> FetchResult:
        """
        Fetch bugs from Jira and save them to data/bugs.json.

        Nothing is written unless every page came back: a failed page raises
        before the file is touched. A fetch cut short by the page cap is saved,
        and says so in `truncated`. The write is atomic.

        Returns:
            FetchResult from fetch_bugs().

        Raises:
            JiraFetchError: a page failed; the previous bugs.json is unchanged.
            OSError: bugs.json could not be written; the previous file is intact.
        """
        result = self.fetch_bugs()
        _write_json_atomically(config.BUGS_FILE, result.bugs)
        logger.info("Saved %d bugs to %s.", len(result.bugs), config.BUGS_FILE)
        return result

    # ------------------------------------------------------------------
    # Issue Normalization
    # ------------------------------------------------------------------

    def _normalize_issue(self, issue: dict[str, Any]) -> dict[str, Any]:
        """
        Normalize a Jira issue into a flat bug dictionary.

        Handles ADF description parsing and field extraction.
        """
        fields = issue.get("fields", {})

        # Parse description (may be ADF or plain string)
        description_raw = fields.get("description")
        if isinstance(description_raw, dict):
            description = parse_adf_to_text(description_raw)
        elif isinstance(description_raw, str):
            description = description_raw
        else:
            description = ""

        # Extract component (first component or "Unknown")
        components = fields.get("components", [])
        component = components[0].get("name", "Unknown") if components else "Unknown"

        # Extract priority name
        priority_data = fields.get("priority")
        priority = priority_data.get("name", "Medium") if priority_data else "Medium"

        # Extract status name
        status_data = fields.get("status")
        status = status_data.get("name", "Open") if status_data else "Open"

        # Extract assignee and reporter names
        assignee_data = fields.get("assignee")
        assignee = assignee_data.get("displayName", "") if assignee_data else ""

        reporter_data = fields.get("reporter")
        reporter = reporter_data.get("displayName", "") if reporter_data else ""

        # Extract resolution
        resolution_data = fields.get("resolution")
        resolution = resolution_data.get("name", "") if resolution_data else ""

        return {
            "key": issue.get("key", ""),
            "summary": fields.get("summary", ""),
            "description": description.strip(),
            "priority": priority,
            "status": status,
            "component": component,
            "created": fields.get("created", ""),
            "updated": fields.get("updated", ""),
            "assignee": assignee,
            "reporter": reporter,
            "resolution": resolution,
            "labels": fields.get("labels", []),
        }


# =============================================================================
# Data Loading Functions
# =============================================================================

def load_bugs_from_file(file_path=None) -> list[dict[str, Any]]:
    """
    Load bugs from a JSON file (bugs.json or sample_bugs.json).

    Args:
        file_path: Path to JSON file. Defaults based on USE_MOCK_DATA setting.

    Returns:
        List of bug dictionaries.
    """
    if file_path is None:
        if config.USE_MOCK_DATA:
            file_path = config.sample_bugs_file()
        else:
            file_path = config.BUGS_FILE

    try:
        with open(file_path, encoding="utf-8") as f:
            bugs = json.load(f)
        logger.info("Loaded %d bugs from %s.", len(bugs), file_path)
        return bugs if isinstance(bugs, list) else []
    except FileNotFoundError:
        logger.warning("Bug file not found: %s", file_path)
        return []
    except (OSError, json.JSONDecodeError) as e:
        logger.error("Failed to load bugs from %s: %s", file_path, e)
        return []


def normalize_webhook_issue(issue: dict[str, Any]) -> dict[str, Any]:
    """
    Flatten a Jira webhook issue into the bug dict shape used everywhere else.

    Simpler than `JiraClient._normalize_issue`: webhook payloads carry only the
    fields needed for a risk score, and the description arrives as plain text.

    Args:
        issue: The `issue` object from a Jira webhook payload.

    Returns:
        Bug dictionary.
    """
    fields = issue.get("fields", {})

    components = fields.get("components", [])
    priority_data = fields.get("priority")
    status_data = fields.get("status")

    return {
        "key": issue.get("key", "UNKNOWN"),
        "summary": fields.get("summary", ""),
        "description": fields.get("description", ""),
        "priority": priority_data.get("name", "Medium") if priority_data else "Medium",
        "status": status_data.get("name", "Open") if status_data else "Open",
        "component": components[0].get("name", "Unknown") if components else "Unknown",
        "created": fields.get("created", datetime.now().isoformat()),
    }


def get_webhook_issue_type(issue: dict[str, Any]) -> str:
    """Return the issue type name from a webhook payload, or '' when absent."""
    return issue.get("fields", {}).get("issuetype", {}).get("name", "")


def refresh_data() -> FetchResult:
    """
    Refresh bug data: fetch from Jira (or load mock data) and return.

    Returns:
        FetchResult. `truncated` can only be True for a live Jira fetch.

    Raises:
        JiraFetchError, OSError: from JiraClient.fetch_and_save().
    """
    if config.USE_MOCK_DATA:
        sample = config.sample_bugs_file()
        logger.info("Mock mode active — loading %s.", sample.name)
        return FetchResult(load_bugs_from_file(sample))

    if not config.is_jira_configured():
        logger.warning("Jira not configured. Attempting to load existing bugs.json.")
        return FetchResult(load_bugs_from_file(config.BUGS_FILE))

    client = JiraClient()
    return client.fetch_and_save()
