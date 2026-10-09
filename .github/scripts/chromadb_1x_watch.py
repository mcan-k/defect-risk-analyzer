"""
chromadb 1.x izleyicisi: dependabot.yml'deki `chromadb >=1.0.0` ertelemesi hâlâ haklı mı?

NEDEN. Her 1.x sürümü CVE-2026-45829'u (GHSA-f4j7-r4q5-qw2c, PYSEC-2026-311)
taşıyor ve düzeltmesi yok; ertelemenin tek gerekçesi bu. Bu betik haftalık
`chromadb-1x-watch.yml` iş akışının kararını verir (Faz 6D-4d-3).

İKİ TARAMA, ÇÜNKÜ BOŞ SONUÇ İYİ HABER DEĞİL.

  * **Kontrol** — `chromadb==CONTROL_VERSION`, 45829'un kesin raporlandığı
    sürüm. Kontrol 45829'u raporlamıyorsa bozuk olan chromadb değil, tarayıcı
    ya da verisidir. Pozitif kontrol budur.
  * **Hedef** — `chromadb>=1.0.0`, yani en yeni 1.x. Soru: hâlâ taşıyor mu?

Öteki üç chromadb kaydı (45830, 45833, 45831) bilerek koşul DEĞİL. Dört
advisory'nin dördü de kapalı aralıklı, `last_affected: 1.5.9` (OSV,
2026-10-07); yeni bir 1.x sürümünde dördü birden görünmeyebilir ve "öteki üçü
hâlâ raporlanıyor" şartı tam beklenen olayı sessizliğe çevirirdi (kullanıcı
kararı K6). Üçü yalnız dağılım notice'inde yazılır.

DURUMLAR — yalnız biri yeşil (kullanıcı kararı K1: GitHub yalnız başarısız
zamanlanmış koşuyu bildirir, sessiz bir bozukluk alarmın yokluğudur):

  * **erteleme haklı** (çıkış 0) — kontrol geçerli, sürümü `CONTROL_VERSION`,
    45829 var; hedef geçerli, chromadb ≥1.0.0 ve 45829 var.
  * **iş var** (çıkış 1) — kontrol sağlam; hedef ≥1.0.0 ve 45829 YOK.
    dependabot.yml'deki girdi silinir, 6D-5 başlar.
  * **izleyici bozuk** (çıkış 2) — raporlardan biri yok, boş, JSON değil ya
    da eksik tarama (kapının `ReportError`'ı); bir raporda chromadb yok ya da
    atlanmış; kontrolün sürümü yanlış ya da 45829'u taşımıyor; hedefin
    sürümü ayrıştırılamıyor ya da <1.0.0 (pip `>=1.0.0`'ı 0.x'e çözemez — rapor
    bunu diyorsa okuma ya da çözümleme bozuktur, ve 0.6.3'ün verisi "iş var"
    desenini verirdi); değerlendirmede beklenmedik bir istisna. Bütün
    nedenler tek mesajda yazılır.

KONTROL SÜRÜMÜ yalnız burada tanımlı; iş akışı requirements dosyalarını
`write-requirements` ile bu betiğe yazdırır. PyPI'den yank edilirse `==` ile
sabitlenmiş sürüm yine kurulur (PEP 592). Silinirse ya da 45829'un advisory'si
1.5.9'u dışlayacak biçimde değişirse kontrol düşer ve izleyici kendi başlığıyla
kırmızı verir: o zaman sabit, 45829'u taşıyan başka bir sürüme taşınır
([1.0.0, 1.5.9] aralığı).

KAPIYA BAĞLILIK. Rapor doğrulaması, mükerrer kayıtların alias üzerinden
katlanması ve annotation biçimi `pip_audit_gate.py`'den DEĞİŞTİRİLMEDEN import
edilir (kullanıcı kararı K3 A), alt çizgili yardımcılar dahil. Aynı istisna iki
yerde ters anlam taşır: kapıda `ReportError` kırmızı bir kapı, burada "izleyici
bozuk". `parse_report` açığı olmayan paketleri döndürmediği için chromadb'nin
sürümü JSON'dan ayrıca okunur. Kapıdaki bir değişiklik bu betiği de değiştirir;
iş akışının `paths:` filtresi bu yüzden kapıyı da içerir.

Ağsız ve kapı dışında bağımlılıksız. Saf kısımlar
`tests/test_chromadb_1x_watch.py`'de test ediliyor.
"""

