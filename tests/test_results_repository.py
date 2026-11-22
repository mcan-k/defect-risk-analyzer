"""
`adapters/results_repository.py` — every read and write path (Faz 6E-2, PR 12).

The 6E discovery measured this module at 47.8% of lines and 25% of branches:
the suite only ever reached the "file does not exist" path, through the
services that use it. Nothing ran a read of an existing file, the quarantine,
any of the three writers or `_write_json` at all (KNOWN-DEBT, "6E keşfinde
bulunan küçük test boşlukları", results_repository row).

What is pinned here is today's behaviour, including the two failure contracts
the service relies on:

  * a read that cannot be used comes back empty — `[]` for the two result
    lists, `{}` for the density map — and a file that is not valid JSON is
    moved aside to `<name>.corrupt-<timestamp>` rather than left to be
    overwritten by the next write;
  * a write that fails returns False and logs; it never raises.

What is NOT pinned here: that a failed write reaches nobody but the log, and
that a write failing part way leaves a truncated file behind. Both are known
defects, measured in 6E-2 PR12 (KNOWN-DEBT, "Failed result writes are logged,
not surfaced"); they are documented with xfail(strict) tests of their own, and
their fix is a separate PR.

Every repository gets explicit paths under tmp_path, so no test reads or writes
config's data directory — except the one that checks the defaults, which only
compares paths.
"""

import json
import logging
import re
from pathlib import Path

from defect_risk_analyzer import config
from defect_risk_analyzer.adapters.results_repository import ResultsRepository

LOGGER = "defect_risk_analyzer.adapters.results_repository"


def _repository(directory: Path) -> ResultsRepository:
    return ResultsRepository(
        results_file=directory / "analysis_results.json",
        webhook_results_file=directory / "webhook_results.json",
        defect_density_file=directory / "defect_density.json",
    )


def _blocked_repository(tmp_path: Path) -> ResultsRepository:
    """Every file's parent is a regular file, so `mkdir` fails with an OSError.

    Chosen over a read-only file or directory because it fails the same way on
    Windows, on Linux and for root, who ignores permission bits.
    """
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory", encoding="utf-8")
    return _repository(blocker)


def _errors(caplog) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER and record.levelno >= logging.ERROR
    ]


def _result(bug_key: str | None, score: int, query: str = "q") -> dict:
    return {"bug_key": bug_key, "query": query, "risk_score": score}


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def test_missing_files_read_as_empty_without_creating_anything(tmp_path, caplog):
    repository = _repository(tmp_path)

    assert repository.load_results() == []
    assert repository.load_webhook_results() == []
    assert repository.load_defect_density() == {}
    assert list(tmp_path.iterdir()) == []
    assert _errors(caplog) == [], "a missing file is the normal first run, not an error"


def test_a_file_of_the_wrong_shape_reads_as_empty_and_is_left_alone(tmp_path):
    repository = _repository(tmp_path)
    (tmp_path / "analysis_results.json").write_text('{"bug_key": "AP-1"}', encoding="utf-8")
    (tmp_path / "webhook_results.json").write_text('"text"', encoding="utf-8")
    (tmp_path / "defect_density.json").write_text("[1, 2]", encoding="utf-8")

    assert repository.load_results() == []
    assert repository.load_webhook_results() == []
    assert repository.load_defect_density() == {}
    # Valid JSON of the wrong shape is not corrupt: nothing is quarantined.
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "analysis_results.json", "defect_density.json", "webhook_results.json",
    ]


def test_corrupt_json_is_quarantined_byte_for_byte_and_not_overwritten(tmp_path, caplog):
    repository = _repository(tmp_path)
    damaged = b'[{"bug_key": "AP-1", "risk_score": 4'
    (tmp_path / "analysis_results.json").write_bytes(damaged)

    assert repository.load_results() == []

    files = sorted(p.name for p in tmp_path.iterdir())
    assert len(files) == 1
    assert re.fullmatch(r"analysis_results\.json\.corrupt-\d{8}-\d{6}", files[0]), files
    assert (tmp_path / files[0]).read_bytes() == damaged
    errors = _errors(caplog)
    assert any(message.startswith("Corrupt JSON in ") for message in errors), errors
    assert any(message.startswith("Moved corrupt file to ") for message in errors), errors

    # The next write starts a new file; the quarantined one is still there.
    assert repository.upsert_result(_result("AP-2", 10)) is True
    assert repository.load_results() == [_result("AP-2", 10)]
    assert (tmp_path / files[0]).read_bytes() == damaged


def test_a_quarantine_that_cannot_move_the_file_leaves_it_and_logs(
    tmp_path, monkeypatch, caplog
):
    repository = _repository(tmp_path)
    damaged = b"{not json"
    target = tmp_path / "webhook_results.json"
    target.write_bytes(damaged)

    def refuse(self, destination):
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(Path, "rename", refuse)

    assert repository.load_webhook_results() == []
    assert target.read_bytes() == damaged
    assert [p.name for p in tmp_path.iterdir()] == ["webhook_results.json"]
    assert any(message.startswith("Could not quarantine ") for message in _errors(caplog))


