"""
chromadb 1.x izleyicisi (`.github/scripts/chromadb_1x_watch.py`) ve iş akışı.

Kararı veren saf kısım — `classify` — sahte raporlarla sınanıyor. Ağ yok:
gerçek pip-audit CI'da, haftada bir ve izleyiciye dokunan PR'larda koşuyor.
Sahte raporların biçimi gerçek bir `pip-audit -r` ölçümünden (Faz 6D-4d-3,
pip-audit 2.10.1, `chromadb==1.5.9` ve `chromadb>=1.0.0`, 2026-10-07): kayıt
kimliği PYSEC, CVE ve GHSA alias'ta, ve 45829 iki özdeş kayıt olarak geliyor
(PYSEC-2026-311 ×2). GHSA kimlikli biçim o ölçümde görülmedi; alias yolunun
ikinci biçimi olarak ayrıca sınanıyor.

DURUMLAR — tek yeşil "erteleme haklı". Ayrıntı betiğin docstring'inde; burada
her hücrenin bir testi var, iki kural özellikle:

  * **Pozitif kontrol.** Kontrol (`chromadb==CONTROL_VERSION`) 45829'u
    raporlamıyorsa hedef ne derse desin sonuç "izleyici bozuk". Bu olmadan
    bozuk bir tarayıcı, hedefte 45829'u göremeyince "iş var" derdi.
  * **Öteki üç kayıt koşul değil.** Hedefte hiç chromadb kaydı yoksa sonuç
    "iş var": yeni bir 1.x sürümü dört advisory'nin hiçbirinin aralığında
    olmayabilir (dördü de `last_affected: 1.5.9`), ve tam o an sessiz
    kalmamak bu iş akışının varlık sebebi.

Bekçinin bekçisi: eksik, boş ya da bozuk bir rapor hiçbir yolla "erteleme
haklı" vermez — her rapor ve her bozukluk biçimi için ayrı bir parametre var.
"""

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

# The repo, not the config sandbox — same reason as tests/test_dependency_pins.py.
REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / ".github" / "scripts"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "chromadb-1x-watch.yml"


def _load(name):
    # CI scripts, not part of the package: loaded by path. The watcher imports
    # the gate by name, so the gate goes into sys.modules first (reused if
    # tests/test_pip_audit_gate.py already put it there); dataclasses also
    # needs each module registered before exec.
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_load("pip_audit_gate")
watch = _load("chromadb_1x_watch")
State = watch.State


def _vuln(vuln_id, *aliases):
    return {"id": vuln_id, "fix_versions": [], "aliases": list(aliases), "description": ""}


def _dep(name, version, *vulns):
    return {"name": name, "version": version, "vulns": list(vulns)}


def _report(*deps):
    return json.dumps({"dependencies": list(deps), "fixes": []})


# 45829 as pip-audit reported it (twice, identical) in the real measurement;
# the GHSA-keyed form was not seen there and covers the second alias path.
SENTINEL_PYSEC = _vuln("PYSEC-2026-311", "CVE-2026-45829", "GHSA-f4j7-r4q5-qw2c")
SENTINEL_GHSA = _vuln("GHSA-f4j7-r4q5-qw2c", "CVE-2026-45829", "PYSEC-2026-311")
OTHER_THREE = (
    _vuln("PYSEC-2026-3813", "CVE-2026-45830", "GHSA-2wm9-hf6c-p5cr"),
    _vuln("PYSEC-2026-3814", "CVE-2026-45833", "GHSA-36p7-vc44-83pf"),
    _vuln("PYSEC-2026-3815", "CVE-2026-45831", "GHSA-xph7-9rjv-w5fr"),
)
CLEAN = _dep("numpy", "2.4.6")


def _chromadb(version, *vulns):
    return _report(_dep("chromadb", version, *vulns), CLEAN)


# The real reports' chromadb part: five records, four distinct.
REAL = (SENTINEL_PYSEC, SENTINEL_PYSEC, *OTHER_THREE)
CONTROL = _chromadb(watch.CONTROL_VERSION, *REAL)
TARGET = _chromadb("1.5.9", *REAL)


# --- the green state and "work to do" ---------------------------------------


def test_both_reports_carry_45829_is_justified():
    result = watch.classify(CONTROL, TARGET)
    assert result.state is State.JUSTIFIED
    assert result.reasons == ()
    assert len(result.target.findings) == 4
    assert [f.records for f in result.target.findings if watch.SENTINEL in f.ids] == [2]


def test_target_without_45829_but_with_the_other_three_is_work():
    result = watch.classify(CONTROL, _chromadb("1.6.0", *OTHER_THREE))
    assert result.state is State.WORK
    assert result.target.version == "1.6.0"


