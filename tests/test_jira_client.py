"""
What JiraClient and the jira_client module functions do today (Faz 6E-2, PR 2).

Until this file the live-Jira path had no test at all: the 6E discovery's
coverage run (2026-11-09) measured jira_client.py at 17.5 % of lines, and none of
JiraClient's methods executed. Everything that turns a Jira project into the
bug list the rest of the product scores went unchecked.

NO NETWORK. JiraClient keeps one `requests.Session` in `_session`; each test
swaps it for FakeSession below, which records every call and replays scripted
responses. The only real Session built is in the constructor tests, and nothing
is sent on it. Files go to pytest's tmp_path; config attributes are changed with
monkeypatch, which restores them. Credentials are obvious placeholders.

HOW THE CLIENT PAGES (read from the code, not from Jira's docs): POST to
/rest/api/3/search/jql with `maxResults` (default 200) and, from the second page
on, `nextPageToken`. It stops when the response says `isLast` (missing counts as
true), when there is no next token, when a page has no issues, or after
`max_pages = 50` — so at most 10,000 issues with the default page size.

KNOWN DEFECTS ARE xfail(strict=True), each naming its KNOWN-DEBT row ("JiraClient
kusurları"). They check only the smallest thing any fix must guarantee — the
previous bugs.json survives a failed fetch byte for byte — and accept either
outcome of the call itself (a return or an exception), so they do not choose the
fix's design. The third known defect, that hitting the 10,000-issue cap is
silent, has NO test here: "the caller is told" cannot be checked without picking
the channel (a log, a return value, an exception). That is a design question for
the fix PR and is recorded in KNOWN-DEBT instead.
"""

import contextlib
import json
from datetime import datetime

import pytest
import requests

from defect_risk_analyzer import config, jira_client
from defect_risk_analyzer.jira_client import (
    JiraClient,
    get_webhook_issue_type,
    load_bugs_from_file,
    normalize_webhook_issue,
    refresh_data,
)

KNOWN_DEBT = "KNOWN-DEBT.md, 'JiraClient kusurları'"
BASE_URL = "https://jira.example.invalid"
SEARCH_URL = f"{BASE_URL}/rest/api/3/search/jql"


# --- fakes -------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status_code=200, payload=None, error=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self._error = error

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self._error is not None:
            raise self._error


class FakeSession:
    """Replays scripted responses; an Exception in the script is raised instead."""

    def __init__(self, posts=(), gets=()):
        self.posts = list(posts)
        self.gets = list(gets)
        self.post_calls = []
        self.get_calls = []

    @staticmethod
    def _next(script, calls, url, kwargs):
        calls.append((url, kwargs))
        item = script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def post(self, url, **kwargs):
        return self._next(self.posts, self.post_calls, url, kwargs)

    def get(self, url, **kwargs):
        return self._next(self.gets, self.get_calls, url, kwargs)


def issue(key, **fields):
    return {"key": key, "fields": {"summary": f"summary {key}", **fields}}


def page(*keys, is_last=None, token=None):
    payload = {"issues": [issue(k) for k in keys]}
    if is_last is not None:
        payload["isLast"] = is_last
    if token is not None:
        payload["nextPageToken"] = token
    return FakeResponse(payload=payload)


def make_client(session=None, **overrides):
    args = {
        "url": BASE_URL + "/",
        "email": "tester@example.invalid",
        "api_token": "placeholder-not-a-token",
        "project_key": "AP",
    }
    args.update(overrides)
    client = JiraClient(**args)
    if session is not None:
        client._session = session
    return client


# --- constructor and credentials -----------------------------------------------


def test_explicit_arguments_build_an_authenticated_json_session():
    """Basic auth from (email, token), JSON headers, trailing slash stripped."""
    client = make_client()
    assert client._url == BASE_URL
    assert client._project_key == "AP"
    assert client._session.auth == ("tester@example.invalid", "placeholder-not-a-token")
    assert client._session.headers["Accept"] == "application/json"
    assert client._session.headers["Content-Type"] == "application/json"


def test_missing_arguments_fall_back_to_config(monkeypatch):
    """Each argument left out is read from config at construction time."""
    monkeypatch.setattr(config, "JIRA_URL", "https://cfg.example.invalid/")
    monkeypatch.setattr(config, "JIRA_EMAIL", "cfg@example.invalid")
    monkeypatch.setattr(config, "JIRA_API_TOKEN", "cfg-placeholder")
    monkeypatch.setattr(config, "JIRA_PROJECT_KEY", "CFG")
    client = JiraClient()
    assert client._url == "https://cfg.example.invalid"
    assert client._session.auth == ("cfg@example.invalid", "cfg-placeholder")
    assert client._project_key == "CFG"


