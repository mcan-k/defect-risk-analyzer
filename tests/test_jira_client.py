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
`JiraClient.MAX_PAGES = 50` — so at most 10,000 issues with the default page size.

THE THREE DEFECTS PR 2 RECORDED ARE FIXED (6E-2 PR 5; KNOWN-DEBT, "JiraClient
kusurları"), and their tests now pin the chosen design exactly — user decisions
of 2026-11-13:
  K1/K2  any failed page raises JiraFetchError (page number, the request error
         as __cause__) and the previous bugs.json survives byte for byte;
  K3     hitting the page cap still saves what came back, sets
         FetchResult.truncated and writes one WARNING line — tested with the cap
         lowered, not with thousands of fake issues;
  K4     a bugs.json that cannot be written raises OSError instead of being
         logged and swallowed; the write is atomic, so the old file is intact.
"""

import json
import logging
from datetime import datetime

import pytest
import requests

from defect_risk_analyzer import config, jira_client
from defect_risk_analyzer.jira_client import (
    FetchResult,
    JiraClient,
    JiraFetchError,
    get_webhook_issue_type,
    load_bugs_from_file,
    normalize_webhook_issue,
    refresh_data,
)

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
    bugs = make_client(session).fetch_bugs().bugs
    assert [b["key"] for b in bugs] == ["AP-1"]
    assert len(session.post_calls) == 1


def test_the_next_page_token_is_carried_to_the_next_request():
    session = FakeSession(posts=[
        page("AP-1", "AP-2", is_last=False, token="t2"),
        page("AP-3", is_last=True),
    ])
    bugs = make_client(session).fetch_bugs(max_results=2).bugs
    assert [b["key"] for b in bugs] == ["AP-1", "AP-2", "AP-3"]
    assert session.post_calls[1][1]["json"]["nextPageToken"] == "t2"
    assert session.post_calls[1][1]["json"]["maxResults"] == 2


def test_a_missing_is_last_counts_as_last():
    """`data.get("isLast", True)` — a response without the field ends the loop."""
    session = FakeSession(posts=[page("AP-1", token="t2"), page("AP-2")])
    assert [b["key"] for b in make_client(session).fetch_bugs().bugs] == ["AP-1"]


def test_no_next_token_stops_the_loop():
    session = FakeSession(posts=[page("AP-1", is_last=False), page("AP-2")])
    assert [b["key"] for b in make_client(session).fetch_bugs().bugs] == ["AP-1"]
    assert len(session.post_calls) == 1


def test_a_page_without_issues_stops_the_loop():
    empty = FakeResponse(payload={"issues": [], "isLast": False})
    session = FakeSession(posts=[empty, page("AP-2")])
    assert make_client(session).fetch_bugs() == FetchResult([], False)
    assert len(session.post_calls) == 1


def test_paging_stops_after_fifty_pages():
    """MAX_PAGES = 50: an endless series of non-last pages is cut at 50 requests,
    and the cut is flagged (K3) — the cap itself is unchanged."""
    endless = [page(f"AP-{i}", is_last=False, token=f"t{i + 1}") for i in range(60)]
    session = FakeSession(posts=endless)
    result = make_client(session).fetch_bugs(max_results=1)
    assert len(session.post_calls) == 50
    assert len(result.bugs) == 50
    assert result.truncated is True


# --- the page cap (K3) ---------------------------------------------------------------


@pytest.fixture
def two_page_cap(monkeypatch):
    """The cap lowered to two pages: K3 without ten thousand fake issues."""
    monkeypatch.setattr(JiraClient, "MAX_PAGES", 2)


def test_hitting_the_page_cap_is_flagged_and_logged(two_page_cap, caplog):
    """Jira still says "more" after the last allowed page: the bugs so far come
    back, `truncated` is True, and exactly one WARNING line says so."""
    session = FakeSession(posts=[
        page("AP-1", is_last=False, token="t2"),
        page("AP-2", is_last=False, token="t3"),
        page("AP-3", is_last=True),
    ])
    with caplog.at_level(logging.INFO, logger=jira_client.__name__):
        result = make_client(session).fetch_bugs()

    assert result.truncated is True
    assert [b["key"] for b in result.bugs] == ["AP-1", "AP-2"]
    assert len(session.post_calls) == 2
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "page cap reached" in warnings[0].getMessage()
    assert "2 bugs fetched" in warnings[0].getMessage()


def test_a_last_page_exactly_at_the_cap_is_not_flagged(two_page_cap, caplog):
    """Using every allowed page is not the same as being cut short."""
    session = FakeSession(posts=[
        page("AP-1", is_last=False, token="t2"),
        page("AP-2", is_last=True),
    ])
    with caplog.at_level(logging.WARNING, logger=jira_client.__name__):
        result = make_client(session).fetch_bugs()

    assert [b["key"] for b in result.bugs] == ["AP-1", "AP-2"]
    assert result.truncated is False
    assert caplog.records == []


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


def test_an_http_error_on_a_later_page_raises_jira_fetch_error(caplog):
    """raise_for_status() on page 2: the page-1 issues are dropped, not returned
    as if they were the whole project. No second attempt; the request error is
    chained and logged."""
    http_error = requests.HTTPError("500 Server Error")
    session = FakeSession(posts=[
        page("AP-1", is_last=False, token="t2"),
        FakeResponse(500, error=http_error),
        page("AP-3", is_last=True),
    ])
    with caplog.at_level(logging.ERROR, logger=jira_client.__name__), \
            pytest.raises(JiraFetchError) as raised:
        make_client(session).fetch_bugs()

    assert raised.value.page == 2
    assert raised.value.__cause__ is http_error
    assert str(raised.value) == "Jira search failed on page 2; nothing was saved."
    assert not isinstance(raised.value, OSError)  # call() would call it a disk error
    assert len(session.post_calls) == 2
    assert "Jira API error on page 2: 500 Server Error" in caplog.text


def test_a_request_exception_on_the_first_page_raises_jira_fetch_error():
    timeout = requests.Timeout("read timed out")
    session = FakeSession(posts=[timeout])
    with pytest.raises(JiraFetchError) as raised:
        make_client(session).fetch_bugs()
    assert raised.value.page == 1
    assert raised.value.__cause__ is timeout


def test_a_page_that_is_not_json_raises_jira_fetch_error():
    """A proxy's HTML error page: requests' JSONDecodeError is a RequestException."""

    class NotJson(FakeResponse):
        def json(self):
            raise requests.exceptions.JSONDecodeError("Expecting value", "<html>", 0)

    session = FakeSession(posts=[page("AP-1", is_last=False, token="t2"), NotJson()])
    with pytest.raises(JiraFetchError) as raised:
        make_client(session).fetch_bugs()
    assert raised.value.page == 2
    assert isinstance(raised.value.__cause__, requests.exceptions.JSONDecodeError)


# --- fetch_and_save ------------------------------------------------------------------------


@pytest.fixture
def bugs_file(tmp_path, monkeypatch):
    path = tmp_path / "data" / "bugs.json"
    monkeypatch.setattr(config, "BUGS_FILE", path)
    return path


def _left_in(directory):
    """Every name in the data directory: a leftover temporary file shows up here."""
    return sorted(p.name for p in directory.iterdir())


def test_fetch_and_save_writes_utf8_json_and_creates_the_directory(bugs_file):
    raw = issue("AP-1", description="Ödeme başarısız")
    session = FakeSession(posts=[FakeResponse(payload={"issues": [raw], "isLast": True})])
    result = make_client(session).fetch_and_save()
    assert bugs_file.exists()
    text = bugs_file.read_text(encoding="utf-8")
    assert "Ödeme başarısız" in text  # ensure_ascii=False: no \\u escapes
    assert json.loads(text) == result.bugs
    assert result.truncated is False
    assert _left_in(bugs_file.parent) == ["bugs.json"]


def test_fetch_and_save_raises_when_the_file_cannot_be_written(bugs_file):
    """K4: an OSError while writing reaches the caller; it used to be logged and
    swallowed, and the user was told the sync had worked."""
    bugs_file.mkdir(parents=True)  # a directory where the file should be
    session = FakeSession(posts=[page("AP-1", is_last=True)])
    with pytest.raises(OSError):
        make_client(session).fetch_and_save()
    assert bugs_file.is_dir()
    assert _left_in(bugs_file.parent) == ["bugs.json"]


PREVIOUS = b'[{"key": "AP-0", "summary": "previous good fetch"}]'


@pytest.fixture
def previous_file(bugs_file):
    """A bugs.json from an earlier good fetch."""
    bugs_file.parent.mkdir(parents=True)
    bugs_file.write_bytes(PREVIOUS)
    return bugs_file


def test_a_failed_later_page_keeps_the_previous_bugs_file(previous_file):
    """K1: page 1 arrived, page 2 failed. Raises, and nothing is written."""
    dropped = requests.ConnectionError("dropped")
    session = FakeSession(posts=[page("AP-1", is_last=False, token="t2"), dropped])
    with pytest.raises(JiraFetchError) as raised:
        make_client(session).fetch_and_save()
    assert raised.value.page == 2
    assert raised.value.__cause__ is dropped
    assert previous_file.read_bytes() == PREVIOUS
    assert _left_in(previous_file.parent) == ["bugs.json"]


def test_a_failed_first_page_keeps_the_previous_bugs_file(previous_file):
    """K2: nothing arrived. Raises; the file is not emptied to '[]'."""
    dropped = requests.ConnectionError("dropped")
    session = FakeSession(posts=[dropped])
    with pytest.raises(JiraFetchError) as raised:
        make_client(session).fetch_and_save()
    assert raised.value.page == 1
    assert raised.value.__cause__ is dropped
    assert previous_file.read_bytes() == PREVIOUS
    assert _left_in(previous_file.parent) == ["bugs.json"]


def test_a_fetch_cut_by_the_cap_is_saved_and_flagged(two_page_cap, bugs_file):
    """K3 decision: what came back is saved; the caller learns it is not all."""
    session = FakeSession(posts=[
        page("AP-1", is_last=False, token="t2"),
        page("AP-2", is_last=False, token="t3"),
    ])
    result = make_client(session).fetch_and_save()
    assert result.truncated is True
    assert [b["key"] for b in json.loads(bugs_file.read_text(encoding="utf-8"))] == [
        "AP-1", "AP-2",
    ]


def test_a_failed_replace_keeps_the_previous_file_and_raises(previous_file, monkeypatch):
    """K4 with a previous file: the last step fails (a reader holds bugs.json open
    on Windows, say). OSError reaches the caller, the old file is untouched and
    the temporary file is gone."""

    def locked(src, dst):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(jira_client.os, "replace", locked)
    session = FakeSession(posts=[page("AP-1", is_last=True)])
    with pytest.raises(PermissionError):
        make_client(session).fetch_and_save()
    assert previous_file.read_bytes() == PREVIOUS
    assert _left_in(previous_file.parent) == ["bugs.json"]


def test_a_write_that_fails_part_way_leaves_the_old_file_whole(previous_file, monkeypatch):
    """The atomic write: half the JSON is out when the disk fills up. A direct
    write would have truncated bugs.json already; this one never opened it."""

    def disk_full(data, f, **kwargs):
        f.write('[{"key": "AP-1", "summ')
        f.flush()
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(jira_client.json, "dump", disk_full)
    session = FakeSession(posts=[page("AP-1", is_last=True)])
    with pytest.raises(OSError):
        make_client(session).fetch_and_save()
    assert previous_file.read_bytes() == PREVIOUS
    assert _left_in(previous_file.parent) == ["bugs.json"]


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
    assert refresh_data() == FetchResult([{"key": "AP-2"}], False)


def test_refresh_data_with_jira_fetches_and_saves(monkeypatch):
    """fetch_and_save()'s result is passed through whole — the cap flag included."""
    _unconfigured(monkeypatch)
    for key, value in (("JIRA_URL", BASE_URL), ("JIRA_EMAIL", "tester@example.invalid"),
                       ("JIRA_API_TOKEN", "placeholder-not-a-token"), ("JIRA_PROJECT_KEY", "AP")):
        monkeypatch.setattr(config, key, value)

    class StubClient:
        def fetch_and_save(self):
            return FetchResult([{"key": "AP-3"}], True)

    monkeypatch.setattr(jira_client, "JiraClient", StubClient)
    assert refresh_data() == FetchResult([{"key": "AP-3"}], True)
