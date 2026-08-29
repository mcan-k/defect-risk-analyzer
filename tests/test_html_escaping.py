"""Nothing reaches raw HTML unescaped.

WHY. `st.markdown(..., unsafe_allow_html=True)` hands its argument to
react-markdown with `rehypeRaw` in the pipeline, and there is no sanitizer in
that path. Measured in the shipped bundle (streamlit 1.41.1,
`static/static/js/index.Phesr84n.js`):

    const Ht=[rehypeKatex, ...tt?[rehypeRaw]:[]]

DOMPurify 3.1.7 IS in the bundle, but only in the `stHtml` chunk
(`index.CbuYSrVP.js`, `data-testid":"stHtml"`) — that is `st.html()`, which this
project never calls. So the protection that does exist comes from React 18.3.1,
not from a sanitizer: `<script>` is built through the
`div.innerHTML="<script><\\/script>"` trick and is inert on insertion, and
attributes whose name starts with `on` are dropped by React's attribute writer.
What React does NOT stop is markup: `transformLinkUri` is overridden to the
identity function (`function transformLinkUri(tt){return tt}`), and no
Content-Security-Policy is set anywhere, so an injected
`<img src="https://attacker/…">` fires a request the moment the page renders.

Faz 6C fixed the two call sites that embedded raw Jira fields. This guard exists
because that fix is bound to the call site: the next `unsafe_allow_html` block
anyone writes would not inherit it, and before this file nothing in the suite
looked at the question at all.

WHAT IS MATCHED. Every call carrying a literal `unsafe_allow_html=True`. Its
first positional argument falls into exactly one of three classes, and each
class has a different obligation:

  1. CONSTANT — a literal, or an f-string with no interpolation. Nothing to
     check. The file must be named in CONSTANT_HTML.
  2. INLINE — an f-string, `.format()`, `%`, or concatenation whose interpolated
     values are visible right here. Every value must be wrapped in
     `html.escape(...)`, or listed in ALLOWED_UNESCAPED with a reason.
  3. OPAQUE — anything else: a bare name, a call, a comprehension result. The
     body was built somewhere else and cannot be judged in place. It must be
     listed in OPAQUE_BODIES with a reason and with whatever pins it.

The third class is not pedantry. `pages/buglar.py` passes `keyword_tags`, a name
built by a generator expression above the call. A two-class guard would file
that under CONSTANT, pass it for the wrong reason, and quietly widen the
constant-only claim this file makes about `theme.py`.

KEYED ON `ast.unparse`, NOT ON LINE NUMBERS. Faz 6A's entry-point guard names
files; naming lines here would break on every insertion above a call site. The
unparsed expression travels with the code and puts the reason next to the thing
it excuses.

THE results.py ASYMMETRY IS DELIBERATE. `ui/results.py` interpolates `color`
without escaping it, while `ui/app.py` escapes the same expression. That looks
inconsistent and is not an oversight: results.py was measured and left out of
Faz 6C's scope, and the one real gap behind it — `theme.py::risk_level_label`
returning an unrecognised level unchanged — is filed separately in
docs/KNOWN-DEBT.md with its own trigger. Wrapping results.py "for consistency"
is a scope extension, not a tidy-up: it touches a file the phase deliberately
did not open. Take that decision on purpose or not at all.

DECLARED BLIND SPOTS. Limits of this guard, stated so a green run is not
mistaken for a proof:

  * Only `ui/` is scanned. An `unsafe_allow_html` call added anywhere else is
    invisible here.
  * Only a literal `True` is matched. `unsafe_allow_html=flag` is not seen.
  * `st.html()` is out of scope — this project does not call it, and that path
    goes through DOMPurify anyway.
  * The guard sees that `html.escape` is CALLED, not that it is right for the
    position. A value escaped with `quote=False` and dropped into an attribute
    passes here.
  * The inside of an OPAQUE body is not inspected. Its entry is worth exactly
    the reason written next to it and the test that pins it.
  * The markdown-link surface is a different subject and is not covered:
    `transformLinkUri` being the identity function affects plain `st.markdown`
    too, with no `unsafe_allow_html` involved. See docs/KNOWN-DEBT.md.
"""

import ast
from pathlib import Path

import pytest

from defect_risk_analyzer.pattern_detector import _extract_common_keywords
from defect_risk_analyzer.ui import i18n

#: The shipped ui/ tree, derived rather than hard-coded — same idiom as
#: tests/test_i18n_locales.py, so moving the package moves the scan with it.
UI_DIR = Path(i18n.__file__).resolve().parent

#: Characters that would change the shape of the surrounding HTML.
HTML_META = set("<>&\"'")


# ---------------------------------------------------------------------------
# The three hand-kept declarations
# ---------------------------------------------------------------------------

#: Files whose every unsafe_allow_html call is a literal with no interpolation.
#: Asserted in both directions: adding an interpolation to one of these files
#: drops it out of the class and goes red.
CONSTANT_HTML: dict[str, str] = {
    "theme.py": (
        "inject_css() — one literal <style> block, no interpolation at all. The "
        "rules hide elements, set geometry and set per-element alpha colours; "
        "none of them carries text from outside."
    ),
}

