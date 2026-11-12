"""
What component_classifier decides, and the defects 6E-2 PR4 fixed (Faz 6E-2).

`classify_bugs` fills in `component` when Jira left it empty or "Unknown", and
`core/scoring.py` groups every bug by that field — so a wrong guess moves a bug
into another module's risk score. Until 6E-2b the module had no test of its
own: one test in test_analysis_service_indexing.py checked one input. The 6E
discovery's coverage run showed 94% line coverage anyway, all of it indirect —
coverage is not verification.

HOW IT DECIDES (read from the code). Text and keywords are lower-cased with
every form of i (İ, I, ı, i) folded to "i". A keyword matches as a whole word,
optionally followed by one Turkish inflection chain (plural, possessive, case,
"-ki") or an English -s/-es/-d/-ed/-ing — never inside another word. A match
lying inside a longer match of another component does not count, and a
keyword spelled two ways ("kayıt", "kayit") counts once. Each match scores one
point; the highest score wins, and on a tie the component listed first in
COMPONENT_KEYWORDS wins. No match, or no text, is "Genel".

THE NINE DEFECTS 6E-2b PINNED as xfail(strict=True) — capital Turkish İ, word
fragments ("Author" read as "auth") and keywords containing another
component's keyword ("performans" contains "form") — were fixed in 6E-2 PR4
and are plain tests now. The guards at the end of the file were written before
that fix and were green on the old rule too: what was right must stay right.
The new rule's known limits: KNOWN-DEBT.md, 'component_classifier kusurları'.

VERB STEMS (6E-2 PR4b). The word rule cannot reach a verb made from a keyword
("yavaşlıyor" from "yavaş"); VERB_STEMS adds narrow word-start prefixes for
those, used only in words no keyword matched. Their tests are at the end.
"""

import pytest

import defect_risk_analyzer.component_classifier as cc
from defect_risk_analyzer.component_classifier import (
    COMPONENT_KEYWORDS,
    classify_bugs,
    classify_component,
)


def classify(summary: str, description: str = "") -> str:
    return classify_component({"summary": summary, "description": description})


# --- every keyword, alone, lands in its own component -----------------------

# Keywords that contain a shorter keyword of another component listed earlier.
# Under the old substring rule each was a 1–1 tie that dictionary order
# resolved the wrong way (6E-2b, xfail); they keep a test of their own.
SUBSTRING_COLLISIONS = {
    # "form" (Frontend) is inside both words, but not as a word of its own.
    "performans": "Performance",
    "performance": "Performance",
    # "şifre"/"sifre" (Authentication) + "leme" is not an inflection.
    "şifreleme": "Security",
    "sifreleme": "Security",
}


# Keyword counts per component, measured 2026-11-11 (218 in all, no keyword in
# two components), then 224 after 6E-2 PR4 added six word forms (Authentication
# +2, Reporting +1, Performance +3; each measured alone first). The loop below
# reads the keywords from the module itself, so without this a deleted keyword
# would simply drop out of the loop and nothing would notice. Changing a list is
# a behaviour change: update this alongside it.
KEYWORD_COUNTS = {
    "Authentication": 30,
    "Payment": 28,
    "Frontend": 42,
    "Backend API": 22,
    "Database": 17,
    "Reporting": 21,
    "Notifications": 15,
    "Inventory": 14,
    "Performance": 19,
    "Security": 16,
}


@pytest.mark.parametrize("component", list(KEYWORD_COUNTS))
def test_every_keyword_classifies_to_its_component(component):
    """Each keyword of a component, as the whole summary, classifies to that
    component — every one of them, the four collisions included — and the
    component still has the number of keywords it was measured with. The
    component list and its ORDER are pinned too: order decides every tie."""
    assert list(COMPONENT_KEYWORDS) == list(KEYWORD_COUNTS)
    assert len(COMPONENT_KEYWORDS[component]) == KEYWORD_COUNTS[component]
    wrong = {
        keyword: classify(keyword)
        for keyword in COMPONENT_KEYWORDS[component]
        if classify(keyword) != component
    }
    assert wrong == {}


