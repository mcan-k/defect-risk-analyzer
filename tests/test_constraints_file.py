"""
`.github/constraints/ci-linux-py311.txt` üreticisinin yazdığı gibi kalmalı.

İDDİA (Faz 6D-3b-2a). Dosya CI'ın Linux kümesinin DOLAYLI paketlerini tutar,
`.github/scripts/constraints_generate.py` ile üretilir ve elle düzenlenmez.
Beş test, beş ayrı kırılma biçimi:

  * başlık üreticinin bugün yazacağı başlıkla aynı — elle düzenlenmiş bir
    başlık, ya da bir doğrudan pin eklenip/silinip yeniden üretilmemiş bir
    dosya kırmızı;
  * her satır `ad==sürüm`, ve küme boş değil (en az 100 satır; 2026-10-13'te
    121) — boş bir dosya ya da `-e`/URL satırı kırmızı;
  * doğrudan pin yok — tek doğruluk kaynakları `requirements*.txt`;
  * pip, setuptools, wheel yok — CI onları bilerek yükseltiyor;
  * Linux imzası: `uvloop` var, `colorama` ve `tzdata` yok (6D-3b-1'de ölçülen
    Windows/Linux farkı). Windows'ta üretilmiş bir dosya kırmızı.

BEYAN EDİLMİŞ KÖR NOKTA. Bu dosya sürümleri doğrulamaz: bir satırı başka bir
geçerli sürüme çevirmek burada yeşil kalır. Kurulan kümenin dosyaya eşit
olduğunu CI'daki eşitlik adımı tutar (6D-3b-2b). Ağsız; uv çağrılmaz.
"""

import importlib.util
import re
import sys
from pathlib import Path

# The repo, not the config sandbox — same reason as tests/test_pip_audit_gate.py.
REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / ".github" / "scripts" / "constraints_generate.py"

_spec = importlib.util.spec_from_file_location("constraints_generate", SCRIPT_PATH)
generate = importlib.util.module_from_spec(_spec)
sys.modules["constraints_generate"] = generate
_spec.loader.exec_module(generate)

CONSTRAINTS = REPO_ROOT / generate.OUTPUT
_LINE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9._+!-]+)$")
_DATE = re.compile(r"^# Tarih \(UTC\): (\d{4}-\d{2}-\d{2})$")


def _lines() -> list[str]:
    return CONSTRAINTS.read_text(encoding="ascii").splitlines()


def _pins() -> dict[str, str]:
    pins = {}
    for line in _lines():
        if line and not line.startswith("#"):
            match = _LINE.match(line)
            assert match, f"tanimsiz satir: {line!r} (yalniz ad==surum olmali)"
            pins[generate.normalize(match.group(1))] = match.group(2)
    return pins


def test_header_is_what_the_generator_writes_today():
    lines = _lines()
    dates = [m.group(1) for m in map(_DATE.match, lines) if m]
    assert len(dates) == 1, "baslikta tek bir 'Tarih (UTC)' satiri olmali"
    expected = generate.render_header(dates[0], generate.direct_pins(REPO_ROOT))
    assert lines[: len(expected)] == expected, (
        "Kisit dosyasinin basligi uretecinin bugun yazacagi basliktan farkli. Dosya "
        "elle duzenlenmez: python .github/scripts/constraints_generate.py --uv <uv>"
    )


def test_every_line_is_a_pin_and_the_set_is_not_empty():
    pins = _pins()
    assert len(pins) >= 100, (
        f"kisit dosyasinda yalniz {len(pins)} paket var; 2026-10-13'te 121'di. "
        "Bos ya da kesilmis bir dosya hicbir seyi kisitlamaz."
    )


def test_no_direct_pin_is_repeated_here():
    repeated = sorted(set(_pins()) & set(generate.direct_pins(REPO_ROOT)))
    assert not repeated, (
        f"dogrudan pinler kisit dosyasinda da var: {repeated}. Tek dogruluk kaynaklari "
        "requirements*.txt; uretec onlari --no-emit-package ile disarida birakir."
    )


def test_installer_trio_is_left_out():
    present = sorted(set(_pins()) & {"pip", "setuptools", "wheel"})
    assert not present, (
        f"{present} kisit dosyasinda. CI onlari --upgrade pip setuptools ile bilerek "
        "yukseltiyor; kisitlanirlarsa o adim kisitla catisir."
    )


def test_file_was_generated_for_linux():
    pins = _pins()
    assert "uvloop" in pins, "uvloop yok: dosya Linux icin uretilmemis olabilir"
    windows_only = sorted({"colorama", "tzdata"} & set(pins))
    assert not windows_only, (
        f"{windows_only} yalniz Windows'ta kuruluyor (6D-3b-1'de olculdu): dosya "
        "Windows hedefiyle uretilmis gorunuyor. Uretec --python-platform "
        "x86_64-manylinux_2_39 ile kosmali."
    )