#: Bodies built somewhere other than the call. Keyed by (file, unparsed body).
OPAQUE_BODIES: dict[tuple[str, str], str] = {
    ("pages/buglar.py", "keyword_tags"): (
        "Pattern keyword tags, built by the generator expression above the call. "
        "Safe because pattern_detector._extract_common_keywords tokenises with "
        "[a-zA-ZçğıöşüÇĞİÖŞÜ]{3,}, which cannot emit an HTML metacharacter. "
        "That boundary is not assumed here — "
        "test_keyword_tokeniser_cannot_emit_html_metacharacters pins it."
    ),
}

#: Interpolated values excused from html.escape. Keyed by (file, unparsed expr).
ALLOWED_UNESCAPED: dict[tuple[str, str], str] = {
    ("results.py", "t('result.risk_score')"): (
        "A message catalog lookup. Both shipped locales were measured — 262 keys "
        "each, and not one value carries <, > or &. The catalogs are repo "
        "content, not input."
    ),
    ("results.py", "color"): (
        "RISK_COLORS lookup with a literal '#666' default — a hex constant from "
        "a module-level dict, never external text."
    ),
    ("results.py", "risk_score"): (
        "int computed by core/scoring.py; api_models.py:74 pins it as "
        "Field(ge=0, le=100) on the way through the API."
    ),
    ("results.py", "risk_level_label(risk_level)"): (
        "The i18n spelling of one of four English constants. An unrecognised "
        "level is passed through unchanged — deliberate, and filed in "
        "docs/KNOWN-DEBT.md with its own trigger rather than patched here."
    ),
}

#: Measured, not assumed. Asserted as a set so a broken scan root cannot sit
#: green while inspecting zero files — the lesson from Faz 6A's T17.
EXPECTED_RAW_HTML_FILES = {
    "app.py",
    "pages/buglar.py",
    "results.py",
    "theme.py",
}


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------

def _sources(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _raw_html_calls(tree: ast.Module):
    """Every call carrying a literal `unsafe_allow_html=True`."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if (
                keyword.arg == "unsafe_allow_html"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
            ):
                yield node
                break


def _classify(body: ast.expr) -> tuple[str, list[ast.expr]]:
    """One of the three classes in the module docstring, plus its values."""
    if isinstance(body, ast.Constant):
        return "constant", []

    if isinstance(body, ast.JoinedStr):
        values = [
            part.value for part in body.values if isinstance(part, ast.FormattedValue)
        ]
        return ("inline", values) if values else ("constant", [])

    if isinstance(body, ast.BinOp) and isinstance(body.op, ast.Add):
        values: list[ast.expr] = []
        for side in (body.left, body.right):
            kind, side_values = _classify(side)
            values.extend(side_values if kind != "opaque" else [side])
        return ("inline", values) if values else ("constant", [])

    if isinstance(body, ast.BinOp) and isinstance(body.op, ast.Mod):
        if not isinstance(body.left, ast.Constant):
            return "opaque", []
        right = body.right
        parts = right.elts if isinstance(right, ast.Tuple) else [right]
        return "inline", list(parts)

    if (
        isinstance(body, ast.Call)
        and isinstance(body.func, ast.Attribute)
        and body.func.attr == "format"
        and isinstance(body.func.value, ast.Constant)
    ):
        return "inline", list(body.args) + [k.value for k in body.keywords]

    return "opaque", []


def _is_escaped(node: ast.expr) -> bool:
    """A `html.escape(...)` call. Matched on the call node, never on text."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "escape"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "html"
    )


def scan(root: Path) -> tuple[set[str], list[str]]:
    """Files carrying raw-HTML calls, and everything that fails the rule."""
    files: set[str] = set()
    offenders: list[str] = []

    for path in _sources(root):
        rel = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))

        for call in _raw_html_calls(tree):
            files.add(rel)

            if not call.args:
                offenders.append(
                    f"{rel}:{call.lineno} body is not passed positionally, so it "
                    f"cannot be judged in place"
                )
                continue

            kind, values = _classify(call.args[0])

            if kind == "constant":
                if rel not in CONSTANT_HTML:
                    offenders.append(
                        f"{rel}:{call.lineno} constant HTML from an undeclared "
                        f"file — add it to CONSTANT_HTML with a reason"
                    )
                continue

            if kind == "opaque":
                key = (rel, ast.unparse(call.args[0]))
                if key not in OPAQUE_BODIES:
                    offenders.append(
                        f"{rel}:{call.lineno} opaque body {key[1]!r} — built "
                        f"elsewhere, so it needs an OPAQUE_BODIES entry"
                    )
                continue

            for value in values:
                if _is_escaped(value):
                    continue
                key = (rel, ast.unparse(value))
                if key not in ALLOWED_UNESCAPED:
                    offenders.append(
                        f"{rel}:{call.lineno} unescaped {key[1]!r} — wrap it in "
                        f"html.escape() or give it an ALLOWED_UNESCAPED reason"
                    )

    return files, offenders