@pytest.mark.parametrize(("keyword", "expected"), sorted(SUBSTRING_COLLISIONS.items()))
def test_a_keyword_containing_another_components_keyword(keyword, expected):
    assert classify(keyword) == expected


# --- the 6E discovery's defects, fixed in 6E-2 PR4 -------------------------------

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
def test_a_word_fragment_is_not_a_keyword(summary, expected):
    assert classify(summary) == expected


TURKISH_UPPERCASE = [
    # "giriş" is an Authentication keyword. str.lower() turns "İ" into "i" +
    # U+0307 (combining dot above), so "GİRİŞ".lower() was not "giriş".
    ("GİRİŞ YAPILAMIYOR", "Authentication"),
    # "şifre" is an Authentication keyword; same cause.
    ("ŞİFRE sıfırlanamıyor", "Authentication"),
]


@pytest.mark.parametrize(("summary", "expected"), TURKISH_UPPERCASE)
def test_turkish_uppercase_is_recognised(summary, expected):
    assert classify(summary) == expected


# Capitals with suffixes, as a Turkish keyboard types them (i → İ, ı → I). All
# were "Genel" or wrong under str.lower(). The last two have a dotless capital
# I as well: "ÇIKIŞ".lower() is "çikiş", which matched neither "çıkış" nor
# "cikis"; "İADE" became "i" + U+0307 + "ade".
TURKISH_CAPITALS_WITH_SUFFIXES = [
    ("ŞİFREMİ UNUTTUM BAĞLANTISI ÇALIŞMIYOR", "Authentication"),
    ("GİRİŞTE HATA ALIYORUM", "Authentication"),
    ("MOBİLDE DÜZEN KAYIYOR", "Frontend"),
    ("SERVİSE İSTEK ATINCA ZAMAN AŞIMI", "Backend API"),
    ("VERİTABANINA BAĞLANAMIYOR", "Database"),
    ("GRAFİKTE EKSEN ETİKETLERİ KAYIYOR", "Reporting"),
    ("BİLDİRİMLER GELMİYOR", "Notifications"),
    ("GÜVENLİKTE AÇIK BULUNDU", "Security"),
    ("ÇIKIŞ YAPILAMIYOR", "Authentication"),
    ("İADE YAPILMADI", "Payment"),
]


@pytest.mark.parametrize(("summary", "expected"), TURKISH_CAPITALS_WITH_SUFFIXES)
def test_turkish_capitals_with_suffixes_are_recognised(summary, expected):
    assert classify(summary) == expected


# A keyword at the start of a Turkish word that is NOT that keyword plus an
# inflection: a derivational suffix or just another word. Each was filed under
# the keyword's component by the old substring rule; nothing else matches.
TURKISH_WORDS_STARTING_WITH_A_KEYWORD = [
    ("Parametre listesi yanlış", "Genel"),  # para (Payment)
    ("Veriler tutarsız görünüyor", "Genel"),  # tutar (Payment) + -sız
    ("Depolama alanı doldu", "Genel"),  # depo (Inventory) + -lama: storage
    ("Formatı bozuk tarih", "Genel"),  # form (Frontend)
    ("Restoran listesi boş", "Genel"),  # rest (Backend API)
]


@pytest.mark.parametrize(("summary", "expected"), TURKISH_WORDS_STARTING_WITH_A_KEYWORD)
def test_a_turkish_word_starting_with_a_keyword_is_not_that_keyword(summary, expected):
    assert classify(summary) == expected


ENGLISH_WORD_FRAGMENTS = [
    ("Restore from backup fails", "Genel"),  # rest
    ("Paragraph spacing broken", "Genel"),  # para
    ("Reporter field is empty", "Genel"),  # report; Reporter is a Jira field
    ("Date format is wrong", "Genel"),  # form
    # rest (Backend API) inside "restart" tied 1–1 with database, and Backend
    # API is listed first.
    ("Database restart required", "Database"),
]


