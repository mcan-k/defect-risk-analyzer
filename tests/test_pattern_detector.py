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

KEYWORD ORDER IS NOT DETERMINISTIC and the fixtures work around it rather than
hiding it. _extract_common_keywords counts over `set(words)` and lets
Counter.most_common break ties by insertion order, so equally common keywords
come out in a different order in every process (measured: six runs, six
orders). The exact-sentence pin therefore uses a cluster with exactly ONE
common keyword. See docs/KNOWN-DEBT.md — this is a live defect in what the user
reads, not a test inconvenience: the "Olası Ortak Neden" suggestion on the
Buglar page names keywords[0] and keywords[1].
"""

import pytest

from defect_risk_analyzer.pattern_detector import detect_patterns


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
    """Set comparison, not list: the order is not stable across processes."""
    assert set(one_keyword["common_keywords"]) == {"timeout"}
    assert no_keywords["common_keywords"] == []


def test_no_collection_means_no_patterns():
    bugs = [{"key": "AP-1", "summary": "x", "description": "y"}]
    assert detect_patterns(bugs, None) == []