def test_target_without_any_chromadb_record_is_work():
    """K6'nın asıl hücresi: eski "öteki üçü hâlâ raporlanıyor" şartı bunu susturdu."""
    result = watch.classify(CONTROL, _chromadb("1.6.0"))
    assert result.state is State.WORK
    assert result.target.findings == ()


def test_target_with_45829_alone_is_justified():
    """Öteki üç kayıt koşul değil, yalnız notice'te yazılır."""
    result = watch.classify(CONTROL, _chromadb("1.6.0", SENTINEL_PYSEC))
    assert result.state is State.JUSTIFIED


@pytest.mark.parametrize(
    "records",
    [(SENTINEL_PYSEC,), (SENTINEL_GHSA,), (SENTINEL_PYSEC, SENTINEL_GHSA)],
    ids=["pysec", "ghsa", "mukerrer"],
)
def test_45829_matches_through_aliases(records):
    """Kimlik hiçbir biçimde CVE değil; eşleşme alias'tan, mükerrerler tek bulgu."""
    result = watch.classify(
        _chromadb(watch.CONTROL_VERSION, *records), _chromadb("1.5.9", *records)
    )
    assert result.state is State.JUSTIFIED
    assert len(result.target.findings) == 1
    assert result.target.findings[0].records == len(records)


# --- the positive control ---------------------------------------------------


def test_control_without_45829_is_broken():
    result = watch.classify(_chromadb(watch.CONTROL_VERSION, *OTHER_THREE), TARGET)
    assert result.state is State.BROKEN
    assert any("pozitif kontrol" in r for r in result.reasons)


def test_control_on_another_version_is_broken():
    result = watch.classify(_chromadb("1.5.8", SENTINEL_PYSEC), TARGET)
    assert result.state is State.BROKEN
    assert any("beklenen " + watch.CONTROL_VERSION in r for r in result.reasons)


# --- broken reports: never green --------------------------------------------

_BROKEN_REPORTS = {
    "yok": None,
    "bos": "",
    "json-degil": "not json",
    "dependencies-yok": "{}",
    "taranan-yok": json.dumps({"dependencies": []}),
    "chromadb-atlanmis": json.dumps({"dependencies": [
        {"name": "chromadb", "skip_reason": "Dependency not found on PyPI"}, CLEAN,
    ]}),
}


@pytest.mark.parametrize("kind", list(_BROKEN_REPORTS))
@pytest.mark.parametrize("which", ["kontrol", "hedef"])
def test_broken_report_is_broken(which, kind):
    broken = _BROKEN_REPORTS[kind]
    control, target = (broken, TARGET) if which == "kontrol" else (CONTROL, broken)
    result = watch.classify(control, target)
    assert result.state is State.BROKEN
    assert [r for r in result.reasons if r.startswith(which + ":")], result.reasons


@pytest.mark.parametrize("which", ["kontrol", "hedef"])
def test_chromadb_missing_from_a_report_is_broken(which):
    no_chromadb = _report(CLEAN)
    control, target = (no_chromadb, TARGET) if which == "kontrol" else (CONTROL, no_chromadb)
    result = watch.classify(control, target)
    assert result.state is State.BROKEN
    assert f"{which}: raporda chromadb yok" in result.reasons


def test_unparseable_target_version_is_broken():
    result = watch.classify(CONTROL, _chromadb("dev", SENTINEL_PYSEC))
    assert result.state is State.BROKEN
    assert any("ayristirilamiyor" in r for r in result.reasons)


@pytest.mark.parametrize(
    "records",
    [(SENTINEL_PYSEC,), OTHER_THREE],
    ids=["45829-tasirken", "0.6.3-benzeri"],
)
def test_target_below_1_0_is_broken(records):
    """`>=1.0.0` 0.x'e çözülemez. İki parametre iki maskeyi tutar: biri "haklı",
    öteki (bugünkü 0.6.3 verisi: 45829 yok, üçü var) "iş var" olurdu."""
    result = watch.classify(CONTROL, _chromadb("0.6.3", *records))
    assert result.state is State.BROKEN
    assert any("0.6.3 olarak cozulmus" in r for r in result.reasons)


def test_every_broken_reason_is_reported():
    result = watch.classify(None, None)
    assert result.state is State.BROKEN
    assert result.reasons == ("kontrol: rapor yok", "hedef: rapor yok")


# --- the command line -------------------------------------------------------


