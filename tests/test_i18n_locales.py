"""The locale contract: what the message catalogs promise each other.

No Streamlit here on purpose. ui/i18n.py does not import it, so the whole
contract — key sets, empty values, the fallback, the crash — is checkable in
milliseconds instead of behind an AppTest run. The rendered-page half of i18n
lives in tests/test_dashboard_language.py and is marked slow.

The four `finding.` assertions are the third copy of the same four sentences.
They started in tests/test_blind_spots.py, moved to tests/test_ui_messages.py
when Phase 5A converted the detector to code/params, and are repeated here
because 5C moved the wording again — out of Python and into tr.json. Each move
is only "the text moved" if the strings are still character for character the
same, and that is what these compare.
"""

import ast
import json
import re
from pathlib import Path

import pytest

from defect_risk_analyzer.ui import i18n, theme
from defect_risk_analyzer.ui.messages import TEMPLATES

UI_DIR = Path(i18n.__file__).resolve().parent


@pytest.fixture(scope="module")
def catalogs() -> dict[str, dict[str, str]]:
    """Every shipped locale, read through the module under test."""
    return {language: i18n.catalog(language) for language in i18n.LANGUAGES}


# =============================================================================
# The two files agree
# =============================================================================

def test_every_shipped_language_has_a_catalog(catalogs):
    """LANGUAGES is what the selector offers; a name with no file is a dead option."""
    assert set(catalogs) == set(i18n.LANGUAGES)
    assert i18n.SOURCE_LANGUAGE in catalogs


def test_locale_key_sets_match(catalogs):
    """The whole reason the source-language fallback is a safety net.

    i18n.translate() falls back to the source language for a key the active
    locale lacks, so a gap would not crash — it would silently render Turkish
    inside an English page and only the log would say so. This test is what
    makes that path unreachable in a shipped build, which is the difference
    between a safety net and an excuse.
    """
    source_keys = set(catalogs[i18n.SOURCE_LANGUAGE])

    for language, catalog in catalogs.items():
        if language == i18n.SOURCE_LANGUAGE:
            continue
        missing = sorted(source_keys - set(catalog))
        extra = sorted(set(catalog) - source_keys)
        assert not missing, f"{language}.json is missing: {missing}"
        assert not extra, f"{language}.json has keys no other locale defines: {extra}"


def test_no_message_is_empty(catalogs):
    """An empty value renders as a gap, which is the failure mode i18n exists to avoid."""
    blank = [
        f"{language}:{key}"
        for language, catalog in catalogs.items()
        for key, value in catalog.items()
        if not value.strip()
    ]
    assert not blank, f"empty messages: {blank}"


def test_keys_are_flat_and_sorted(catalogs):
    """Flat dotted keys, stored sorted.

    Sorted because the files are reviewed side by side: an unsorted catalog
    makes a two-line translation diff look like a rewrite. Flat because a
    nested schema would need a flattener before any of the checks above, and
    would raise the question of what a dict-valued key means.
    """
    for language in catalogs:
        raw = json.loads(
            (i18n.LOCALES_DIR / f"{language}.json").read_text(encoding="utf-8")
        )
        assert all(isinstance(value, str) for value in raw.values()), language
        assert list(raw) == sorted(raw), f"{language}.json is not sorted by key"


# =============================================================================
# The four sentences, unchanged across two migrations
# =============================================================================

BLIND_SPOT_SENTENCES_TR = {
    "finding.unanalyzed_risky_module": (
        "{module} modülü {risk_level} risk seviyesinde ancak henüz analiz "
        "edilmemiş. Analiz sayfasından analiz yapın."
    ),
    "finding.neglected_critical_bug": (
        "{key} — {priority} öncelikli bug {days_open} gündür '{status}' "
        "durumunda. Acil müdahale gerekiyor."
    ),
    "finding.stale_bug": (
        "{key} — {days_open} gündür açık. Çözüm süresi beklentinin üzerinde."
    ),
    "finding.rising_unattended_module": (
        "{module} modülünde bug sayısı artıyor ({recent_bugs} yeni bug) ancak "
        "üzerinde çalışılan bug yok. Bu modüle kaynak ayrılması önerilir."
    ),
}


