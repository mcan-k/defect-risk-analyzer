"""
What component_classifier decides today, and where it is known to be wrong (Faz 6E-2b).

`classify_bugs` fills in `component` when Jira left it empty or "Unknown", and
`core/scoring.py` groups every bug by that field — so a wrong guess moves a bug
into another module's risk score. Until this file the module had no test of its
own: one test in test_analysis_service_indexing.py checked one input. The 6E
discovery's coverage run showed 94% line coverage anyway, all of it indirect —
coverage is not verification.

HOW IT DECIDES (read from the code, not the docstring). Each component scores
one point per keyword occurrence: keywords of three characters or fewer must
match a whole word (`\\b…\\b`), longer ones match anywhere as a substring. The
highest score wins; on a tie `max()` returns the component listed first in
COMPONENT_KEYWORDS. No match, or no text, is "Genel". The module docstring
says "first match wins" — that is not what the code does (KNOWN-DEBT, the
component_classifier section); the docstring is left for the fix PR.

KNOWN DEFECTS ARE xfail(strict=True), each naming its KNOWN-DEBT row. The
expected value in every xfail is the CORRECT component, derived from the
keyword lists and argued in the case's comment — so when the fix lands, the
case XPASSes and strict turns that into a red that forces the marker off.
Measured before writing (6E-2a, 2026-11-11): 4 of the 218 keywords, given
alone, land in another component.
"""

import pytest

from defect_risk_analyzer.component_classifier import (
    COMPONENT_KEYWORDS,
    classify_bugs,
    classify_component,
)

KNOWN_DEBT = "KNOWN-DEBT.md, 'component_classifier kusurları'"


def classify(summary: str, description: str = "") -> str:
    return classify_component({"summary": summary, "description": description})


# --- every keyword, alone, lands in its own component -----------------------

# Keywords that do NOT, because a longer keyword of theirs contains a shorter
# keyword of another component listed earlier — a tie that dictionary order
# resolves the wrong way. Each is pinned as an xfail below.
SUBSTRING_COLLISIONS = {
    # "form" (Frontend) is inside both words; 1–1 tie, Frontend is listed first.
    "performans": "Performance",
    "performance": "Performance",
    # "şifre"/"sifre" (Authentication) is inside both words; 1–1 tie.
    "şifreleme": "Security",
    "sifreleme": "Security",
}


# Keyword counts per component, measured 2026-11-11 (218 in all, no keyword in
# two components). The loop below reads the keywords from the module itself, so
# without this a deleted keyword would simply drop out of the loop and nothing
# would notice. Changing a list is a behaviour change: update this alongside it.
KEYWORD_COUNTS = {
    "Authentication": 28,
    "Payment": 28,
    "Frontend": 42,
    "Backend API": 22,
    "Database": 17,
    "Reporting": 20,
    "Notifications": 15,
    "Inventory": 14,
    "Performance": 16,
    "Security": 16,
}


@pytest.mark.parametrize("component", list(KEYWORD_COUNTS))
def test_every_keyword_classifies_to_its_component(component):
    """Each keyword of a component, as the whole summary, classifies to that
    component — the known collisions excepted, which have their own xfails —
    and the component still has the number of keywords it was measured with.
    The component list and its ORDER are pinned too: order decides every tie."""
    assert list(COMPONENT_KEYWORDS) == list(KEYWORD_COUNTS)
    assert len(COMPONENT_KEYWORDS[component]) == KEYWORD_COUNTS[component]
    wrong = {
        keyword: classify(keyword)
        for keyword in COMPONENT_KEYWORDS[component]
        if keyword not in SUBSTRING_COLLISIONS and classify(keyword) != component
    }
    assert wrong == {}


@pytest.mark.parametrize(("keyword", "expected"), sorted(SUBSTRING_COLLISIONS.items()))
@pytest.mark.xfail(strict=True, reason=f"Bilinen kusur: kelime parçası eşleşmesi ({KNOWN_DEBT})")
def test_a_keyword_containing_another_components_keyword(keyword, expected):
    assert classify(keyword) == expected


# --- known defects, from the 6E discovery --------------------------------------

WORD_FRAGMENTS = [
    # "auth" (Authentication) is inside "Author"; no word in the sentence is a
    # keyword of any component, so the right answer is "Genel".
    ("Author field shows wrong text", "Genel"),
    # "para" (Payment) is inside "Parameter"; nothing else matches.
    ("Parameter list is wrong", "Genel"),
    # "rest" (Backend API) is inside "Restart"; nothing else matches.
    ("Restart required after update", "Genel"),
]


