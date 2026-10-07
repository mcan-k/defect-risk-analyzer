"""
pip-audit kapısı: raporu ignore listesiyle iki yönde karşılaştırır.

TASARIM (Faz 6D-4d-2, kullanıcı kararları 2026-10-02 ve 10-07). pip-audit CI'da
ignore'suz koşar, JSON yazar ve adımı düşürmez. Kararı bu betik verir, ve iki
yönde düşer:

  * **yeni bulgu** — raporda olup ignore listesinin kapsamadığı bir açık;
  * **bayat ignore** — listede olup raporda artık görünmeyen bir kimlik. Bu,
    koşul (b)'nin mekanik tetikleyicisidir: düzeltme gelince satır silinir.

Bir de bekçinin bekçisi: rapor yoksa, boşsa, JSON değilse, `dependencies`
taşımıyorsa, hiç paket taranmamışsa ya da projenin kendisinden başka bir paket
atlanmışsa (`skip_reason`) kapı yeşil GEÇMEZ. Boş ya da eksik bir tarama iyi
haber değil, bozuk taramadır.

KİMLİK. Ignore listesi CVE'yi, CVE yoksa GHSA'yı tutar. pip-audit her açığı
PYSEC kimliğiyle raporlar, CVE/GHSA alias'tadır, ve aynı kaydı birden çok kez
yazabilir (#47'de pypi kaynağında setuptools iki kez, osv'de chromadb iki kez).
Eşleşme bu yüzden kimlik ∪ alias üzerinden yapılır ve bir paketteki kayıtlar
kimlik kümeleri kesişiyorsa tek bir bulguya katlanır. Birimler ayrı yazılır:
"kayit" ham girdi, "bulgu" tekil açık.

ÇIKTI. Hata ve özet GitHub annotation'ı olarak basılır (iş günlüğü oturum
istiyor, annotation'lar istemiyor). Bulgu dağılımı her koşuda bir notice olarak
yazılır: koşul (d) — hangi kayıt hangi paketten, hangi sürümle kapanır — her
koşuda yeniden ölçülür.

Ağsız ve bağımlılıksız: yalnız standart kütüphane (`tomllib` 3.11'de var).
Saf kısımlar `tests/test_pip_audit_gate.py`'de test ediliyor.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

# The editable install of this repo: pip-audit's pypi source skips it
# ("not found on PyPI"). It is the only package allowed to be skipped.
PROJECT = "defect-risk-analyzer"


class ReportError(Exception):
    """Rapor okunamıyor ya da tarama eksik: kapı bunu kırmızı sayar."""


@dataclass(frozen=True)
class Finding:
    """Bir paketteki tekil bir açık; mükerrer kayıtlar tek bulguya katlanmış."""

    package: str
    version: str
    ids: frozenset[str]
    fix_versions: tuple[str, ...]
    records: int

    @property
    def key(self) -> str:
        """İnsan için ad: CVE, yoksa GHSA, yoksa en küçük kimlik."""
        for prefix in ("CVE-", "GHSA-"):
            named = sorted(i for i in self.ids if i.startswith(prefix))
            if named:
                return named[0]
        return sorted(self.ids)[0]


@dataclass(frozen=True)
class Verdict:
    findings: tuple[Finding, ...]
    new: tuple[Finding, ...]
    stale: tuple[str, ...]
    records: int
    scanned: int

    @property
    def ok(self) -> bool:
        return not self.new and not self.stale


def _normalize(name: str) -> str:
    return name.lower().replace("_", "-").replace(".", "-")


def parse_report(text: str) -> tuple[list[dict], int]:
    """Raporu doğrula; (açık taşıyan paketler, taranan paket sayısı) döndür.

    Eksik ya da bozuk her durum `ReportError` fırlatır.
    """
    if not text.strip():
        raise ReportError("rapor bos")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReportError(f"rapor JSON degil ({exc})") from exc
    if not isinstance(data, dict) or not isinstance(data.get("dependencies"), list):
        raise ReportError("raporda `dependencies` listesi yok")
    deps = data["dependencies"]
    skipped = sorted(
        d.get("name", "?") for d in deps if "skip_reason" in d
    )
    foreign = [n for n in skipped if _normalize(n) != PROJECT]
    if foreign:
        raise ReportError(
            "tarama eksik: projeden baska atlanan paket(ler): " + ", ".join(foreign)
        )
    scanned = [d for d in deps if "skip_reason" not in d]
    if not scanned:
        raise ReportError("hic paket taranmamis")
    return [d for d in scanned if d.get("vulns")], len(scanned)


def _fold(package: str, version: str, vulns: list[dict]) -> list[Finding]:
    """Bir paketin kayıtlarını, kimlik kümeleri kesişenleri birleştirerek katla."""
    groups: list[tuple[set[str], set[str], int]] = []
    for vuln in vulns:
        ids = {vuln["id"], *vuln.get("aliases", [])}
        fixes = set(vuln.get("fix_versions", []))
        merged_ids, merged_fixes, count = ids, fixes, 1
        rest = []
        for g_ids, g_fixes, g_count in groups:
            if g_ids & merged_ids:
                merged_ids |= g_ids
                merged_fixes |= g_fixes
                count += g_count
            else:
                rest.append((g_ids, g_fixes, g_count))
        groups = [*rest, (merged_ids, merged_fixes, count)]
    return [
        Finding(package, version, frozenset(ids), tuple(sorted(fixes)), count)
        for ids, fixes, count in groups
    ]


def evaluate(report_text: str, ignored: list[str]) -> Verdict:
    """Raporu ignore listesiyle karşılaştır. Rapor bozuksa `ReportError`."""
    vulnerable, scanned = parse_report(report_text)
    findings: list[Finding] = []
    records = 0
    for dep in vulnerable:
        records += len(dep["vulns"])
        findings.extend(_fold(dep["name"], dep["version"], dep["vulns"]))
    findings.sort(key=lambda f: (f.package, f.key))
    ignored_set = set(ignored)
    new = tuple(f for f in findings if not f.ids & ignored_set)
    seen = set().union(*(f.ids for f in findings)) if findings else set()
    stale = tuple(sorted(ignored_set - seen))
    return Verdict(tuple(findings), new, stale, records, scanned)


def load_ignore(path: Path) -> list[str]:
    """`ignore = [...]` dizisini oku; her öğe bir CVE ya da GHSA kimliği."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    ids = data.get("ignore")
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise ValueError(f"{path}: `ignore` bir dize listesi olmali")
    return ids