@pytest.mark.parametrize("key,sentence", sorted(BLIND_SPOT_SENTENCES_TR.items()))
def test_the_turkish_finding_templates_are_unchanged(key, sentence, catalogs):
    assert catalogs[i18n.SOURCE_LANGUAGE][key] == sentence


def test_templates_exposes_exactly_the_finding_namespace(catalogs):
    """ui/messages.py:TEMPLATES is derived, not written twice.

    tests/test_ui_messages.py has read this name since 5A and asserts it equals
    the set of codes the blind spot detector emits. Deriving it from the
    `finding.` prefix is what lets pattern findings get their own namespace
    without silently widening that assertion.
    """
    expected = {
        key[len("finding."):]: value
        for key, value in catalogs[i18n.SOURCE_LANGUAGE].items()
        if key.startswith("finding.")
    }
    assert TEMPLATES == expected


# =============================================================================
# Missing keys — one gap falls back, no gap at all raises
# =============================================================================

def test_a_key_missing_from_one_locale_falls_back_to_the_source(monkeypatch, caplog):
    """Built in memory, not by editing a shipped file.

    A user is free to hand-edit their own locale, and half a translation must
    leave a working page rather than a stack trace.
    """
    monkeypatch.setattr(
        i18n,
        "catalog",
        lambda language: {} if language == "en" else {"x.y": "kaynak metin"},
    )

    with caplog.at_level("WARNING"):
        assert i18n.translate("x.y", "en") == "kaynak metin"

    assert "x.y" in caplog.text


def test_a_key_missing_everywhere_raises(monkeypatch):
    monkeypatch.setattr(i18n, "catalog", lambda language: {})

    with pytest.raises(i18n.UnknownMessageKey):
        i18n.translate("no.such.key", "en")

    with pytest.raises(i18n.UnknownMessageKey):
        i18n.translate("no.such.key", i18n.SOURCE_LANGUAGE)


def test_a_missing_param_raises_rather_than_rendering_a_gap(monkeypatch):
    monkeypatch.setattr(i18n, "catalog", lambda language: {"x.y": "{a} and {b}"})

    with pytest.raises(KeyError):
        i18n.translate("x.y", i18n.SOURCE_LANGUAGE, a=1)


def test_a_message_with_no_params_is_not_formatted(monkeypatch):
    """Nothing to interpolate means nothing to escape.

    Without this branch a translator would have to double every literal brace
    for a reason invisible in their file.
    """
    monkeypatch.setattr(i18n, "catalog", lambda language: {"x.y": "100% {literal}"})

    assert i18n.translate("x.y", i18n.SOURCE_LANGUAGE) == "100% {literal}"


# =============================================================================
# The active language
# =============================================================================

def test_set_language_rejects_what_it_cannot_render(caplog):
    previous = i18n.get_language()
    try:
        with caplog.at_level("WARNING"):
            assert i18n.set_language("de") == i18n.SOURCE_LANGUAGE
        assert "de" in caplog.text
    finally:
        i18n.set_language(previous)


def test_t_renders_in_the_active_language():
    previous = i18n.get_language()
    try:
        i18n.set_language("en")
        english = i18n.t("finding.stale_bug", key="AP-1", days_open=40)
        i18n.set_language("tr")
        turkish = i18n.t("finding.stale_bug", key="AP-1", days_open=40)
    finally:
        i18n.set_language(previous)

    assert "AP-1" in english and "AP-1" in turkish
    assert english != turkish


# =============================================================================
# Risk levels: translated on screen, English everywhere else
# =============================================================================

def test_risk_level_colours_survive_translation():
    """The colour follows the level, never the words used for it.

    Faz 5C spells CRITICAL as "KRİTİK" in Turkish, which means the Plotly
    legend is keyed by translated text. The map for it has to be DERIVED from
    RISK_COLORS rather than rewritten per language — otherwise a level whose
    wording changed would silently fall through to Plotly's default palette and
    the chart would still render, just in the wrong colours.
    """
    previous = i18n.get_language()
    try:
        for language in i18n.LANGUAGES:
            i18n.set_language(language)
            colour_map = theme.risk_color_map()

            assert len(colour_map) == len(theme.RISK_COLORS), (
                f"{language}: two levels share a label, so one colour was lost"
            )
            for level, colour in theme.RISK_COLORS.items():
                label = theme.risk_level_label(level)
                assert colour_map[label] == colour, f"{language}: {level} lost its colour"
    finally:
        i18n.set_language(previous)


