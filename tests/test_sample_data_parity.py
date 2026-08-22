"""data/sample_bugs_en.json is a translation, and this proves it is only that.

The English demo set exists so an English-speaking evaluator does not get a
translated menu wrapped around 20 Turkish bug reports. The risk it introduces
is that a second data file quietly becomes a second source of truth: a changed
priority, a shifted date, a renamed component, and the numbers the tool reports
would depend on which language you happened to pick.

So the file is not checked by reading it. It is checked by DERIVING the same
things from both files and comparing:

  * every field that feeds scoring is identical, bug for bug
  * calculate_module_stats and calculate_risk_score agree exactly
  * and both still agree with tests/data/scores-aff55c6-now2026-04-01.json,
    the committed snapshot that predates all of this

That last one is the real point. tests/data/ is untouchable, and the English
data must leave it exactly where it was.

Bug keys stay identical too (AP-101 …). They appear in the snapshots, in
test_blind_spot_contract.py and inside rendered sentences; renaming them would
break the chain in places no reading of this file would reveal.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from defect_risk_analyzer.core.scoring import calculate_module_stats, calculate_risk_score

TESTS_DATA = Path(__file__).resolve().parent / "data"
SNAPSHOT = TESTS_DATA / "scores-aff55c6-now2026-04-01.json"

#: The clock the committed snapshot was produced against.
NOW = datetime(2026, 4, 1, 12, 0, tzinfo=timezone(timedelta(hours=3)))

#: Everything calculate_module_stats and calculate_risk_score can see. If a
#: field is in here it may not differ between the two files; if it is not, it
#: is prose and translating it is the whole point.
SCORING_FIELDS = ("key", "created", "updated", "priority", "status", "component", "labels")

TRANSLATED_FIELDS = ("summary", "description", "assignee", "reporter")


@pytest.fixture(scope="module")
def turkish(sample_bugs_path: Path) -> list[dict]:
    return json.loads(sample_bugs_path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def english(sample_bugs_path: Path) -> list[dict]:
    """Read from the repo, like sample_bugs_path: config points at the sandbox."""
    return json.loads(
        (sample_bugs_path.parent / "sample_bugs_en.json").read_text(encoding="utf-8")
    )


# ---------------------------------------------------------------------------
# The two files describe the same bugs
# ---------------------------------------------------------------------------


def test_the_same_bugs_in_the_same_order(turkish, english):
    assert [bug["key"] for bug in english] == [bug["key"] for bug in turkish]


@pytest.mark.parametrize("field", SCORING_FIELDS)
def test_every_scoring_field_is_identical(field, turkish, english):
    differing = [
        f"{tr['key']}.{field}: {tr.get(field)!r} vs {en.get(field)!r}"
        for tr, en in zip(turkish, english, strict=True)
        if tr.get(field) != en.get(field)
    ]
    assert not differing, "; ".join(differing)


@pytest.mark.parametrize("field", TRANSLATED_FIELDS)
def test_every_prose_field_was_actually_translated(field, turkish, english):
    """The other direction: a file that is a copy is not a translation.

    Without this, forgetting one bug would leave a Turkish sentence in the
    English demo and every check above would still pass.
    """
    untranslated = [
        tr["key"]
        for tr, en in zip(turkish, english, strict=True)
        if tr.get(field) == en.get(field)
    ]
    assert not untranslated, f"{field} not translated for: {untranslated}"


def test_the_two_files_have_the_same_shape(turkish, english):
    for tr, en in zip(turkish, english, strict=True):
        assert set(tr) == set(en), f"{tr['key']} has different fields"


# ---------------------------------------------------------------------------
# The numbers do not move
# ---------------------------------------------------------------------------


def _scores(bugs: list[dict]) -> tuple[dict, dict]:
    stats = calculate_module_stats(bugs, now=NOW)
    return stats, {name: calculate_risk_score(name, data) for name, data in stats.items()}


def test_module_stats_and_risk_scores_are_identical(turkish, english):
    """The claim the whole file rests on: translating prose costs nothing."""
    tr_stats, tr_scores = _scores(turkish)
    en_stats, en_scores = _scores(english)

    assert en_stats == tr_stats
    assert en_scores == tr_scores


def test_the_english_data_leaves_the_committed_snapshot_where_it_was(english):
    """tests/data/ is untouchable, and this is what makes that checkable.

    Read only — the snapshot is never rewritten, whatever the outcome.
    """
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    stats, scores = _scores(english)

    assert set(stats) == set(snapshot["modules"])
    for module, expected in snapshot["modules"].items():
        assert scores[module] == expected["risk_score"], module


# ---------------------------------------------------------------------------
# Which file gets loaded
# ---------------------------------------------------------------------------


def test_the_persisted_language_picks_the_demo_file(monkeypatch, sample_bugs_path):
    """From config.LANGUAGE, not from a live session. See config.sample_bugs_file.

    Choosing on the live value would mean clearing the cached analysis service
    on every toggle, which means re-indexing into ChromaDB — the silent
    side effect Faz 4(a) was written to remove.
    """
    import shutil

    from defect_risk_analyzer import config

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(sample_bugs_path, config.SAMPLE_BUGS_FILE)
    shutil.copyfile(sample_bugs_path.parent / "sample_bugs_en.json", config.SAMPLE_BUGS_EN_FILE)

    monkeypatch.setattr(config, "LANGUAGE", "tr")
    assert config.sample_bugs_file() == config.SAMPLE_BUGS_FILE

    monkeypatch.setattr(config, "LANGUAGE", "en")
    assert config.sample_bugs_file() == config.SAMPLE_BUGS_EN_FILE


def test_a_missing_translation_falls_back_to_a_working_demo(monkeypatch, sample_bugs_path):
    """An absent English file must not leave the user with an empty bug list."""
    import shutil

    from defect_risk_analyzer import config

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(sample_bugs_path, config.SAMPLE_BUGS_FILE)
    config.SAMPLE_BUGS_EN_FILE.unlink(missing_ok=True)

    monkeypatch.setattr(config, "LANGUAGE", "en")
    assert config.sample_bugs_file() == config.SAMPLE_BUGS_FILE