@pytest.mark.parametrize(("summary", "expected"), WORD_FRAGMENTS)
@pytest.mark.xfail(strict=True, reason=f"Bilinen kusur: kelime parçası eşleşmesi ({KNOWN_DEBT})")
def test_a_word_fragment_is_not_a_keyword(summary, expected):
    assert classify(summary) == expected


TURKISH_UPPERCASE = [
    # "giriş" is an Authentication keyword. str.lower() turns "İ" into "i" +
    # U+0307 (combining dot above), so "GİRİŞ".lower() is not "giriş".
    ("GİRİŞ YAPILAMIYOR", "Authentication"),
    # "şifre" is an Authentication keyword; same cause.
    ("ŞİFRE sıfırlanamıyor", "Authentication"),
]


@pytest.mark.parametrize(("summary", "expected"), TURKISH_UPPERCASE)
@pytest.mark.xfail(strict=True, reason=f"Bilinen kusur: büyük harfli Türkçe İ ({KNOWN_DEBT})")
def test_turkish_uppercase_is_recognised(summary, expected):
    assert classify(summary) == expected


# --- the decision rule ----------------------------------------------------------


@pytest.mark.parametrize(
    "bug",
    [{}, {"summary": "", "description": ""}, {"summary": "   ", "description": "\n"}],
    ids=["no-fields", "empty", "whitespace"],
)
def test_no_text_is_genel(bug):
    """`if not text.strip(): return "Genel"`."""
    assert classify_component(bug) == "Genel"


def test_no_keyword_is_genel():
    """Text with no keyword of any component: `if not scores: return "Genel"`."""
    assert classify("Uygulama beklenmedik şekilde kapandı") == "Genel"


def test_highest_score_wins_over_first_match():
    """Authentication scores 1 (login), Payment 3 (payment ×2, refund). The higher
    score wins even though Authentication is listed first and matches first."""
    assert classify("login then payment payment refund") == "Payment"


@pytest.mark.parametrize("summary", ["login payment", "payment login"])
def test_a_tie_goes_to_the_component_listed_first(summary):
    """1–1 tie: `max()` keeps the first maximum in COMPONENT_KEYWORDS order, so
    Authentication (listed before Payment) wins, whatever the word order."""
    assert classify(summary) == "Authentication"


def test_short_keywords_need_a_whole_word():
    """"ui" (Frontend, two characters) is matched only as a word: inside "Build"
    and "guide" it does not count, and nothing else matches."""
    assert classify("Build guide") == "Genel"


def test_summary_and_description_are_read_together():
    """The text is f"{summary} {description}": a keyword only in the description
    still counts, and counts add up across both fields."""
    assert classify("Ekran donuyor", "veritabanı deadlock") == "Database"
    assert classify("login", "invoice invoice") == "Payment"


@pytest.mark.parametrize(
    ("summary", "expected"),
    [
        ("giriş yapılamıyor", "Authentication"),
        ("giris yapilamiyor", "Authentication"),
        ("Login fails after update", "Authentication"),
        ("PAYMENT DECLINED AT CHECKOUT", "Payment"),
    ],
    ids=["tr", "tr-ascii", "en", "en-uppercase"],
)
def test_turkish_and_english_inputs(summary, expected):
    """Lower-case Turkish, its ASCII spelling, English, and upper-case ASCII
    English all classify (upper-case Turkish does not — see the xfail above)."""
    assert classify(summary) == expected


# --- classify_bugs ----------------------------------------------------------------


@pytest.mark.parametrize(
    "component",
    ["", "Unknown", "   ", None],
    ids=["empty", "Unknown", "whitespace", "missing"],
)
def test_classify_bugs_fills_an_unassigned_component(component):
    """Empty, "Unknown", whitespace and a missing key are all replaced."""
    bug = {"key": "AP-1", "summary": "login hatası"}
    if component is not None:
        bug["component"] = component
    classify_bugs([bug])
    assert bug["component"] == "Authentication"


def test_classify_bugs_keeps_an_assigned_component():
    """A component Jira already set is never overwritten, even when the text
    would classify elsewhere."""
    bug = {"key": "AP-2", "summary": "login hatası", "component": "Reporting"}
    classify_bugs([bug])
    assert bug["component"] == "Reporting"


def test_classify_bugs_works_in_place_and_returns_the_same_list():
    """The list is modified in place and returned as the same object."""
    bugs = [{"key": "AP-3", "summary": "stok sayımı yanlış", "component": ""}]
    assert classify_bugs(bugs) is bugs
    assert bugs[0]["component"] == "Inventory"