# ---------------------------------------------------------------------------
# The guard works in both directions, on a synthetic tree
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_ui(tmp_path):
    """One file per class, including the two that must be flagged."""
    (tmp_path / "escaped.py").write_text(
        'import html\nst.markdown(f"<b>{html.escape(name)}</b>", '
        "unsafe_allow_html=True)\n",
        encoding="utf-8",
    )
    (tmp_path / "bare.py").write_text(
        'st.markdown(f"<b>{name}</b>", unsafe_allow_html=True)\n',
        encoding="utf-8",
    )
    (tmp_path / "constant.py").write_text(
        'st.markdown("<style>a{color:red}</style>", unsafe_allow_html=True)\n',
        encoding="utf-8",
    )
    (tmp_path / "opaque.py").write_text(
        "st.markdown(built_elsewhere, unsafe_allow_html=True)\n",
        encoding="utf-8",
    )
    return tmp_path


def test_the_guard_flags_every_undeclared_class(synthetic_ui):
    """A guard that never flags anything is the failure this test exists for.

    All three failing shapes at once: an unescaped interpolation, an opaque body
    with no entry, and a constant in a file no declaration names.
    """
    files, offenders = scan(synthetic_ui)

    assert files == {"escaped.py", "bare.py", "constant.py", "opaque.py"}

    flagged = {line.split(":")[0] for line in offenders}
    assert flagged == {"bare.py", "constant.py", "opaque.py"}, offenders


def test_escaping_the_value_clears_the_flag(synthetic_ui):
    """The other direction, measured rather than assumed."""
    offender = synthetic_ui / "bare.py"
    assert any(line.startswith("bare.py") for line in scan(synthetic_ui)[1])

    offender.write_text(
        'import html\nst.markdown(f"<b>{html.escape(name)}</b>", '
        "unsafe_allow_html=True)\n",
        encoding="utf-8",
    )

    assert not any(line.startswith("bare.py") for line in scan(synthetic_ui)[1])


def test_an_empty_scan_root_is_not_green(tmp_path):
    """A broken glob or a wrong root must not read as compliance.

    `scan` finds nothing in an empty tree and reports no offenders — which is
    exactly why the repo test below asserts the FILE SET and not just the
    absence of offenders.
    """
    files, offenders = scan(tmp_path)

    assert files == set()
    assert offenders == []
    assert files != EXPECTED_RAW_HTML_FILES


# ---------------------------------------------------------------------------
# The real tree
# ---------------------------------------------------------------------------

def test_no_unescaped_value_reaches_raw_html_in_ui():
    """EXPECTED GREEN, and it asserts the set, not just the absence.

    Asserting only "nothing was flagged" would pass on an empty discovery, as
    test_an_empty_scan_root_is_not_green demonstrates. So the four measured
    files are named and the guard must have looked at all of them.
    """
    files, offenders = scan(UI_DIR)

    assert files == EXPECTED_RAW_HTML_FILES
    assert offenders == [], "unescaped values reaching raw HTML: " + "; ".join(offenders)


def test_every_declaration_is_still_used():
    """A declaration nobody needs is a stale excuse, not a safety net.

    Each entry names a call site that exists today. When one is fixed or
    deleted, this goes red so the reason is removed with it instead of sitting
    here excusing nothing.
    """
    _, offenders = scan(UI_DIR)
    assert offenders == []

    live_constant = set()
    live_opaque = set()
    live_allowed = set()

    for path in _sources(UI_DIR):
        rel = path.relative_to(UI_DIR).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for call in _raw_html_calls(tree):
            if not call.args:
                continue
            kind, values = _classify(call.args[0])
            if kind == "constant":
                live_constant.add(rel)
            elif kind == "opaque":
                live_opaque.add((rel, ast.unparse(call.args[0])))
            else:
                live_allowed |= {
                    (rel, ast.unparse(v)) for v in values if not _is_escaped(v)
                }

    assert set(CONSTANT_HTML) == live_constant
    assert set(OPAQUE_BODIES) == live_opaque
    assert set(ALLOWED_UNESCAPED) == live_allowed


# ---------------------------------------------------------------------------
# What the OPAQUE_BODIES entry rests on
# ---------------------------------------------------------------------------

def test_keyword_tokeniser_cannot_emit_html_metacharacters():
    """The boundary the `keyword_tags` excuse depends on.

    pattern_detector._extract_common_keywords tokenises with a letters-only
    character class, so a bug summary carrying markup contributes words and
    never the markup itself. Loosening that regex has to fail here, because the
    guard above trusts this and inspects nothing inside the generator.

    The non-empty assertion is load-bearing: a tokeniser that returned nothing
    would satisfy the metacharacter check for free.
    """
    bugs = [
        {
            "summary": '<img src=x onerror="alert(1)"> checkout failure',
            "description": "<a href='javascript:void(0)'>timeout</a> on payment",
        }
    ]

    keywords = _extract_common_keywords(bugs)

    assert keywords, "tokeniser returned nothing, so the check below proves nothing"
    for word in keywords:
        assert not HTML_META & set(word), f"tokeniser emitted markup: {word!r}"