def _escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "").replace("\n", "%0A")


def _annotate(level: str, title: str, lines: list[str]) -> None:
    # Titles are kept free of ':' and ',', which a workflow-command property
    # would need escaped; the message part only needs %, CR and LF escaped.
    print(f"::{level} title={_escape(title)}::{_escape(chr(10).join(lines))}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--ignore", type=Path, required=True)
    args = parser.parse_args(argv)

    ignored = load_ignore(args.ignore)
    if not args.report.is_file():
        _annotate("error", "pip-audit gate", [f"rapor yok: {args.report}"])
        return 1
    try:
        verdict = evaluate(args.report.read_text(encoding="utf-8"), ignored)
    except ReportError as exc:
        _annotate("error", "pip-audit gate", [str(exc)])
        return 1

    _annotate("notice", "pip-audit distribution", [
        f"taranan {verdict.scanned} paket; {verdict.records} kayit, "
        f"{len(verdict.findings)} tekil bulgu (kayit = ham girdi, bulgu = tekil acik)",
        *(
            f"{f.package}=={f.version} {f.key} kayit={f.records} "
            f"fix={','.join(f.fix_versions) or '(yok)'} ids={','.join(sorted(f.ids))}"
            for f in verdict.findings
        ),
    ])
    if verdict.new:
        _annotate("error", "pip-audit gate - yeni bulgu", [
            *(f"{f.package}=={f.version} {f.key} ids={','.join(sorted(f.ids))}"
              for f in verdict.new),
            "Ya bump edin, ya da kimligi ignore listesine ve gerekcesini "
            "docs/KNOWN-DEBT.md'ye ayni PR'da ekleyin.",
        ])
    if verdict.stale:
        _annotate("error", "pip-audit gate - bayat ignore", [
            *verdict.stale,
            "Bu kimlikler artik raporlanmiyor: .github/pip-audit-ignore.toml'dan "
            "silin, docs/KNOWN-DEBT.md'deki satiri kapatin.",
        ])
    return 0 if verdict.ok else 1


if __name__ == "__main__":
    sys.exit(main())
