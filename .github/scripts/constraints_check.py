"""
CI kısıt eşitlik kontrolü: kurulan küme = kısıt dosyası ∪ doğrudan pinler.

İDDİA (Faz 6D-3b-2b). CI `requirements-dev.txt`'i
`-c .github/constraints/ci-linux-py311.txt` ile kuruyor. `-c` bir paketi
kurdurmaz, yalnız kurulursa sürümünü sabitler; dosyanın kurulan kümeyi
gerçekten tuttuğunu tek başına göstermez. Bu betik `pip freeze` çıktısını iki
yönde karşılaştırır:

  * **kısıtsız kurulan** — kurulu, ama ne kısıt dosyasında ne doğrudan pin:
    bir bump yeni bir dolaylı paket getirmiş;
  * **kurulmayan kısıt** — dosyada, ama kurulu değil: bir bump bir dolaylı
    paketi düşürmüş, satır bayat;
  * **sürüm farkı** — dosyadaki sürüm kurulmamış (`-c` altında olmamalı;
    olursa dosya ile kurulum ayrışmıştır);
  * **doğrudan pin uyuşmuyor** — `requirements*.txt`'teki `==` sürüm kurulu
    değil.

pip, setuptools ve wheel karşılaştırmaya girmez: CI onları bilerek
yükseltiyor ve kısıt dosyası onları bilerek dışarıda bırakıyor (üretecin
docstring'i). `-e` satırı (projenin kendisi) ve yorumlar da girmez; pip,
uzak deposu olmayan bir git kopyasında `# Editable Git install with no
remote (...)` diye bir yorum satırı yazıyor (2026-10-12'de kendi sayımımızı
şaşırtan satır).

Bekçinin bekçisi: freeze yoksa, boşsa ya da tanımsız bir satır taşıyorsa
kontrol yeşil GEÇMEZ. Boş bir karşılaştırma iyi haber değil, bozuk ölçümdür —
pip-audit kapısının ilkesi.

ÇIKTI. Sonuç GitHub annotation'ı olarak basılır, pip-audit kapısı gibi: eşitse
bir notice (sayılarla), değilse farkları adlarıyla sayan bir error.

Ağsız ve bağımlılıksız: yalnız standart kütüphane. Saf kısımlar
`tests/test_constraints_check.py`'de test ediliyor.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DIRECT_FILES = ("requirements.txt", "requirements-dev.txt")
INSTALLER_TRIO = frozenset({"pip", "setuptools", "wheel"})

# Kısıt dosyası ve freeze: her veri satırı tam olarak `ad==sürüm`.
_STRICT = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;#]+)$")
# requirements*.txt: üretecin kuralı — `==` satırları doğrudan pindir, yorum ve
# `-r` satırları eşleşmez.
_DIRECT = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*([^\s;#]+)")


class CheckError(Exception):
    """Girdi okunamıyor ya da boş: kontrol bunu kırmızı sayar."""


@dataclass(frozen=True)
class Verdict:
    installed: int
    constrained: int
    direct: int
    unconstrained: tuple[str, ...]
    not_installed: tuple[str, ...]
    version_diffs: tuple[str, ...]
    direct_diffs: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not (
            self.unconstrained
            or self.not_installed
            or self.version_diffs
            or self.direct_diffs
        )


def normalize(name: str) -> str:
    """PEP 503 adı: `PyYAML` ve `pyyaml`, `pip_api` ve `pip-api` aynı paket."""
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_pins(text: str) -> dict[str, str]:
    """`ad==sürüm` satırları; yorum, boş ve `-e` satırları atlanır.

    pip, setuptools ve wheel atlanır. Tanımsız bir satır sessizce geçmez.
    """
    pins: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-e"):
            continue
        match = _STRICT.match(line)
        if not match:
            raise CheckError(f"tanimsiz satir: {raw!r} (yalniz ad==surum olmali)")
        name = normalize(match.group(1))
        if name not in INSTALLER_TRIO:
            pins[name] = match.group(2)
    return pins


def parse_freeze(text: str) -> dict[str, str]:
    """`pip freeze` çıktısı; boşsa `CheckError`."""
    installed = parse_pins(text)
    if not installed:
        raise CheckError("freeze bos: karsilastirilacak kurulu paket yok")
    return installed


def direct_pins(root: Path) -> dict[str, str]:
    """CI'ın kurduğu iki requirements dosyasındaki `==` pinler."""
    pins: dict[str, str] = {}
    for filename in DIRECT_FILES:
        for line in (root / filename).read_text(encoding="utf-8").splitlines():
            match = _DIRECT.match(line.strip())
            if match:
                pins[normalize(match.group(1))] = match.group(2)
    return pins


def compare(
    installed: dict[str, str],
    constraints: dict[str, str],
    directs: dict[str, str],
) -> Verdict:
    """Kurulu kümeyi kısıt dosyası ∪ doğrudan pinlerle iki yönde karşılaştır."""
    expected = set(constraints) | set(directs)
    both = sorted(set(constraints) & set(installed))
    return Verdict(
        installed=len(installed),
        constrained=len(constraints),
        direct=len(directs),
        unconstrained=tuple(sorted(set(installed) - expected)),
        not_installed=tuple(sorted(set(constraints) - set(installed))),
        version_diffs=tuple(
            f"{name}: kisit {constraints[name]}, kurulu {installed[name]}"
            for name in both
            if constraints[name] != installed[name]
        ),
        direct_diffs=tuple(
            f"{name}: requirements {version}, kurulu {installed.get(name, 'yok')}"
            for name, version in sorted(directs.items())
            if installed.get(name) != version
        ),
    )


def _escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "").replace("\n", "%0A")


def _annotate(level: str, title: str, lines: list[str]) -> None:
    # Same rule as the pip-audit gate: the title stays free of ':' and ','.
    print(f"::{level} title={_escape(title)}::{_escape(chr(10).join(lines))}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--constraints", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        if not args.freeze.is_file():
            raise CheckError(f"freeze dosyasi yok: {args.freeze}")
        installed = parse_freeze(args.freeze.read_text(encoding="utf-8"))
        constraints = parse_pins(args.constraints.read_text(encoding="utf-8"))
    except CheckError as exc:
        _annotate("error", "constraints check", [str(exc)])
        return 1
    verdict = compare(installed, constraints, direct_pins(REPO_ROOT))

    if verdict.ok:
        _annotate("notice", "constraints check", [
            f"ESIT - kurulu {verdict.installed} paket = {verdict.constrained} "
            f"kisit + {verdict.direct} dogrudan (pip, setuptools, wheel ve -e haric)"
        ])
        return 0
    _annotate("error", "constraints check", [
        f"FARKLI - kurulu {verdict.installed} paket; {verdict.constrained} "
        f"kisit + {verdict.direct} dogrudan bekleniyordu",
        *(f"kisitsiz kurulan: {name}" for name in verdict.unconstrained),
        *(f"kurulmayan kisit: {name}" for name in verdict.not_installed),
        *(f"surum farki: {line}" for line in verdict.version_diffs),
        *(f"dogrudan pin uyusmuyor: {line}" for line in verdict.direct_diffs),
        "Kisit dosyasi yeniden uretilir, elle duzenlenmez: CONTRIBUTING.md, "
        "'Bagimlilik kisitlari'.",
    ])
    return 1


if __name__ == "__main__":
    sys.exit(main())
