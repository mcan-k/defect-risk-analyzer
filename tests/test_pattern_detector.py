"""What detect_patterns returns, pinned before Faz 5C converts it.

Written FIRST, deliberately, and this is the same sequencing Faz 5A used on
blind_spot_detector: the sentence the detector built was asserted here as a
literal, so the commit that moved that wording into locales/tr.json could be
read as a move rather than believed to be one. That commit took the literals
out of this file — the diff shows tests/test_i18n_locales.py and tr.json
gaining exactly what this file and pattern_detector.py lost.

What is left here is structure: codes, params, keys, counts, severity. The
wording is the presentation layer's problem and is asserted where the renderer
lives, which is the same division 5A settled on.

ChromaDB is never involved. detect_patterns takes the collection as an
argument, so a stub that answers count() and query() is enough — which is also
why the API-level contract test can build a full payload without a database.

TIES ARE BROKEN BY A RULE, NOT BY HASH ORDER (6D-6b). Until then the cluster
was iterated as a set, _extract_common_keywords counted over `set(words)`, and
Counter.most_common broke ties by insertion order — so equally common keywords,
and a tied module or priority, came out differently in every process (measured:
six runs, six orders; the 6D-6b browser check saw one pattern's module move
between Frontend, Inventory and Reporting across restarts). The user reads all
of it on the Buglar page: the module in the header and the "Olası Ortak Neden"
sentence, which names keywords[0] and keywords[1]. Now a count ties to code
point order, and a priority tie to the more severe priority. The tie tests at
the end pin that; one runs in eight interpreters with fixed hash seeds, because
in-process the seed is whatever this run drew and the old code could pass by
luck. The exact-sentence pin still uses a cluster with ONE common keyword.
"""

import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

# Module level imports only names the code had before 6D-6b. A name added
# later is imported inside the test that needs it: one missing name must fail
# that test, not stop the whole file from being collected.
from defect_risk_analyzer.pattern_detector import _extract_common_keywords, detect_patterns

REPO_ROOT = Path(__file__).resolve().parents[1]


class StubCollection:
    """Answers every query with every bug, at a similarity above the threshold.

    Clustering is not what these tests are about; the shape of a pattern is.
    Returning everything makes the cluster deterministic and keeps the fixtures
    readable.
    """

    def __init__(self, bugs: list[dict]) -> None:
        self._bugs = bugs

    def count(self) -> int:
        return len(self._bugs)

    def query(self, query_texts, n_results, include):
        metadatas = [{"key": bug["key"]} for bug in self._bugs][:n_results]
        # Cosine distance 0.1 → similarity 0.95, comfortably over the 0.70 default.
        return {"metadatas": [metadatas], "distances": [[0.1] * len(metadatas)]}


def _cluster(bugs: list[dict]) -> dict:
    """The single pattern these fixtures are built to produce."""
    patterns = detect_patterns(bugs, StubCollection(bugs))
    assert len(patterns) == 1, f"fixture produced {len(patterns)} patterns, expected 1"
    return patterns[0]


@pytest.fixture
def one_keyword() -> dict:
    """Three bugs sharing exactly one word, so the sentence has no tie to break.

    "timeout" appears in all three; alfa/beta/gama appear once each and the
    detector keeps only words seen in two or more bugs.
    """
    return _cluster([
        {"key": "AP-1", "summary": "timeout", "description": "alfa",
         "component": "Payment", "priority": "High", "status": "Open"},
        {"key": "AP-2", "summary": "timeout", "description": "beta",
         "component": "Payment", "priority": "High", "status": "Open"},
        {"key": "AP-3", "summary": "timeout", "description": "gama",
         "component": "Payment", "priority": "Highest", "status": "Open"},
    ])


