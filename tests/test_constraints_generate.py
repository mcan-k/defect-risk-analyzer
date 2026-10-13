"""
`.github/scripts/constraints_generate.py`'nin ağsız kısımları.

İDDİA. Kısıt dosyası yalnız dolaylı paketleri tutar ve 6D-3b-1'de ölçülen
üreticiyle (uv 0.12.19, `x86_64-manylinux_2_39`, Python 3.11) üretilir. Bunu
betikte üç şey sağlıyor ve her biri burada ayrı tutuluyor:

  * komut her doğrudan pini ve pip/setuptools/wheel'i `--no-emit-package`
    olarak taşıyor — doğrudan adlar bugünkü requirements dosyalarından
    okunuyor, yani bir pin eklenince komut da kendiliğinden değişiyor;
  * başlık yeniden üretim tarifini ve "elle düzenlenmez" uyarısını taşıyor;
  * sürüm kapısı başka bir uv ile çalışmayı reddediyor.

uv burada hiç çağrılmıyor: depoda ağ testi yok, ve uv CI'ın kurduğu kümede
değil. Gerçek üretimin sonucunu `tests/test_constraints_file.py` tutuyor.

BOŞUNA GEÇMEME. Doğrudan ad sayısı en az 13 olmalı (2026-10-13'te
requirements.txt 9 + requirements-dev.txt 4). Desen hiçbir satırı yakalamazsa
"her doğrudan ad dışlanmış" iddiası boş bir küme üzerinde doğru çıkardı.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

# The repo, not the config sandbox — same reason as tests/test_pip_audit_gate.py.
REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / ".github" / "scripts" / "constraints_generate.py"

# A CI script, not part of the package, so it is loaded by path.
_spec = importlib.util.spec_from_file_location("constraints_generate", SCRIPT_PATH)
generate = importlib.util.module_from_spec(_spec)
sys.modules["constraints_generate"] = generate
_spec.loader.exec_module(generate)


def _emitted_exclusions(command: list[str]) -> set[str]:
    return {
        command[i + 1] for i, part in enumerate(command) if part == "--no-emit-package"
    }


def test_command_excludes_every_direct_pin_and_the_installer_trio():
    directs = generate.direct_pins(REPO_ROOT)
    assert len(directs) >= 13, (
        f"requirements.txt + requirements-dev.txt'te yalniz {len(directs)} dogrudan pin "
        "bulundu; desen satirlari yakalamiyor olabilir."
    )

    command = generate.build_command("uv", directs)
    assert command[:4] == ["uv", "pip", "compile", "requirements-dev.txt"]
    assert _emitted_exclusions(command) == {*directs, "pip", "setuptools", "wheel"}
    for flag, value in [("--python-platform", "x86_64-manylinux_2_39"),
                        ("--python-version", "3.11")]:
        assert command[command.index(flag) + 1] == value
    for flag in ("--no-header", "--no-annotate", "--no-config"):
        assert flag in command
    assert "--upgrade" not in command, "bayraksiz uretim surumleri degistirmemeli"

    one = generate.build_command("uv", directs, upgrade_packages=("urllib3",))
    assert one[one.index("--upgrade-package") + 1] == "urllib3"
    assert "--upgrade" not in one


def test_header_carries_the_recipe_and_the_not_editable_mark():
    directs = generate.direct_pins(REPO_ROOT)
    header = generate.render_header("2026-10-13", directs)
    text = "\n".join(header)

    assert "ELLE DUZENLENMEZ" in header[1]
    assert "python .github/scripts/constraints_generate.py" in text
    assert "uv 0.12.19, hedef x86_64-manylinux_2_39, --python-version 3.11" in text
    assert "Tarih (UTC): 2026-10-13" in text
    for name in directs:
        assert f"--no-emit-package {name}" in text
    assert all(line.startswith("#") for line in header)
    assert text.isascii(), "baslik ASCII olmali (modul docstring'i: cp1254)"


def test_version_gate_refuses_any_other_uv():
    assert generate.check_uv_version("uv 0.12.19 (bea1384 2026-09-24)") == "0.12.19"
    for output in ("uv 0.12.20 (abc1234 2026-09-30)", "uv 0.13.0", "", "pip 26.2.1"):
        with pytest.raises(SystemExit, match="uv 0.12.19 gerekli"):
            generate.check_uv_version(output)