@pytest.mark.parametrize(
    ("control", "target", "state"),
    [
        (CONTROL, TARGET, State.JUSTIFIED),
        (CONTROL, _chromadb("1.6.0", *OTHER_THREE), State.WORK),
        (None, None, State.BROKEN),
    ],
    ids=["hakli", "is-var", "dosyalar-yok"],
)
def test_main_exit_code_and_title(tmp_path, capsys, control, target, state):
    paths = {}
    for name, text in (("control", control), ("target", target)):
        paths[name] = tmp_path / f"{name}.json"
        if text is not None:
            paths[name].write_text(text, encoding="utf-8")
    code = watch.main(
        ["evaluate", "--control", str(paths["control"]), "--target", str(paths["target"])]
    )
    out = capsys.readouterr().out
    assert code == state.value
    assert f"title={watch.TITLES[state]}::" in out
    if state is not State.JUSTIFIED:
        assert watch.TITLES[State.JUSTIFIED] not in out


def test_main_unexpected_error_is_broken(tmp_path, capsys, monkeypatch):
    """Yakalanmasa Python 1 ile çıkardı — "iş var"ın kodu."""

    def boom(*_):
        raise RuntimeError("boom")

    monkeypatch.setattr(watch, "classify", boom)
    code = watch.main(
        ["evaluate", "--control", str(tmp_path / "c"), "--target", str(tmp_path / "t")]
    )
    out = capsys.readouterr().out
    assert code == State.BROKEN.value
    assert f"title={watch.TITLES[State.BROKEN]}::" in out


def test_write_requirements_uses_the_single_control_constant(tmp_path):
    assert watch.main(["write-requirements", str(tmp_path)]) == 0
    control = (tmp_path / "chromadb-control.txt").read_text(encoding="utf-8")
    target = (tmp_path / "chromadb-target.txt").read_text(encoding="utf-8")
    assert control == f"chromadb=={watch.CONTROL_VERSION}\n"
    assert target == "chromadb>=1.0.0\n"


def test_titles_are_ascii_without_separators():
    """Bir workflow-command özelliğinde `:` ve `,` kaçış ister; kapının kuralı."""
    titles = [*watch.TITLES.values(), watch.DISTRIBUTION_TITLE]
    bad = [t for t in titles if not t.isascii() or ":" in t or "," in t]
    assert not bad, bad


# --- the repo around it -----------------------------------------------------

_CHROMADB_1X = re.compile(r"^\s*chromadb\s*(==\s*1\.|>=?\s*1)", re.MULTILINE | re.IGNORECASE)


def test_no_requirements_file_names_chromadb_1x():
    """İki requirements dosyası `$RUNNER_TEMP`'te üretilir: Dependabot depodaki
    her requirements dosyasını toplar ve 1.x satırını görürse ertelemeyi deler.

    Kök ve `.github/` taranır (Dependabot'un pip dizini `/`). Hangi dizinleri
    gerçekten topladığı ölçülmedi; kapsam bir çıkarım. `requirements.txt`'in
    bulunması taramanın boş dönmediğini kanıtlar.
    """
    files = sorted(
        {*REPO_ROOT.glob("*.txt"), *REPO_ROOT.glob("*.in"),
         *(REPO_ROOT / ".github").rglob("*.txt"), *(REPO_ROOT / ".github").rglob("*.in")}
    )
    assert REPO_ROOT / "requirements.txt" in files
    offenders = [
        p.relative_to(REPO_ROOT).as_posix()
        for p in files
        if _CHROMADB_1X.search(p.read_text(encoding="utf-8", errors="replace"))
    ]
    assert not offenders, f"chromadb 1.x satiri depodaki bir requirements dosyasinda: {offenders}"


def test_watch_workflow_triggers():
    """Haftalık takvim, elle tetikleme, ve izleyiciyi değiştiren her şeyde PR koşusu.

    `pip_audit_gate.py` listede çünkü izleyici onu import ediyor;
    `requirements-dev.txt` çünkü pip-audit sürümü oradan geliyor.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    assert re.search(r"^  schedule:\n    #.*\n(    #.*\n)*    - cron: ", text, re.MULTILINE)
    assert re.search(r"^  workflow_dispatch:", text, re.MULTILINE)
    paths = re.search(r"^  pull_request:\n    paths:\n((?:      - .*\n)+)", text, re.MULTILINE)
    assert paths, "pull_request.paths blogu bulunamadi"
    listed = {line.strip()[2:] for line in paths.group(1).splitlines()}
    assert listed == {
        ".github/workflows/chromadb-1x-watch.yml",
        ".github/scripts/chromadb_1x_watch.py",
        ".github/scripts/pip_audit_gate.py",
        "requirements-dev.txt",
    }