from __future__ import annotations

import argparse
import enum
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from pip_audit_gate import Finding, ReportError, _annotate, _fold, _normalize, parse_report

PACKAGE = "chromadb"
# The one place the control version lives; see the docstring before moving it.
CONTROL_VERSION = "1.5.9"
TARGET_SPEC = "chromadb>=1.0.0"
# Matched against every id and alias, so the GHSA and PYSEC records count too.
SENTINEL = "CVE-2026-45829"
NOTICE_ONLY = ("CVE-2026-45830", "CVE-2026-45833", "CVE-2026-45831")
# Titles stay ASCII and free of ':' and ',' (same rule as the gate).
TITLE = "chromadb 1x izleyici"

_MAJOR = re.compile(r"^(\d+)\.")


class State(enum.Enum):
    """Değer çıkış kodudur."""

    JUSTIFIED = 0
    WORK = 1
    BROKEN = 2


TITLES = {
    State.JUSTIFIED: f"{TITLE} - erteleme hakli",
    State.WORK: f"{TITLE} - is var",
    State.BROKEN: f"{TITLE} - izleyici bozuk",
}
DISTRIBUTION_TITLE = f"{TITLE} - dagilim"


@dataclass(frozen=True)
class Scan:
    """Bir raporda chromadb: sürümü ve tekil bulguları."""

    version: str
    findings: tuple[Finding, ...]
    other_vulnerable: int

    @property
    def has_sentinel(self) -> bool:
        return any(SENTINEL in f.ids for f in self.findings)


@dataclass(frozen=True)
class Result:
    state: State
    reasons: tuple[str, ...]
    control: Scan | None
    target: Scan | None


def requirement_files() -> dict[str, str]:
    """İş akışının `$RUNNER_TEMP`'e yazdığı iki requirements dosyası."""
    return {
        "control": f"{PACKAGE}=={CONTROL_VERSION}\n",
        "target": f"{TARGET_SPEC}\n",
    }


def major(version: str) -> int | None:
    """Ana sürüm numarası; ayrıştırılamıyorsa None."""
    match = _MAJOR.match(version)
    return int(match.group(1)) if match else None


def read_scan(text: str | None, label: str) -> Scan:
    """Raporu doğrula ve chromadb'yi çıkar. Bozuk ya da eksikse `ReportError`.

    `text` None ise rapor dosyası yok demektir.
    """
    if text is None:
        raise ReportError(f"{label}: rapor yok")
    try:
        vulnerable, _ = parse_report(text)
    except ReportError as exc:
        raise ReportError(f"{label}: {exc}") from exc
    # parse_report drops packages without vulns, so the version is read here.
    deps = json.loads(text)["dependencies"]
    entries = [d for d in deps if _normalize(d.get("name", "")) == PACKAGE]
    if len(entries) != 1 or "version" not in entries[0]:
        raise ReportError(f"{label}: raporda {PACKAGE} yok")
    version = entries[0]["version"]
    findings: list[Finding] = []
    others = 0
    for dep in vulnerable:
        if _normalize(dep["name"]) == PACKAGE:
            findings.extend(_fold(dep["name"], dep["version"], dep["vulns"]))
        else:
            others += 1
    findings.sort(key=lambda f: f.key)
    return Scan(version, tuple(findings), others)