@pytest.fixture
def no_keywords() -> dict:
    """Two bugs with nothing in common, which is the other wording branch."""
    return _cluster([
        {"key": "BP-1", "summary": "Kırmızı", "description": "",
         "component": "Frontend", "priority": "Low", "status": "Open"},
        {"key": "BP-2", "summary": "Yeşil", "description": "",
         "component": "Frontend", "priority": "Low", "status": "Open"},
    ])


# =============================================================================
# Structural, not a sentence
# =============================================================================

def test_the_theme_is_a_code_and_params_rather_than_a_sentence(one_keyword, no_keywords):
    """This file used to assert the two Turkish sentences here.

    They moved to ui/locales/{tr,en}.json in the same commit that added this
    test, and tests/test_i18n_locales.py now holds the literals character for
    character. The diff of that commit is the evidence: the strings leave this
    file and pattern_detector.py, and arrive in tr.json.
    """
    assert "summary" not in one_keyword, "the detector is building sentences again"

    assert one_keyword["code"] == "pattern_theme"
    assert one_keyword["params"] == {"bug_count": 3, "keywords": ["timeout"]}

    assert no_keywords["code"] == "pattern_theme"
    assert no_keywords["params"] == {"bug_count": 2, "keywords": []}


# =============================================================================
# The rest of the shape, which the conversion must not disturb
# =============================================================================

def test_a_cluster_carries_its_bugs_and_counts(one_keyword):
    assert one_keyword["pattern_id"] == 1
    assert one_keyword["bug_keys"] == ["AP-1", "AP-2", "AP-3"]
    assert one_keyword["bug_count"] == 3


def test_the_common_component_and_priority_are_the_modal_ones(one_keyword):
    assert one_keyword["common_component"] == "Payment"
    assert one_keyword["common_priority"] == "High"


def test_severity_comes_from_size_and_priority(one_keyword, no_keywords):
    # Three bugs with one Highest → "high"; two Low bugs both open → "medium".
    assert one_keyword["severity"] == "high"
    assert no_keywords["severity"] == "medium"


def test_keywords_are_the_words_shared_by_two_or_more_bugs(one_keyword, no_keywords):
    """Set comparison is enough here; the order is pinned by the tie tests below."""
    assert set(one_keyword["common_keywords"]) == {"timeout"}
    assert no_keywords["common_keywords"] == []


def test_no_collection_means_no_patterns():
    bugs = [{"key": "AP-1", "summary": "x", "description": "y"}]
    assert detect_patterns(bugs, None) == []


# =============================================================================
# Ties — the same answer in every process
# =============================================================================

# Every count ties: three modules twice each, Low and Medium three times each,
# ten words in exactly two bugs each. Listed out of key order on purpose.
_TIED_WORDS = {
    "alfa": ("T-1", "T-2"), "bravo": ("T-1", "T-2"), "charlie": ("T-3", "T-4"),
    "delta": ("T-3", "T-4"), "echo": ("T-5", "T-6"), "foxtrot": ("T-5", "T-6"),
    "golf": ("T-1", "T-3"), "hotel": ("T-2", "T-4"), "india": ("T-3", "T-5"),
    "juliet": ("T-4", "T-6"),
}
_TIED = [  # (key, component, priority)
    ("T-5", "Reporting", "Medium"), ("T-2", "Frontend", "Medium"),
    ("T-6", "Inventory", "Low"), ("T-1", "Reporting", "Low"),
    ("T-4", "Frontend", "Medium"), ("T-3", "Inventory", "Low"),
]
TIED_BUGS = [
    {"key": key, "component": component, "priority": priority, "status": "Open",
     "summary": " ".join(w for w, keys in _TIED_WORDS.items() if key in keys),
     "description": ""}
    for key, component, priority in _TIED
]