def test_turkish_spells_the_risk_levels_out():
    """The declared exception to "Turkish is preserved verbatim".

    Before 5C the interface printed CRITICAL/HIGH/MEDIUM/LOW raw while pattern
    severities on the same screen already read KRİTİK/YÜKSEK/ORTA/DÜŞÜK. This
    pins the decision that closed that inconsistency, and pins that the two
    vocabularies agree.
    """
    previous = i18n.get_language()
    try:
        i18n.set_language("tr")
        assert theme.risk_level_label("CRITICAL") == "KRİTİK"
        assert theme.risk_level_label("LOW") == "DÜŞÜK"
        assert [i18n.t(f"risk.level.{level.lower()}") for level in theme.RISK_COLORS] == [
            i18n.t(f"severity.{level.lower()}") for level in theme.RISK_COLORS
        ]

        i18n.set_language("en")
        assert theme.risk_level_label("CRITICAL") == "CRITICAL"
    finally:
        i18n.set_language(previous)


def test_an_unrecognised_level_is_passed_through():
    """Stored analysis results are outside data; an odd value must still render."""
    assert theme.risk_level_label("UNKNOWN") == "UNKNOWN"


# =============================================================================
# The source and the catalogs agree — both directions
# =============================================================================

#: t() called with a computed key. Each entry is a prefix whose whole namespace
#: is reachable that way, and the list is deliberately closed: a new dynamic
#: call site fails test_dynamic_t_calls_are_all_declared until it is added here
#: with a reason. Without that, one f-string would silently excuse every unused
#: key in the catalog from the "is it used?" check below.
DYNAMIC_PREFIXES = {
    "chart.status.": "ui/app.py — open/closed, from the status column",
    "severity.": "ui/pages/buglar.py — pattern severity, from the detector",
    "finding.": "ui/messages.py — blind spot codes, from the detector",
    "risk.level.": "ui/theme.py — risk level, from core/scoring.py",
}


def _ui_sources() -> list[Path]:
    return sorted(UI_DIR.rglob("*.py"))


def _collect_t_calls() -> tuple[set[str], list[str]]:
    """Every t() key in ui/, split into literal keys and dynamic call sites."""
    literal: set[str] = set()
    dynamic: list[str] = []

    for path in _ui_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name != "t":
                continue

            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                literal.add(first.value)
            else:
                dynamic.append(f"{path.name}:{node.lineno}")

    return literal, dynamic


def test_every_t_key_exists_in_every_locale(catalogs):
    """The failure this prevents: a key is renamed in one place and not the other.

    UnknownMessageKey would surface it, but only on the code path that renders
    that one message — which may be a branch no test walks. This sees all of
    them at parse time.
    """
    literal, _ = _collect_t_calls()

    missing = sorted(
        f"{language}:{key}"
        for language, catalog in catalogs.items()
        for key in literal
        if key not in catalog
    )
    assert not missing, f"t() calls with no message: {missing}"


def test_every_message_is_actually_used(catalogs):
    """The other direction: a key nothing renders is either dead or a typo.

    Both are worth knowing. A dead key costs a translator real work on a string
    no user will read, and a typo shows up here as the *old* key going unused
    while test_every_t_key_exists reports the new one missing.
    """
    literal, _ = _collect_t_calls()

    unused = sorted(
        key
        for key in catalogs[i18n.SOURCE_LANGUAGE]
        if key not in literal
        and not any(key.startswith(prefix) for prefix in DYNAMIC_PREFIXES)
    )
    assert not unused, f"messages nothing renders: {unused}"


def test_dynamic_t_calls_are_all_declared():
    """One call site per declared prefix, and no undeclared ones."""
    _, dynamic = _collect_t_calls()

    assert len(dynamic) == len(DYNAMIC_PREFIXES), (
        f"t() call sites with a computed key: {dynamic}. Every one needs an entry "
        f"in DYNAMIC_PREFIXES, otherwise it silently excuses unused messages."
    )


