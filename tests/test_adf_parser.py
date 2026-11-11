"""
What parse_adf_to_text returns today, branch by branch (Faz 6E-2a).

`parse_adf_to_text` (jira_client.py:25) turns a Jira Cloud rich-text field —
Atlassian Document Format, a nested JSON tree — into the plain text that the
vector store embeds and the LLM prompt quotes. ROADMAP's Faz 3 called this test
"the highest return" and it was never written: the 6E discovery's coverage run
(2026-11-09) found that not one line of the function executed under the suite,
not even indirectly, because nothing in the suite builds a JiraClient issue.

These are characterizations of the current code, not a specification of ADF.
Every expected value is read off the branch it exercises; the branch is named
in each docstring. No defect was found that needed an xfail.

The ADF nodes below are hand-written to the shape the function reads —
`type`, `text`, `content`, `attrs` — and nothing else. They are synthetic; no
real Jira payload is in this file.
"""

import pytest

from defect_risk_analyzer.jira_client import JiraClient, parse_adf_to_text


def text(value: str) -> dict:
    return {"type": "text", "text": value}


def node(node_type: str, *children: dict, **extra) -> dict:
    return {"type": node_type, "content": list(children), **extra}


# --- inputs that are not ADF nodes -----------------------------------------


def test_none_is_empty():
    """`if adf_node is None: return ""` — a missing description is not "None"."""
    assert parse_adf_to_text(None) == ""


def test_a_string_is_returned_as_is():
    """Server/Data Center instances send plain strings; they pass straight through."""
    assert parse_adf_to_text("Ödeme  sayfası\nçöküyor") == "Ödeme  sayfası\nçöküyor"


def test_a_list_joins_its_items_with_a_space():
    """The list branch joins every item's text with one space, empty ones included —
    unlike the container branch, which skips them (test_an_empty_child_is_skipped)."""
    assert parse_adf_to_text([text("a"), text("b"), "c"]) == "a b c"
    assert parse_adf_to_text([text("a"), {"type": "hardBreak"}, text("b")]) == "a  b"


def test_a_scalar_that_is_not_a_node_is_empty():
    """Anything that is neither None, str, list nor dict falls to `return ""`."""
    assert parse_adf_to_text(42) == ""


def test_a_text_node_returns_its_text():
    """`type == "text"` returns `text` directly and ignores any `content`."""
    assert parse_adf_to_text({"type": "text", "text": "login", "content": [text("x")]}) == "login"


# --- container nodes ---------------------------------------------------------

# Every type the function names in its if/elif chain. Each one joins its
# non-empty children with a single space; the chain has nine branches, two of
# which accept two types each, so eleven types in all.
CONTAINER_TYPES = [
    "paragraph",
    "heading",
    "bulletList",
    "orderedList",
    "listItem",
    "codeBlock",
    "blockquote",
    "table",
    "tableRow",
    "tableCell",
    "tableHeader",
]


@pytest.mark.parametrize("node_type", CONTAINER_TYPES)
def test_container_types_join_children(node_type):
    """Each named container returns `" ".join(parts)` of its children.

    The second assertion is the only thing that tells a named container apart
    from the unnamed fall-through: with children, both join them identically,
    so deleting a branch from the chain would change nothing. Without children
    but with a stray `text` field, a named container returns "" while the
    fall-through returns that `text`. Found by mutation (6E-2a, MA1)."""
    assert parse_adf_to_text(node(node_type, text("one"), text("two"))) == "one two"
    assert parse_adf_to_text({"type": node_type, "text": "stray"}) == ""


# --- inline nodes that carry their text in attrs -----------------------------

INLINE = [
    ("mention", {"text": "@Ayşe"}, "@Ayşe"),
    ("inlineCard", {"url": "https://example.invalid/AP-1"}, "https://example.invalid/AP-1"),
    ("emoji", {"shortName": ":warning:"}, ":warning:"),
]