# The child's stub mirrors StubCollection; the test module itself is not
# importable from a bare interpreter.
_CHILD = """
import json, sys
from defect_risk_analyzer.pattern_detector import detect_patterns

bugs = json.loads(sys.stdin.read())

class Stub:
    def count(self):
        return len(bugs)

    def query(self, query_texts, n_results, include):
        metadatas = [{"key": bug["key"]} for bug in bugs][:n_results]
        return {"metadatas": [metadatas], "distances": [[0.1] * len(metadatas)]}

(pattern,) = detect_patterns(bugs, Stub())
print(json.dumps([pattern["common_component"], pattern["common_priority"],
                  pattern["common_keywords"], [b["key"] for b in pattern["bugs"]]]))
"""


def test_ties_resolve_the_same_way_under_every_hash_seed():
    """Eight interpreters, eight fixed hash seeds, one answer.

    Fixed seeds make the old code's answers fixed too, so its red is the same
    on every run rather than a matter of luck. PYTHONHASHSEED reaches the child
    only because it is started without -E or -I, which ignore PYTHON*
    variables. PYTHONPATH is passed for the reason test_core_boundary.py gives.
    """
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}
    answers = {}
    for seed in range(8):
        result = subprocess.run(
            [sys.executable, "-c", _CHILD],
            input=json.dumps(TIED_BUGS),
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**env, "PYTHONHASHSEED": str(seed)},
            cwd=str(REPO_ROOT),
            timeout=120,
        )
        assert result.returncode == 0, result.stderr
        answers[seed] = json.loads(result.stdout)

    expected = [
        "Frontend",
        "Medium",
        ["alfa", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel"],
        ["T-1", "T-2", "T-3", "T-4", "T-5", "T-6"],
    ]
    wrong = {seed: answer for seed, answer in answers.items() if answer != expected}
    assert not wrong, wrong


def test_a_tie_goes_to_the_first_name_and_the_more_severe_priority():
    """Modules tie 2-2-2 and so do priorities.

    Ö is U+00D6, so Ödeme sorts after Arama and Rapor. Medium outranks Low by
    scoring.PRIORITY_WEIGHTS; Blocker, which that table does not know, ranks
    after every known priority. The first key carries neither winner, so
    insertion order cannot pass this by accident.
    """
    from defect_risk_analyzer.pattern_detector import _most_common_priority

    pattern = _cluster([
        {"key": "K-1", "summary": "ortak", "description": "",
         "component": "Rapor", "priority": "Low", "status": "Open"},
        {"key": "K-2", "summary": "ortak", "description": "",
         "component": "Ödeme", "priority": "Blocker", "status": "Open"},
        {"key": "K-3", "summary": "ortak", "description": "",
         "component": "Arama", "priority": "Medium", "status": "Open"},
        {"key": "K-4", "summary": "ortak", "description": "",
         "component": "Rapor", "priority": "Blocker", "status": "Open"},
        {"key": "K-5", "summary": "ortak", "description": "",
         "component": "Ödeme", "priority": "Medium", "status": "Open"},
        {"key": "K-6", "summary": "ortak", "description": "",
         "component": "Arama", "priority": "Low", "status": "Open"},
    ])

    assert (pattern["common_component"], pattern["common_priority"]) == ("Arama", "Medium")
    assert _most_common_priority(Counter({"Blocker": 2, "Lowest": 2})) == "Lowest"
    assert _most_common_priority(Counter({"Zeta": 1, "Blocker": 1})) == "Blocker"


def test_keywords_tied_on_count_go_in_code_point_order_and_stop_at_eight():
    """yavaş is in three bugs and eight words in two: nine qualify, eight fit.

    Code point order puts ç (U+00E7) and ö (U+00F6) after z, so ödeme is the
    word that does not fit.
    """
    bugs = [
        {"summary": "yavaş araba zebra çanta ödeme kalem masa", "description": ""},
        {"summary": "yavaş araba zebra çanta ödeme kalem", "description": ""},
        {"summary": "yavaş masa defter lamba", "description": ""},
        {"summary": "defter lamba", "description": ""},
    ]

    assert _extract_common_keywords(bugs) == [
        "yavaş", "araba", "defter", "kalem", "lamba", "masa", "zebra", "çanta",
    ]