# --- test_connection ---------------------------------------------------------------


def test_connection_ok_on_200_with_a_ten_second_timeout():
    """GET /rest/api/3/myself; 200 is success. The 10 s timeout is passed."""
    session = FakeSession(gets=[FakeResponse(200, {"displayName": "Tester"})])
    assert make_client(session).test_connection() is True
    assert session.get_calls == [(f"{BASE_URL}/rest/api/3/myself", {"timeout": 10})]


def test_connection_fails_on_a_non_200_status():
    session = FakeSession(gets=[FakeResponse(401)])
    assert make_client(session).test_connection() is False


def test_connection_fails_on_a_request_exception():
    """A network error is caught and reported as False, not raised."""
    session = FakeSession(gets=[requests.ConnectionError("unreachable")])
    assert make_client(session).test_connection() is False


# --- the search request ----------------------------------------------------------


def test_the_search_asks_for_the_projects_bugs_and_the_used_fields():
    """The JQL and the field list, exactly as built today."""
    session = FakeSession(posts=[page("AP-1", is_last=True)])
    make_client(session).fetch_bugs()
    body = session.post_calls[0][1]["json"]
    assert body["jql"] == "project = AP AND issuetype = Bug ORDER BY created DESC"
    assert body["fields"] == [
        "summary", "description", "priority", "status", "components", "created",
        "updated", "assignee", "reporter", "resolution", "labels",
    ]


def test_the_search_posts_to_search_jql_with_a_thirty_second_timeout():
    session = FakeSession(posts=[page("AP-1", is_last=True)])
    make_client(session).fetch_bugs()
    url, kwargs = session.post_calls[0]
    assert url == SEARCH_URL
    assert kwargs["timeout"] == 30


def test_the_default_page_size_is_two_hundred():
    """maxResults defaults to 200 — with the 50-page cap, 10,000 issues at most."""
    session = FakeSession(posts=[page("AP-1", is_last=True)])
    make_client(session).fetch_bugs()
    body = session.post_calls[0][1]["json"]
    assert body["maxResults"] == 200
    assert "nextPageToken" not in body


# --- paging --------------------------------------------------------------------------


def test_is_last_stops_even_when_a_next_token_is_present():
    session = FakeSession(posts=[page("AP-1", is_last=True, token="t2"), page("AP-2")])
    bugs = make_client(session).fetch_bugs()
    assert [b["key"] for b in bugs] == ["AP-1"]
    assert len(session.post_calls) == 1


def test_the_next_page_token_is_carried_to_the_next_request():
    session = FakeSession(posts=[
        page("AP-1", "AP-2", is_last=False, token="t2"),
        page("AP-3", is_last=True),
    ])
    bugs = make_client(session).fetch_bugs(max_results=2)
    assert [b["key"] for b in bugs] == ["AP-1", "AP-2", "AP-3"]
    assert session.post_calls[1][1]["json"]["nextPageToken"] == "t2"
    assert session.post_calls[1][1]["json"]["maxResults"] == 2


def test_a_missing_is_last_counts_as_last():
    """`data.get("isLast", True)` — a response without the field ends the loop."""
    session = FakeSession(posts=[page("AP-1", token="t2"), page("AP-2")])
    assert [b["key"] for b in make_client(session).fetch_bugs()] == ["AP-1"]


def test_no_next_token_stops_the_loop():
    session = FakeSession(posts=[page("AP-1", is_last=False), page("AP-2")])
    assert [b["key"] for b in make_client(session).fetch_bugs()] == ["AP-1"]
    assert len(session.post_calls) == 1


def test_a_page_without_issues_stops_the_loop():
    empty = FakeResponse(payload={"issues": [], "isLast": False})
    session = FakeSession(posts=[empty, page("AP-2")])
    assert make_client(session).fetch_bugs() == []
    assert len(session.post_calls) == 1


def test_paging_stops_after_fifty_pages():
    """max_pages = 50: an endless series of non-last pages is cut at 50 requests.
    Silently — see the module docstring and KNOWN-DEBT for why that is a defect
    with no test of its own."""
    endless = [page(f"AP-{i}", is_last=False, token=f"t{i + 1}") for i in range(60)]
    session = FakeSession(posts=endless)
    bugs = make_client(session).fetch_bugs(max_results=1)
    assert len(session.post_calls) == 50
    assert len(bugs) == 50