@pytest.mark.parametrize(("summary", "expected"), ENGLISH_WORD_FRAGMENTS)
def test_an_english_word_fragment_is_not_a_keyword(summary, expected):
    assert classify(summary) == expected


def test_a_suffixed_keyword_containing_another_components_keyword():
    """"şifreleme" + "de": Security's keyword with a case suffix. The old rule
    also counted Authentication's "şifre" inside it — a 1–1 tie it lost."""
    assert classify("Şifrelemede eski algoritma kullanılıyor") == "Security"


def test_a_match_inside_a_longer_match_of_another_component_does_not_count():
    """"sql" (Database) lies inside "sql injection" (Security). Counted on its
    own it makes Database 2 (sql, query) against Security 2 (sql injection,
    injection), and Database, listed first, wins. Dropped, Security wins."""
    assert classify("SQL injection in search query") == "Security"


def test_a_keyword_spelled_two_ways_counts_once():
    """"kayıt" and "kayit" both normalize to "kayit". Counted twice, Database
    would beat Authentication 2–1; once, it is a 1–1 tie that Authentication,
    listed first, wins — as it did before normalization existed."""
    assert classify("kayıt login") == "Authentication"


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


# Word forms the inflection rule cannot reach from an existing keyword, added as
# keywords of their own in 6E-2 PR4 (user decision S2(b)). The old substring
# rule found them inside them ("filtre" in "filtreleme", "auth" in
# "authorization", "slow" in "slower"); the word rule accepts only inflections,
# not derivations, so without these each title below is "Genel". Each word was
# measured alone before it went in: no corpus input it changed became wrong.
DERIVED_FORMS = [
    ("Filtreleme sonrası liste boş", "Reporting"),  # filtreleme
    ("Uygulama çok yavaşladı", "Performance"),  # yavaşladı
    ("Uygulama cok yavasladi", "Performance"),  # yavasladi
    ("Authorization fails for admin users", "Authentication"),  # authorization
    ("User cannot authenticate", "Authentication"),  # authenticate
    ("Slower after update", "Performance"),  # slower
]