# =============================================================================
# No bare user-facing literal is left in ui/
# =============================================================================

#: Strings that reach a streamlit call but are not text a user reads. This list
#: IS the record of what was deliberately left alone; it is meant to shrink or
#: stay put, never to grow without a reason.
NOT_TRANSLATABLE = {
    # st.page_link targets — file paths, pinned separately by
    # test_nav_declares_all_four_pages in tests/test_dashboard_pages.py.
    "app.py", "pages/buglar.py", "pages/analiz.py", "pages/ayarlar.py",
    # Provider identifiers: values written to .env and compared against
    # config.LLM_PROVIDER, not labels.
    "groq", "openai",
    # Placeholders that are examples of a format, not sentences.
    "you@company.com", "AP", "gsk_...", "sk-...", "ATATT3x...",
}

_HTML_TAG = re.compile(r"<[^>]*>")
_HTML_ENTITY = re.compile(r"&[a-zA-Z]+;")

_RENDERERS = frozenset({
    "title", "header", "subheader", "markdown", "caption", "info", "warning",
    "error", "success", "metric", "text_input", "text_area", "multiselect",
    "selectbox", "radio", "button", "toggle", "number_input", "tabs", "expander",
    "dataframe", "code", "progress", "spinner", "write", "text", "checkbox",
    "slider", "download_button", "page_link", "link_button", "toast",
})

#: Keyword arguments that carry text a user reads.
_VISIBLE_KW = frozenset({"label", "help", "placeholder", "text", "body", "caption"})

#: Keyword arguments that never do — values, flags, geometry, widget keys.
_INVISIBLE_KW = frozenset({
    "key", "language", "type", "index", "value", "use_container_width",
    "hide_index", "horizontal", "label_visibility", "min_value", "max_value",
    "step", "default", "options", "column_config", "unsafe_allow_html",
    "on_change", "format_func",
})


def _strings_in(node: ast.AST):
    """Every string literal reachable from an argument expression.

    f-strings collapse to their constant parts with {} where a value goes, so
    "**{name}** — {n} bug" is judged on "**{}** — {} bug".
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        yield node.value
    elif isinstance(node, ast.JoinedStr):
        yield "".join(p.value if isinstance(p, ast.Constant) else "{}" for p in node.values)
    elif isinstance(node, ast.List | ast.Tuple):
        for element in node.elts:
            yield from _strings_in(element)
    elif isinstance(node, ast.BinOp):
        for side in (node.left, node.right):
            yield from _strings_in(side)
    elif isinstance(node, ast.IfExp):
        for side in (node.body, node.orelse):
            yield from _strings_in(side)


def _is_prose(text: str) -> bool:
    """True if anything is left to read once markup and values are removed."""
    stripped = _HTML_ENTITY.sub("", _HTML_TAG.sub("", text)).replace("{}", "")
    return any(character.isalpha() for character in stripped)


def _on_logger(call: ast.Call) -> bool:
    """logger.info/warning/error share names with st.* but are not user-facing."""
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "logger"
    )


def test_no_bare_user_facing_literal_survives_in_ui():
    """Every sentence the user reads goes through t(), or is listed above.

    This is the mechanised form of the Faz 5C measurement — 227 call sites
    across eight files — and its real job is the next change rather than this
    one: adding st.subheader("Yeni Bölüm") to a page would ship a string no
    locale can reach, and nothing else in the suite would notice.
    """
    offenders = []

    for path in _ui_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _on_logger(node):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name not in _RENDERERS:
                continue

            values = [text for arg in node.args for text in _strings_in(arg)]
            for keyword in node.keywords:
                if keyword.arg in _INVISIBLE_KW:
                    continue
                if keyword.arg in _VISIBLE_KW or keyword.arg is None:
                    values += list(_strings_in(keyword.value))

            for text in values:
                if text in NOT_TRANSLATABLE or text.strip().startswith(("<style", "http")):
                    continue
                if not _is_prose(text):
                    continue
                offenders.append(f"{path.name}:{node.lineno} st.{name}({text[:60]!r})")

    assert not offenders, "untranslated literals: " + "; ".join(offenders)