# --- _normalize_issue ------------------------------------------------------------------


def test_normalize_issue_maps_every_field():
    raw = issue(
        "AP-7",
        description="Sepet boşalıyor",
        priority={"name": "High"},
        status={"name": "In Progress"},
        components=[{"name": "Payment"}],
        created="2026-03-01T10:00:00.000+0300",
        updated="2026-03-02T11:00:00.000+0300",
        assignee={"displayName": "Ayşe"},
        reporter={"displayName": "Ali"},
        resolution={"name": "Fixed"},
        labels=["checkout", "regression"],
    )
    assert make_client()._normalize_issue(raw) == {
        "key": "AP-7",
        "summary": "summary AP-7",
        "description": "Sepet boşalıyor",
        "priority": "High",
        "status": "In Progress",
        "component": "Payment",
        "created": "2026-03-01T10:00:00.000+0300",
        "updated": "2026-03-02T11:00:00.000+0300",
        "assignee": "Ayşe",
        "reporter": "Ali",
        "resolution": "Fixed",
        "labels": ["checkout", "regression"],
    }


def test_normalize_issue_defaults_for_missing_or_null_fields():
    """Jira sends null for an unset priority/assignee/resolution; each has a default."""
    raw = {"key": "AP-8", "fields": {
        "priority": None, "status": None, "assignee": None, "reporter": None,
        "resolution": None, "components": [],
    }}
    normalized = make_client()._normalize_issue(raw)
    assert normalized["summary"] == ""
    assert normalized["description"] == ""
    assert normalized["priority"] == "Medium"
    assert normalized["status"] == "Open"
    assert normalized["component"] == "Unknown"
    people = (normalized["assignee"], normalized["reporter"], normalized["resolution"])
    assert people == ("", "", "")
    assert (normalized["created"], normalized["updated"], normalized["labels"]) == ("", "", [])


def test_normalize_issue_keeps_only_the_first_component():
    raw = issue("AP-9", components=[{"name": "Frontend"}, {"name": "Payment"}])
    assert make_client()._normalize_issue(raw)["component"] == "Frontend"


# --- errors while fetching -------------------------------------------------------------


def test_an_http_error_on_a_later_page_returns_the_pages_so_far():
    """raise_for_status() on page 2 is caught; the loop breaks and the page-1
    issues come back — no exception, no second attempt."""
    session = FakeSession(posts=[
        page("AP-1", is_last=False, token="t2"),
        FakeResponse(500, error=requests.HTTPError("500 Server Error")),
        page("AP-3", is_last=True),
    ])
    bugs = make_client(session).fetch_bugs()
    assert [b["key"] for b in bugs] == ["AP-1"]
    assert len(session.post_calls) == 2


def test_a_request_exception_on_the_first_page_returns_nothing():
    session = FakeSession(posts=[requests.Timeout("read timed out")])
    assert make_client(session).fetch_bugs() == []


# --- fetch_and_save ------------------------------------------------------------------------


@pytest.fixture
def bugs_file(tmp_path, monkeypatch):
    path = tmp_path / "data" / "bugs.json"
    monkeypatch.setattr(config, "BUGS_FILE", path)
    return path


def test_fetch_and_save_writes_utf8_json_and_creates_the_directory(bugs_file):
    raw = issue("AP-1", description="Ödeme başarısız")
    session = FakeSession(posts=[FakeResponse(payload={"issues": [raw], "isLast": True})])
    bugs = make_client(session).fetch_and_save()
    assert bugs_file.exists()
    text = bugs_file.read_text(encoding="utf-8")
    assert "Ödeme başarısız" in text  # ensure_ascii=False: no \\u escapes
    assert json.loads(text) == bugs


def test_fetch_and_save_survives_a_write_error(bugs_file):
    """An OSError while writing is logged and swallowed; the bugs still return."""
    bugs_file.mkdir(parents=True)  # a directory where the file should be
    session = FakeSession(posts=[page("AP-1", is_last=True)])
    assert [b["key"] for b in make_client(session).fetch_and_save()] == ["AP-1"]


PREVIOUS = b'[{"key": "AP-0", "summary": "previous good fetch"}]'