@pytest.mark.parametrize(("summary", "expected"), DERIVED_FORMS)
def test_a_derived_form_added_as_a_keyword_classifies(summary, expected):
    assert classify(summary) == expected


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
    English all classify (upper-case Turkish has its own tests above)."""
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


# --- verb stems (6E-2 PR4b) ----------------------------------------------------------
#
# The word rule accepts inflections only, so a verb made from a keyword
# ("yavaşla-" from "yavaş") is "Genel" under it. The old substring rule found
# the keyword inside the verb: "Uygulama yavaşlıyor" and "Liste filtrelenmiyor"
# were right before 6E-2 PR4 and "Genel" after it (measured). VERB_STEMS fixes
# that with narrow word-start prefixes, each measured alone first: it rescued
# at least one input the old rule got right, and changed nothing else on the
# discovery corpora or the full suite (user decision, 2026-11-11).

# The table, pinned. A stem is a prefix, so every one is a deliberate, measured
# choice; adding, widening or dropping one is a behaviour change — measure it,
# then update this.
VERB_STEMS_MEASURED = {
    "Authentication": ["authoriz"],
    "Payment": ["faturala"],
    "Frontend": ["sayfala"],
    "Reporting": ["filtrele", "filtreliyor", "raporla", "raporluyor"],
    "Notifications": ["mesajlaş", "mesajlas", "uyarıl"],
    "Inventory": ["stokla", "transferre", "transferring"],
    "Performance": ["yavaşl", "yavasl", "önbellekl", "onbellekl"],
}


def test_verb_stems_are_the_measured_ones():
    assert cc.VERB_STEMS == VERB_STEMS_MEASURED


@pytest.mark.parametrize("component", list(VERB_STEMS_MEASURED))
def test_every_verb_stem_classifies_to_its_component(component):
    """Each stem, as the whole summary, is a word that starts with itself."""
    wrong = {
        stem: classify(stem)
        for stem in cc.VERB_STEMS[component]
        if classify(stem) != component
    }
    assert wrong == {}


# One verb form per stem; each was "Genel" before VERB_STEMS.
VERB_FORMS = [
    ("User is not authorized", "Authentication"),  # authoriz
    ("Siparişler faturalanmadı", "Payment"),  # faturala
    ("Sonuçlar sayfalanmıyor", "Frontend"),  # sayfala
    ("Liste filtrelenmiyor", "Reporting"),  # filtrele
    ("LİSTE FİLTRELENMİYOR", "Reporting"),  # filtrele, Turkish capitals
    ("Arama sonuçları yanlış filtreliyor", "Reporting"),  # filtreliyor
    ("Satışlar raporlanmıyor", "Reporting"),  # raporla
    ("Aylık satışları raporluyor ama toplam yanlış", "Reporting"),  # raporluyor
    ("Mesajlaşma ekranı donuyor", "Notifications"),  # mesajlaş
    ("Kullanicilar mesajlasamiyor", "Notifications"),  # mesajlas
    ("Kullanıcı uyarılmadı", "Notifications"),  # uyarıl (ı folds: also "uyarilmadi")
    ("Stoklama yapılamıyor", "Inventory"),  # stokla
    ("Items transferred twice", "Inventory"),  # transferre
    ("Transferring goods hangs", "Inventory"),  # transferring
    ("Uygulama yavaşlıyor", "Performance"),  # yavaşl
    ("Sistem yavaslamis", "Performance"),  # yavasl
    ("Sonuçlar önbelleklenmiyor", "Performance"),  # önbellekl
    ("Onbellekleme kapali kaliyor", "Performance"),  # onbellekl
]


@pytest.mark.parametrize(("summary", "expected"), VERB_FORMS)
def test_a_verb_made_from_a_keyword_classifies(summary, expected):
    assert classify(summary) == expected


# Words that share the start of a stem — or would, were the stem one letter
# shorter — and are not that verb. Each is today's answer, and a wider or
# unanchored stem would change it.
VERB_STEM_TRAPS = [
    ("Animasyon yavaşça kayboluyor", "Genel"),  # yavaş+ça, an adverb: the stem is "yavaşl"
    ("Mikrofiltreleme ünitesi arızalı", "Genel"),  # a stem starts a word, never inside one
    ("Filtreli kahve makinesi siparişi", "Genel"),  # filtre+li, an adjective: not "filtrel"
    ("Raporlu personel listesi açılmıyor", "Genel"),  # raporlu = on sick leave: not "raporl"
    ("Faturalı hatlarda arama kesiliyor", "Genel"),  # faturalı hat = postpaid line
    ("Sayfalık rapor eksik çıkıyor", "Reporting"),  # sayfa+lık: not "sayfal"
    ("Uyarıcı ilaç listesi eksik", "Genel"),  # uyarıcı = stimulant: not "uyarı"
    ("Authority certificate expired", "Security"),  # authority: not "author"
    ("Authorship field is empty", "Genel"),
    ("Transferrin value missing in lab results", "Genel"),  # a protein: not "transferr"
]


@pytest.mark.parametrize(("summary", "expected"), VERB_STEM_TRAPS)
def test_a_word_sharing_a_stems_start_is_not_that_verb(summary, expected):
    assert classify(summary) == expected


def test_a_word_a_keyword_matched_is_not_counted_again_by_a_stem():
    """"raporlarda" is "rapor" + inflection — a keyword match — and also starts
    with the stem "raporla". Counted once, Reporting 1 ties Payment 1 (ödeme)
    and Payment, listed first, wins. Counted twice, Reporting would win 2–1."""
    assert classify("Ödeme raporlarda eksik") == "Payment"


def test_a_stem_of_a_component_without_keywords_is_ignored(monkeypatch):
    """Stems are walked in COMPONENT_KEYWORDS order, so a stem filed under a
    component that has no keywords scores nothing — rather than a score the
    tie-break never sees, which would leave max() an empty sequence."""
    monkeypatch.setitem(cc.VERB_STEMS, "Nowhere", ["zzyzx"])
    assert classify("zzyzxing fails") == "Genel"
