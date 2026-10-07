"""
pip-audit kapısı (`.github/scripts/pip_audit_gate.py`) ve ignore listesinin
gerekçe bekçisi.

İKİ PARÇA, İKİ İŞ.

1. Kapının saf kısmı — `evaluate` ve `parse_report` — sahte raporlarla test
   ediliyor. Ağ yok: gerçek pip-audit CI'da koşuyor, burada yalnız kararı
   veren mantık sınanıyor. Sahte raporların biçimi PR #47'nin CI ölçümünden
   (2026-10-07, pip-audit 2.10.1): kayıt PYSEC kimliğiyle gelir, CVE/GHSA
   alias'tadır, aynı kayıt birden çok kez yazılabilir, projenin kendisi pypi
   kaynağında `skip_reason` ile atlanır.

2. Gerekçe bekçisi — koşul (a): ignore listesindeki her kimliğin
   `docs/KNOWN-DEBT.md`'de kendi satırı olmalı (chromadb bölümündeki
   `| **CVE-…** (GHSA-…) … | Tetikleyici: …` satırları). Ağsız; yalnız iki
   dosya okur. Koşul (c) da burada: bir satır yalnız bir ignore kimliği taşır
   ve bir tetikleyicisi vardır, toplu satır yok.

BEYAN EDİLMİŞ KÖR NOKTA (koşul a). Bekçi ignore listesinde BULUNAN kimlikler
üzerinde döner; listeden silinen bir satırı göremez — `test_dependabot_config.py`
M3'ünün dersi. Ama sistem bir bütün olarak kapalı: silinen bir ignore satırı,
pip-audit kaydı yeniden raporladığında kapıyı "yeni bulgu" ile kırmızıya
çevirir.

İkinci kör nokta: bekçi satırın VARLIĞINI tutar, içeriğinin doğruluğunu değil.
Tetikleyicinin hâlâ geçerli olup olmadığına bakan şey kapının "bayat ignore"
yönüdür.
"""

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

# The repo, not the config sandbox — same reason as tests/test_dependency_pins.py.
REPO_ROOT = Path(__file__).resolve().parents[1]
GATE_PATH = REPO_ROOT / ".github" / "scripts" / "pip_audit_gate.py"
IGNORE_PATH = REPO_ROOT / ".github" / "pip-audit-ignore.toml"
KNOWN_DEBT = REPO_ROOT / "docs" / "KNOWN-DEBT.md"

# The gate is a CI script, not part of the package, so it is loaded by path.
# It must be in sys.modules before exec: dataclasses looks its module up there.
_spec = importlib.util.spec_from_file_location("pip_audit_gate", GATE_PATH)
gate = importlib.util.module_from_spec(_spec)
sys.modules["pip_audit_gate"] = gate
_spec.loader.exec_module(gate)

# Bir gerekçe satırı: tablo satırı, kalın bir CVE ya da GHSA ile başlar, ardından
# parantez içinde öteki kimlik, ve ikinci hücrede bir tetikleyici.
_ROW = re.compile(
    r"^(?P<row>\| \*\*(?P<id>CVE-\d{4}-\d{4,}|GHSA(?:-[0-9a-z]{4}){3})\*\* \("
    r".*\| Tetikleyici: .*)$",
    re.MULTILINE,
)


def _vuln(vuln_id, *aliases, fix=()):
    return {"id": vuln_id, "fix_versions": list(fix), "aliases": list(aliases),
            "description": ""}


def _dep(name, version, *vulns):
    return {"name": name, "version": version, "vulns": list(vulns)}


def _report(*deps):
    return json.dumps({"dependencies": list(deps), "fixes": []})


PROJECT_SKIPPED = {
    "name": "defect-risk-analyzer",
    "skip_reason": "Dependency not found on PyPI and could not be audited",
}
CHROMADB = _dep(
    "chromadb", "0.6.3",
    _vuln("PYSEC-2026-3814", "CVE-2026-45833", "GHSA-36p7-vc44-83pf"),
    _vuln("PYSEC-2026-3815", "CVE-2026-45831", "GHSA-xph7-9rjv-w5fr"),
    _vuln("PYSEC-2026-3813", "CVE-2026-45830", "GHSA-2wm9-hf6c-p5cr"),
)
SETUPTOOLS_RECORD = _vuln(
    "PYSEC-2026-3447", "BIT-setuptools-2026-59890", "CVE-2026-59890",
    "GHSA-h35f-9h28-mq5c", fix=("83.0.0",),
)
CLEAN = _dep("numpy", "2.4.6")
IGNORED = ["CVE-2026-45830", "CVE-2026-45833", "CVE-2026-45831"]


# --- the gate ---------------------------------------------------------------


def test_report_matching_the_ignore_list_passes():
    """#47'deki yükseltilmiş ortamın raporu: üç chromadb kaydı, üçü de listede."""
    verdict = gate.evaluate(_report(CHROMADB, CLEAN, PROJECT_SKIPPED), IGNORED)
    assert verdict.ok
    assert (verdict.records, len(verdict.findings), verdict.scanned) == (3, 3, 2)


def test_new_finding_fails():
    """Listede olmayan bir açık kapıyı düşürür: setuptools 79.0.1, C1'siz CI."""
    setuptools = _dep("setuptools", "79.0.1", SETUPTOOLS_RECORD)
    verdict = gate.evaluate(_report(CHROMADB, setuptools, PROJECT_SKIPPED), IGNORED)
    assert not verdict.ok
    assert [f.key for f in verdict.new] == ["CVE-2026-59890"]
    assert verdict.stale == ()