def test_a_file_that_cannot_be_read_reads_as_empty_and_is_left_alone(tmp_path, caplog):
    """A directory where the file should be: open() raises an OSError
    (PermissionError on Windows, IsADirectoryError elsewhere). That is not
    corruption, so nothing is moved."""
    repository = _repository(tmp_path)
    (tmp_path / "defect_density.json").mkdir()

    assert repository.load_defect_density() == {}
    assert (tmp_path / "defect_density.json").is_dir()
    assert [p.name for p in tmp_path.iterdir()] == ["defect_density.json"]
    errors = _errors(caplog)
    assert any(message.startswith("Could not read ") for message in errors), errors
    assert not any("corrupt" in message.lower() for message in errors), errors


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def test_an_upserted_result_reads_back_and_is_written_as_readable_utf8(tmp_path):
    repository = _repository(tmp_path)
    result = {"bug_key": "AP-1", "query": "Giriş başarısız — şifre sıfırlama", "risk_score": 72}

    assert repository.upsert_result(result) is True

    assert repository.load_results() == [result]
    assert repository.load_webhook_results() == [], "only the analysis results file is written"
    written = (tmp_path / "analysis_results.json").read_text(encoding="utf-8")
    # ensure_ascii=False, indent=2: the file stays readable by a person.
    assert json.loads(written) == [result]
    assert written == json.dumps([result], ensure_ascii=False, indent=2)
    assert not (tmp_path / "webhook_results.json").exists()


def test_upsert_replaces_the_result_with_the_same_bug_key(tmp_path):
    repository = _repository(tmp_path)
    repository.upsert_result(_result("AP-1", 10))
    repository.upsert_result(_result("AP-2", 20))

    assert repository.upsert_result(_result("AP-1", 30)) is True

    # The replaced result moves to the end; the other one is untouched.
    assert repository.load_results() == [_result("AP-2", 20), _result("AP-1", 30)]


def test_results_without_a_bug_key_are_always_appended(tmp_path):
    """Free-text analyses carry bug_key None. They are never deduplicated:
    neither against each other nor against keyed results."""
    repository = _repository(tmp_path)
    repository.upsert_result(_result("AP-1", 10))
    repository.upsert_result(_result(None, 20, query="login"))

    assert repository.upsert_result(_result(None, 30, query="login")) is True

    assert repository.load_results() == [
        _result("AP-1", 10), _result(None, 20, query="login"), _result(None, 30, query="login"),
    ]


def test_webhook_results_keep_every_event_in_their_own_file(tmp_path):
    repository = _repository(tmp_path)
    first, second = _result("AP-9", 40), _result("AP-9", 50)

    assert repository.append_webhook_result(first) is True
    assert repository.append_webhook_result(second) is True

    # A history, not a map: the same key twice is two entries.
    assert repository.load_webhook_results() == [first, second]
    assert repository.load_results() == []
    assert not (tmp_path / "analysis_results.json").exists()


def test_the_defect_density_map_round_trips(tmp_path):
    repository = _repository(tmp_path)
    density = {"Ödeme": {"bug_density": 0.4, "risk_score": 55}, "Auth": {"bug_density": 0.1}}

    assert repository.save_defect_density(density) is True

    assert repository.load_defect_density() == density
    assert sorted(p.name for p in tmp_path.iterdir()) == ["defect_density.json"]


def test_a_write_creates_missing_parent_directories(tmp_path):
    repository = _repository(tmp_path / "not" / "yet" / "there")

    assert repository.append_webhook_result(_result("AP-1", 10)) is True

    assert (tmp_path / "not" / "yet" / "there" / "webhook_results.json").is_file()
    assert repository.load_webhook_results() == [_result("AP-1", 10)]


def test_a_failed_write_returns_false_logs_and_never_raises(tmp_path, caplog):
    repository = _blocked_repository(tmp_path)

    assert repository.upsert_result(_result("AP-1", 10)) is False
    assert repository.append_webhook_result(_result("AP-1", 10)) is False
    assert repository.save_defect_density({"Auth": {"bug_density": 0.1}}) is False

    errors = _errors(caplog)
    assert len(errors) == 3, errors
    assert all(message.startswith("Failed to write ") for message in errors), errors
    assert (tmp_path / "blocker").read_text(encoding="utf-8") == "a file, not a directory"


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_the_default_paths_come_from_config():
    repository = ResultsRepository()

    assert repository._results_file == config.ANALYSIS_RESULTS_FILE
    assert repository._webhook_results_file == config.WEBHOOK_RESULTS_FILE
    assert repository._defect_density_file == config.DEFECT_DENSITY_FILE
