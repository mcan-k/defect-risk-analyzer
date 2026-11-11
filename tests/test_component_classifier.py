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


# --- guards: what is right today must stay right (6E-2 PR4) -----------------------
#
# Written BEFORE the matching rule changed, and green on the old rule too. The
# old rule matched a long keyword anywhere inside a word, which happens to
# accept Turkish suffixes ("ödemede" contains "ödeme") and English inflections
# ("payments" contains "payment"). A stricter rule that fixes the word-fragment
# defects must not lose these. In every case the suffixed keyword is the only
# thing to classify by — measured: with whole-word matching each one is "Genel"
# (6E-2 PR4 discovery, candidate C).

SUFFIXED_TURKISH = [
    ("Girişte hata alıyorum", "Authentication"),
    ("Loginde takılıyor", "Authentication"),
    ("Ödemede takılıyor", "Payment"),
    ("Faturalar yanlış tutarla kesiliyor", "Payment"),
    ("Sepete eklenmiyor", "Frontend"),
    ("Formda alanlar kayıyor", "Frontend"),
    ("Servise istek atınca zaman aşımı", "Backend API"),
    ("Servislerde bağlantı kopuyor", "Backend API"),
    ("Veritabanına bağlanamıyor", "Database"),
    ("Kayıtlar iki kez ekleniyor", "Database"),
    ("Raporda toplamlar yanlış", "Reporting"),
    ("Grafikte eksen etiketleri kayıyor", "Reporting"),
    ("Bildirimler gelmiyor", "Notifications"),
    ("Mesajlarda Türkçe karakter bozuk", "Notifications"),
    ("Stoklar eksi değere düşüyor", "Inventory"),
    ("Ürünlerin miktarı güncellenmiyor", "Inventory"),
    ("Önbellekteki veri bayat kalıyor", "Performance"),
    ("Bellekte sızıntı var", "Performance"),
    ("Güvenlikte açık bulundu", "Security"),
    ("Sertifikası süresi dolmuş", "Security"),
]


@pytest.mark.parametrize(("summary", "expected"), SUFFIXED_TURKISH)
def test_a_keyword_with_a_turkish_suffix_still_classifies(summary, expected):
    assert classify(summary) == expected


# The same titles as typed without Turkish letters and in capitals ("ş" → "S").
ASCII_UPPERCASE_TURKISH = [
    ("SIFREMI UNUTTUM BAGLANTISI CALISMIYOR", "Authentication"),
    ("ODEMEDE TAKILIYOR", "Payment"),
    ("MENUDE ALT BASLIKLAR GORUNMUYOR", "Frontend"),
    ("SERVISE ISTEK ATINCA ZAMAN ASIMI", "Backend API"),
    ("TABLODA EKSIK SUTUN VAR", "Database"),
    ("ISTATISTIKLERDE GECEN AY EKSIK", "Reporting"),
    ("UYARILAR IKI KEZ GOSTERILIYOR", "Notifications"),
    ("STOKLAR EKSI DEGERE DUSUYOR", "Inventory"),
    ("BELLEKTE SIZINTI VAR", "Performance"),
    ("ZAFIYETLER KAPATILMADI", "Security"),
]


@pytest.mark.parametrize(("summary", "expected"), ASCII_UPPERCASE_TURKISH)
def test_ascii_uppercase_turkish_still_classifies(summary, expected):
    assert classify(summary) == expected


ENGLISH_INFLECTIONS = [
    ("Payments are processed twice", "Payment"),
    ("Order refunded twice", "Payment"),
    ("Tokens expire too early", "Authentication"),
    ("Cached results are stale", "Performance"),
]


@pytest.mark.parametrize(("summary", "expected"), ENGLISH_INFLECTIONS)
def test_english_inflections_still_classify(summary, expected):
    assert classify(summary) == expected


def test_a_short_keyword_is_not_a_prefix():
    """"hiz" (Performance, the ASCII spelling of "hız") begins "Hizmet"
    (service). Today a keyword of three characters or fewer must be a whole
    word; a rule that matched keywords as prefixes would file this under
    Performance."""
    assert classify("Hizmet dışı kaldı") == "Genel"


# The sample data's own labels as the answer key: summary and description of
# every record, classified, against its `component`. One record is wrong today
# and pinned as such: AP-501 in the English file scores Database 3 (database,
# race condition, transaction) and Inventory 3 (stock twice, quantity), and the
# tie goes to Database, listed first. Its Turkish twin scores Inventory higher
# (stok, miktar, ürün) and is right. A change to this dict is a change in what
# the classifier says about real-looking bugs — read the diff before updating it.
@pytest.mark.parametrize(
    ("file_name", "mismatches"),
    [
        ("sample_bugs.json", {}),
        ("sample_bugs_en.json", {"AP-501": "Database"}),
    ],
)
def test_sample_data_classifies_as_labelled(file_name, mismatches):
    # Imported here so this guard section stays one block at the end of the file.
    import json
    from pathlib import Path

    data = Path(__file__).resolve().parents[1] / "data"
    bugs = json.loads((data / file_name).read_text(encoding="utf-8"))
    assert len(bugs) == 20
    got = {
        bug["key"]: classify_component(bug)
        for bug in bugs
        if classify_component(bug) != bug["component"]
    }
    assert got == mismatches