@pytest.mark.xfail(
    strict=True, reason=f"Bilinen kusur K1: kısmi liste bugs.json'u eziyor ({KNOWN_DEBT})"
)
def test_a_failed_later_page_keeps_the_previous_bugs_file(bugs_file):
    bugs_file.parent.mkdir(parents=True)
    bugs_file.write_bytes(PREVIOUS)
    session = FakeSession(posts=[
        page("AP-1", is_last=False, token="t2"),
        requests.ConnectionError("dropped"),
    ])
    with contextlib.suppress(Exception):  # returning or raising are both acceptable
        make_client(session).fetch_and_save()
    assert bugs_file.read_bytes() == PREVIOUS


@pytest.mark.xfail(
    strict=True,
    reason=f"Bilinen kusur K2: ilk sayfa hatası bugs.json'u '[]' yapıyor ({KNOWN_DEBT})",
)
def test_a_failed_first_page_keeps_the_previous_bugs_file(bugs_file):
    bugs_file.parent.mkdir(parents=True)
    bugs_file.write_bytes(PREVIOUS)
    session = FakeSession(posts=[requests.ConnectionError("dropped")])
    with contextlib.suppress(Exception):
        make_client(session).fetch_and_save()
    assert bugs_file.read_bytes() == PREVIOUS


# --- module functions ----------------------------------------------------------------------


def test_normalize_webhook_issue_maps_the_payload():
    payload = {"key": "AP-5", "fields": {
        "summary": "Login hatası", "description": "düz metin",
        "priority": {"name": "Highest"}, "status": {"name": "Open"},
        "components": [{"name": "Authentication"}, {"name": "Frontend"}],
        "created": "2026-03-05T09:00:00.000+0300",
    }}
    assert normalize_webhook_issue(payload) == {
        "key": "AP-5", "summary": "Login hatası", "description": "düz metin",
        "priority": "Highest", "status": "Open", "component": "Authentication",
        "created": "2026-03-05T09:00:00.000+0300",
    }


def test_normalize_webhook_issue_defaults():
    """Missing key, priority, status, components and created all have defaults;
    `created` defaults to the current local time in ISO form."""
    normalized = normalize_webhook_issue({"fields": {}})
    assert normalized["key"] == "UNKNOWN"
    assert (normalized["priority"], normalized["status"], normalized["component"]) == (
        "Medium", "Open", "Unknown",
    )
    assert datetime.fromisoformat(normalized["created"]).date() == datetime.now().date()


@pytest.mark.parametrize(
    ("payload", "expected"),
    [({"fields": {"issuetype": {"name": "Bug"}}}, "Bug"), ({}, "")],
    ids=["present", "absent"],
)
def test_get_webhook_issue_type(payload, expected):
    assert get_webhook_issue_type(payload) == expected


@pytest.mark.parametrize(
    "content",
    [None, b"{not json", b'{"key": "AP-1"}'],
    ids=["missing-file", "corrupt-json", "not-a-list"],
)
def test_load_bugs_from_file_returns_empty_on_bad_input(tmp_path, content):
    path = tmp_path / "bugs.json"
    if content is not None:
        path.write_bytes(content)
    assert load_bugs_from_file(path) == []


def test_load_bugs_from_file_defaults_to_bugs_file_outside_mock_mode(bugs_file, monkeypatch):
    monkeypatch.setattr(config, "USE_MOCK_DATA", False)
    bugs_file.parent.mkdir(parents=True)
    bugs_file.write_text('[{"key": "AP-1"}]', encoding="utf-8")
    assert load_bugs_from_file() == [{"key": "AP-1"}]


def _unconfigured(monkeypatch):
    monkeypatch.setattr(config, "USE_MOCK_DATA", False)
    for key in ("JIRA_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_PROJECT_KEY"):
        monkeypatch.setattr(config, key, "")


def test_refresh_data_without_jira_reads_the_saved_file(bugs_file, monkeypatch):
    _unconfigured(monkeypatch)
    bugs_file.parent.mkdir(parents=True)
    bugs_file.write_text('[{"key": "AP-2"}]', encoding="utf-8")
    assert refresh_data() == [{"key": "AP-2"}]


def test_refresh_data_with_jira_fetches_and_saves(monkeypatch):
    _unconfigured(monkeypatch)
    for key, value in (("JIRA_URL", BASE_URL), ("JIRA_EMAIL", "tester@example.invalid"),
                       ("JIRA_API_TOKEN", "placeholder-not-a-token"), ("JIRA_PROJECT_KEY", "AP")):
        monkeypatch.setattr(config, key, value)

    class StubClient:
        def fetch_and_save(self):
            return [{"key": "AP-3"}]

    monkeypatch.setattr(jira_client, "JiraClient", StubClient)
    assert refresh_data() == [{"key": "AP-3"}]