@pytest.mark.parametrize(("node_type", "attrs", "expected"), INLINE, ids=[i[0] for i in INLINE])
def test_inline_nodes_read_their_attrs(node_type, attrs, expected):
    """mention → attrs.text, inlineCard → attrs.url, emoji → attrs.shortName."""
    assert parse_adf_to_text({"type": node_type, "attrs": attrs}) == expected


@pytest.mark.parametrize("node_type", [i[0] for i in INLINE])
def test_inline_nodes_without_attrs_are_empty(node_type):
    """`adf_node.get("attrs", {}).get(...)` — no attrs, or the wrong key, is ""."""
    assert parse_adf_to_text({"type": node_type}) == ""
    assert parse_adf_to_text({"type": node_type, "attrs": {"other": "x"}}) == ""


# --- nodes the chain does not name ------------------------------------------


def test_an_unknown_node_with_children_joins_them():
    """The fall-through `" ".join(parts) if parts else text` — `doc` and `panel`
    are not in the chain, yet their children still come out."""
    document = node("doc", node("panel", text("inside"), text("panel")))
    assert parse_adf_to_text(document) == "inside panel"


@pytest.mark.parametrize(
    ("leaf", "expected"),
    [
        ({"type": "hardBreak"}, ""),
        ({"type": "status", "text": "IN REVIEW"}, "IN REVIEW"),
    ],
    ids=["hardBreak", "unknown-with-text"],
)
def test_an_unknown_leaf_returns_its_text_or_nothing(leaf, expected):
    """With no children the fall-through returns the node's own `text`, default ""."""
    assert parse_adf_to_text(leaf) == expected


def test_an_empty_child_is_skipped_not_joined():
    """`if child_text: parts.append(...)` — a hardBreak between two words leaves
    one space, not two. (The list branch has no such filter; see the list test.)"""
    paragraph = node("paragraph", text("first"), {"type": "hardBreak"}, text("second"))
    assert parse_adf_to_text(paragraph) == "first second"


def test_a_nested_jira_document():
    """A realistic description: heading, paragraph with a mention, a bullet list,
    a code block and a table — flattened depth-first, joined by single spaces."""
    document = node(
        "doc",
        node("heading", text("Ödeme hatası"), attrs={"level": 2}),
        node("paragraph", text("Rapor eden"), {"type": "mention", "attrs": {"text": "@Ali"}}),
        node(
            "bulletList",
            node("listItem", node("paragraph", text("Sepete ürün ekle"))),
            node("listItem", node("paragraph", text("Öde butonuna bas"))),
        ),
        node("codeBlock", text("HTTP 502")),
        node(
            "table",
            node("tableRow", node("tableHeader", node("paragraph", text("Adım")))),
            node("tableRow", node("tableCell", node("paragraph", text("3")))),
        ),
    )
    assert parse_adf_to_text(document) == (
        "Ödeme hatası Rapor eden @Ali Sepete ürün ekle Öde butonuna bas HTTP 502 Adım 3"
    )


# --- where a JiraClient issue's description goes through the parser ----------


@pytest.fixture
def client() -> JiraClient:
    # Explicit arguments, so the constructor reads nothing from config and no
    # request is ever made — _normalize_issue is pure.
    return JiraClient(
        url="https://jira.example.invalid",
        email="tester@example.invalid",
        api_token="synthetic-token-0000",
        project_key="AP",
    )


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        (node("doc", node("paragraph", text("  ADF açıklama  "))), "ADF açıklama"),
        ("  düz metin  ", "düz metin"),
        (None, ""),
    ],
    ids=["adf-dict", "plain-string", "missing"],
)
def test_normalize_issue_description_branches(client, description, expected):
    """_normalize_issue: a dict goes through parse_adf_to_text, a str is used
    as-is, anything else is ""; the result is stripped either way."""
    issue = {"key": "AP-1", "fields": {"summary": "s", "description": description}}
    assert client._normalize_issue(issue)["description"] == expected