def test_stale_ignore_fails():
    """Listede olup raporda görünmeyen kimlik bayattır — koşul (b)."""
    verdict = gate.evaluate(
        _report(CHROMADB, PROJECT_SKIPPED), [*IGNORED, "CVE-2099-00001"]
    )
    assert not verdict.ok
    assert verdict.stale == ("CVE-2099-00001",)
    assert verdict.new == ()


def test_cve_key_matches_a_pysec_record_through_its_aliases():
    """Kayıt PYSEC kimliğiyle gelir; CVE yalnız alias'ta. Eşleşme yine olmalı."""
    record = _dep("chromadb", "0.6.3",
                  _vuln("PYSEC-2026-3813", "CVE-2026-45830", "GHSA-2wm9-hf6c-p5cr"))
    verdict = gate.evaluate(_report(record), ["CVE-2026-45830"])
    assert verdict.ok
    assert verdict.findings[0].key == "CVE-2026-45830"


def test_ghsa_key_matches_when_there_is_no_cve():
    """CVE'si olmayan bir açık GHSA ile anahtarlanır ve öyle eşleşir."""
    record = _dep("somepkg", "1.0", _vuln("PYSEC-2026-0001", "GHSA-aaaa-bbbb-cccc"))
    verdict = gate.evaluate(_report(record), ["GHSA-aaaa-bbbb-cccc"])
    assert verdict.ok
    assert verdict.findings[0].key == "GHSA-aaaa-bbbb-cccc"


def test_duplicate_records_fold_into_one_finding():
    """pip-audit aynı kaydı iki kez yazabilir (#47, pypi, setuptools): bir bulgu."""
    setuptools = _dep("setuptools", "79.0.1", SETUPTOOLS_RECORD, SETUPTOOLS_RECORD)
    verdict = gate.evaluate(_report(setuptools), ["CVE-2026-59890"])
    assert verdict.records == 2
    assert len(verdict.findings) == 1
    assert verdict.findings[0].records == 2
    assert verdict.ok


def test_missing_report_fails(tmp_path, capsys):
    """pip-audit çöktü ve rapor yazılmadı: kapı yeşil geçmez."""
    code = gate.main(["--report", str(tmp_path / "yok.json"), "--ignore", str(IGNORE_PATH)])
    assert code == 1
    assert "rapor yok" in capsys.readouterr().out


def test_empty_report_fails():
    with pytest.raises(gate.ReportError, match="bos"):
        gate.evaluate("", IGNORED)


def test_non_json_report_fails():
    with pytest.raises(gate.ReportError, match="JSON degil"):
        gate.evaluate("Traceback (most recent call last):", IGNORED)


def test_report_without_dependencies_fails():
    with pytest.raises(gate.ReportError, match="dependencies"):
        gate.evaluate("{}", IGNORED)


def test_report_with_no_scanned_package_fails():
    """Hiç paket taranmadıysa sıfır bulgu iyi haber değil, bozuk taramadır."""
    with pytest.raises(gate.ReportError, match="hic paket taranmamis"):
        gate.evaluate(_report(), [])
    with pytest.raises(gate.ReportError, match="hic paket taranmamis"):
        gate.evaluate(_report(PROJECT_SKIPPED), [])


def test_a_skipped_package_other_than_the_project_fails():
    """Kısmi tarama yeşil geçmez: atlanabilecek tek paket projenin kendisi."""
    skipped = {"name": "numpy", "skip_reason": "could not be audited"}
    with pytest.raises(gate.ReportError, match="tarama eksik.*numpy"):
        gate.evaluate(_report(CHROMADB, skipped, PROJECT_SKIPPED), IGNORED)


# --- the justification guard --------------------------------------------------


def _rows() -> list[re.Match]:
    return list(_ROW.finditer(KNOWN_DEBT.read_text(encoding="utf-8")))


def test_every_ignored_id_has_its_own_known_debt_row():
    """Koşul (a) ve (c): her ignore kimliğinin tam bir gerekçe satırı var.

    Satır başka bir ignore kimliği taşımaz (toplu satır yok) ve desenin kendisi
    ikinci hücrede bir tetikleyici ister.
    """
    ignored = gate.load_ignore(IGNORE_PATH)
    rows = _rows()
    problems = []
    for vuln_id in ignored:
        own = [m for m in rows if m["id"] == vuln_id]
        if len(own) != 1:
            problems.append(f"{vuln_id}: {len(own)} gerekce satiri (tam 1 olmali)")
            continue
        others = [o for o in ignored if o != vuln_id and o in own[0]["row"]]
        if others:
            problems.append(f"{vuln_id}: satir baska ignore kimligi de tasiyor: {others}")
    assert not problems, (
        "Ignore listesi ile docs/KNOWN-DEBT.md gerekceleri ayrismis:\n  "
        + "\n  ".join(problems)
        + "\nHer kimlik icin `| **<CVE>** (<GHSA>) ... | Tetikleyici: ... |` "
        "bicimli tek bir satir gerekli (chromadb bolumu). Kimlik eklendiyse "
        "satirini ekleyin; acik kapandiysa ignore satirini da silin."
    )


def test_ignore_ids_and_known_debt_rows_are_found():
    """Bekçinin bekçisi: liste ve desen boş dönerse yukarıdaki test boşuna geçer.

    Liste meşru biçimde boşalırsa (chromadb'nin üç açığı da kapanırsa) bu test
    kırmızıya döner ve bilinçli bir karar ister: kapı ve bu dosya ya güncellenir
    ya silinir.
    """
    assert gate.load_ignore(IGNORE_PATH), f"{IGNORE_PATH} bos bir liste tasiyor."
    assert _rows(), (
        "docs/KNOWN-DEBT.md'de `| **CVE-...** (` bicimli hic gerekce satiri "
        "bulunamadi. Desen ya da tablo bicimi degismis; _ROW'u guncelleyin."
    )
