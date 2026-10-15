"""
CI kısıt dosyasının üreticisi: `.github/constraints/ci-linux-py311.txt`.

NE YAZAR (Faz 6D-3b-2a, kullanıcı kararları 2026-10-11/12). CI'ın
(ubuntu-24.04, Python 3.11) `requirements-dev.txt`'ten çözdüğü DOLAYLI
paketlerin tam sürümleri. İki şey bilerek dışarıda:

  * doğrudan pinler — tek doğruluk kaynakları `requirements*.txt`; aynı pin
    iki yerde yazılırsa bir bump ikisinden birini bayat bırakır;
  * pip, setuptools, wheel — CI onları `--upgrade pip setuptools` ile bilerek
    yükseltiyor (KNOWN-DEBT, 6D-4d-2'nin setuptools satırı).

Dışlama uv'nin kendi bayrağıyla yapılır (`--no-emit-package`; paketin
bağımlılıkları çözümde kalır), doğrudan adlar her koşuda requirements
dosyalarından okunur. Elle tutulan bir ad listesi bir bump'ta senkronu
kaybederdi.

NEDEN uv, NEDEN BU SÜRÜM. 6D-3b-1'de (taslak PR #56, 2026-10-12) ölçüldü: uv
0.12.19'un `--python-platform x86_64-manylinux_2_39 --python-version 3.11`
çıktısı CI'ın kendi `pip freeze`'ine ad ve sürümce birebir eşitti (134 paket),
26.04'te de eşitti, ve aynı komut windows-2025'ten koşunca aynı çıktıyı verdi.
Başka bir uv başka bir çözüm üretebilir; betik bu yüzden başka bir sürümle
çalışmayı reddeder. uv `requirements-dev.txt`'e girmez: CI'ın ona ihtiyacı
yok, girerse Dependabot onu yükseltmeye çalışır ve pip-audit onu da tarar.

KULLANIM — depo kökünde; uv depo dışında geçici bir venv'e kurulur:

    python -m venv <gecici>/uvenv
    <gecici>/uvenv/Scripts/python -m pip install uv==0.12.19
    python .github/scripts/constraints_generate.py --uv <gecici>/uvenv/Scripts/uv

    --upgrade                    tam tazeleme (her sürümden önce)
    --upgrade-package <paket>    yalnız o paket (dolaylı pakette güvenlik bulgusu)

Mevcut dosya uv'ye tercih olarak verilir (`-o`): bayraksız bir yeniden üretim
gerekmedikçe hiçbir sürümü değiştirmez, ve aynı gün iki kez koşulursa bayt
bayt aynı dosyayı yazar.

BAŞLIK ASCII. pip bir kısıt dosyasını Windows'ta yerel kod sayfasıyla
okuyabiliyor; Türkçe harfler 6D-3a'da görülen cp1254 hatasını tekrarlayabilir.

Ağsız kısımlar (komut, başlık, sürüm kapısı) saf fonksiyonlardır ve
`tests/test_constraints_generate.py`'de test ediliyor; dosyanın kendisini
`tests/test_constraints_file.py` tutuyor.
"""

from __future__ import annotations

import argparse
import datetime
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(".github") / "constraints" / "ci-linux-py311.txt"
SCRIPT = ".github/scripts/constraints_generate.py"
INPUT = "requirements-dev.txt"
DIRECT_FILES = ("requirements.txt", "requirements-dev.txt")

UV_VERSION = "0.12.19"
TARGET = "x86_64-manylinux_2_39"
PYTHON_VERSION = "3.11"
INSTALLER_TRIO = ("pip", "setuptools", "wheel")

NOT_EDITABLE = "ELLE DUZENLENMEZ"
# CONTRIBUTING.md'deki "Bağımlılık kısıtları" bölümü, başlıkta ASCII adıyla.
# Kırmızı bir Dependabot PR'ında ne yapılacağı orada yazılı (6D-3b-2c).
CONTRIBUTING_SECTION = "Bagimlilik kisitlari"