def classify(control_text: str | None, target_text: str | None) -> Result:
    """İki raporu tek bir duruma indir. Saf; bütün bozukluk nedenlerini toplar."""
    reasons: list[str] = []

    control: Scan | None = None
    try:
        control = read_scan(control_text, "kontrol")
    except ReportError as exc:
        reasons.append(str(exc))
    if control is not None:
        if control.version != CONTROL_VERSION:
            reasons.append(
                f"kontrol: {PACKAGE} {control.version} cozulmus, "
                f"beklenen {CONTROL_VERSION}"
            )
        if not control.has_sentinel:
            reasons.append(
                f"kontrol: {PACKAGE}=={control.version} {SENTINEL} raporlamiyor "
                "(pozitif kontrol dustu - tarayici ya da verisi bozuk)"
            )

    target: Scan | None = None
    try:
        target = read_scan(target_text, "hedef")
    except ReportError as exc:
        reasons.append(str(exc))
    if target is not None:
        target_major = major(target.version)
        if target_major is None:
            reasons.append(f"hedef: {PACKAGE} surumu ayristirilamiyor: {target.version!r}")
        elif target_major < 1:
            reasons.append(
                f"hedef: {TARGET_SPEC} {target.version} olarak cozulmus "
                "(pip bunu yapamaz - okuma ya da cozumleme bozuk)"
            )

    if reasons:
        return Result(State.BROKEN, tuple(reasons), control, target)
    if target.has_sentinel:
        return Result(State.JUSTIFIED, (), control, target)
    return Result(State.WORK, (), control, target)


def _scan_lines(label: str, scan: Scan | None) -> list[str]:
    if scan is None:
        return [f"{label}: okunamadi"]
    lines = [
        f"{label}: {PACKAGE}=={scan.version}, {len(scan.findings)} tekil bulgu, "
        f"{SENTINEL} {'var' if scan.has_sentinel else 'YOK'}; "
        f"{PACKAGE} disinda acik tasiyan paket: {scan.other_vulnerable}"
    ]
    lines += [
        f"  {f.key} kayit={f.records} fix={','.join(f.fix_versions) or '(yok)'} "
        f"ids={','.join(sorted(f.ids))}"
        for f in scan.findings
    ]
    seen = set().union(*(f.ids for f in scan.findings)) if scan.findings else set()
    lines.append(
        "  kosul olmayan uc kayit: "
        + ", ".join(f"{i} {'var' if i in seen else 'yok'}" for i in NOTICE_ONLY)
    )
    return lines


def _verdict_lines(result: Result) -> list[str]:
    if result.state is State.BROKEN:
        return [
            *result.reasons,
            "Izleyici olcemiyor; bu chromadb hakkinda bir karar degil, bir ariza.",
        ]
    target = result.target
    if result.state is State.JUSTIFIED:
        return [
            f"{PACKAGE}=={target.version} hala {SENTINEL} tasiyor; "
            "dependabot.yml'deki >=1.0.0 ertelemesi hakli."
        ]
    return [
        f"{PACKAGE}=={target.version} artik {SENTINEL} raporlamiyor ve kontrol "
        f"({PACKAGE}=={CONTROL_VERSION}) hala raporluyor.",
        "dependabot.yml'deki chromadb ignore girdisini silin ve 6D-5'i baslatin; "
        "docs/KNOWN-DEBT.md'deki 1.x satirini kapatin.",
    ]


def _read(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.is_file() else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    sub = parser.add_subparsers(dest="command", required=True)
    write = sub.add_parser("write-requirements")
    write.add_argument("directory", type=Path)
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--control", type=Path, required=True)
    evaluate.add_argument("--target", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "write-requirements":
        for name, content in requirement_files().items():
            (args.directory / f"chromadb-{name}.txt").write_text(content, encoding="utf-8")
        return 0

    # Any crash must read as "broken" (2). Uncaught, Python would exit 1, which
    # is the code for "work to do".
    try:
        result = classify(_read(args.control), _read(args.target))
    except Exception as exc:
        _annotate("error", TITLES[State.BROKEN], [f"beklenmedik hata: {exc!r}"])
        return State.BROKEN.value
    _annotate("notice", DISTRIBUTION_TITLE, [
        *_scan_lines("kontrol", result.control),
        *_scan_lines("hedef", result.target),
    ])
    level = "notice" if result.state is State.JUSTIFIED else "error"
    _annotate(level, TITLES[result.state], _verdict_lines(result))
    return result.state.value


if __name__ == "__main__":
    sys.exit(main())
