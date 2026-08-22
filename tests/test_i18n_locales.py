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

import json

import pytest

from defect_risk_analyzer.ui import i18n
from defect_risk_analyzer.ui.messages import TEMPLATES


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
        "edilmemiş. Canlı Analiz sayfasından analiz yapın."
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