# `ad==sürüm` satırı; yorum ve `-r` satırları eşleşmez.
_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*([^\s;#]+)")
_UV_VERSION_LINE = re.compile(r"^uv (\S+)")


def normalize(name: str) -> str:
    """PEP 503 adı: `PyYAML` ve `pyyaml`, `pip_api` ve `pip-api` aynı paket."""
    return re.sub(r"[-_.]+", "-", name).lower()


def direct_pins(root: Path) -> list[str]:
    """CI'ın kurduğu iki requirements dosyasındaki `==` pinlerin adları."""
    names: set[str] = set()
    for filename in DIRECT_FILES:
        for line in (root / filename).read_text(encoding="utf-8").splitlines():
            match = _PIN.match(line.strip())
            if match:
                names.add(normalize(match.group(1)))
    return sorted(names)


def build_command(
    uv: str,
    directs: list[str],
    upgrade: bool = False,
    upgrade_packages: tuple[str, ...] = (),
) -> list[str]:
    """uv pip compile komutu; `-o` çağıran tarafından eklenir."""
    command = [
        uv, "pip", "compile", INPUT,
        "--python-platform", TARGET,
        "--python-version", PYTHON_VERSION,
        "--no-config", "--no-header", "--no-annotate", "--quiet",
    ]
    for name in sorted({*directs, *INSTALLER_TRIO}):
        command += ["--no-emit-package", name]
    if upgrade:
        command.append("--upgrade")
    for package in upgrade_packages:
        command += ["--upgrade-package", package]
    return command


def check_uv_version(text: str) -> str:
    """`uv --version` çıktısı sabit sürüm değilse SystemExit."""
    match = _UV_VERSION_LINE.match(text.strip())
    if not match or match.group(1) != UV_VERSION:
        raise SystemExit(
            f"uv {UV_VERSION} gerekli, bulunan: {text.strip()!r}. Kisit dosyasi "
            "6D-3b-1'de olculen surumle uretilir; baska bir surum baska bir "
            "cozum uretebilir."
        )
    return match.group(1)


def render_header(date: str, directs: list[str]) -> list[str]:
    """Dosyanın başlığı: yeniden üretim tarifi, sürüm ve tarih (ASCII)."""
    command = build_command("uv", directs)
    lines = [
        "# " + "=" * 77,
        f"# CI kisit dosyasi -- {NOT_EDITABLE}",
        "# " + "=" * 77,
        f"# Ureten: python {SCRIPT} --uv <uv>",
        f"# uv {UV_VERSION}, hedef {TARGET}, --python-version {PYTHON_VERSION}",
        f"# Tarih (UTC): {date}",
        "# Komut:",
        f"#   {' '.join(command[:4])}",
    ]
    options = command[4:]
    index = 0
    while index < len(options):
        flag = options[index]
        if index + 1 < len(options) and not options[index + 1].startswith("--"):
            lines.append(f"#     {flag} {options[index + 1]}")
            index += 2
        else:
            lines.append(f"#     {flag}")
            index += 1
    lines += [
        "# Icerik: yalniz dolayli paketler. Dogrudan pinler requirements*.txt'te;",
        "# pip, setuptools ve wheel disarida (CI onlari bilerek yukseltiyor).",
        "# Yalniz CI icindir (ubuntu-24.04, Python 3.11); yerel kurulumda kullanilmaz.",
        "# Dependabot PR'i kirmizi gelirse ve yeniden uretim icin: CONTRIBUTING.md,",
        f"# '{CONTRIBUTING_SECTION}' bolumu.",
        "# " + "=" * 77,
    ]
    return lines


def parse_pins(text: str) -> list[str]:
    """uv çıktısının satırları; tanımsız bir satır sessizce geçmez."""
    pins = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not _PIN.match(line) or "@" in line or ";" in line:
            raise SystemExit(f"uv ciktisinda tanimsiz satir: {raw!r}")
        pins.append(line)
    return pins


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--uv", default="uv", help="uv calistirilabilirinin yolu")
    parser.add_argument("--upgrade", action="store_true")
    parser.add_argument("--upgrade-package", action="append", default=[])
    args = parser.parse_args(argv)

    version = subprocess.run(
        [args.uv, "--version"], capture_output=True, text=True, check=True
    ).stdout
    check_uv_version(version)

    directs = direct_pins(REPO_ROOT)
    command = build_command(
        args.uv, directs, args.upgrade, tuple(args.upgrade_package)
    )
    target = REPO_ROOT / OUTPUT
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.txt"
        if target.exists():
            shutil.copyfile(target, out)
        subprocess.run([*command, "-o", str(out)], cwd=REPO_ROOT, check=True)
        pins = parse_pins(out.read_text(encoding="utf-8"))

    date = datetime.datetime.now(datetime.UTC).date().isoformat()
    target.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join([*render_header(date, directs), *pins]) + "\n"
    target.write_bytes(body.encode("ascii"))
    print(f"{OUTPUT}: {len(pins)} paket", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
