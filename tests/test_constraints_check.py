"""
CI kısıt eşitlik kontrolü (`.github/scripts/constraints_check.py`).

İDDİA (Faz 6D-3b-2b). CI'da kurulan küme = kısıt dosyası ∪ doğrudan pinler,
iki yönde. Sekiz test, sekiz ayrı kırılma biçimi:

  * eşit küme geçer ve sonucu sayılarla söyler — gerçek kısıt dosyası ve
    gerçek requirements dosyalarından kurulmuş bir freeze ile, CI'daki
    komutun kendisi (`main`) üzerinden;
  * kısıtsız kurulan paket kırmızı (bir bump yeni bir dolaylı getirdi);
  * kurulmayan kısıt kırmızı (bir bump bir dolaylıyı düşürdü, satır bayat);
  * sürüm farkı kırmızı;
  * doğrudan pin uyuşmuyor ya da hiç kurulmamış — kırmızı;
  * okunamayan freeze kırmızı: boş, yalnız yorum, tanımsız satır;
  * `-e`, yorumlar (2026-10-12'de sayımımızı şaşırtan `# Editable Git
    install with no remote` dahil) ve pip/setuptools/wheel yok sayılır;
  * adlar PEP 503'e göre normalleşir (`PyYAML` = `pyyaml`).

Ağsız; pip çağrılmaz. Gerçek kurulumla karşılaştırma CI'ın işi; burada
kararı veren mantık sınanıyor. Windows'taki pozitif kontrol (kısıtsız
{colorama, tzdata}, kurulmayan {uvloop}) PR gövdesinde.
"""

import importlib.util
import re
import sys
from pathlib import Path

import pytest

# The repo, not the config sandbox — same reason as tests/test_pip_audit_gate.py.
REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / ".github" / "scripts" / "constraints_check.py"
CONSTRAINTS = REPO_ROOT / ".github" / "constraints" / "ci-linux-py311.txt"

# A CI script, not part of the package, so it is loaded by path. It must be in
# sys.modules before exec: dataclasses looks its module up there.
_spec = importlib.util.spec_from_file_location("constraints_check", SCRIPT_PATH)
check = importlib.util.module_from_spec(_spec)
sys.modules["constraints_check"] = check
_spec.loader.exec_module(check)

_NOTICE = re.compile(
    r"^::notice title=constraints check::ESIT - kurulu (\d+) paket = "
    r"(\d+) kisit \+ (\d+) dogrudan \(pip, setuptools, wheel ve -e haric\)$"
)

CONSTRAINED = {"certifi": "2026.9.15", "uvloop": "0.22.1"}
DIRECT = {"openai": "3.26.1", "pytest": "9.1.1"}


def test_equal_sets_pass_and_say_so(tmp_path, capsys):
    """Gerçek dosyalardan kurulmuş bir freeze: rc 0 ve tek bir notice satırı."""
    constraints = check.parse_pins(CONSTRAINTS.read_text(encoding="utf-8"))
    directs = check.direct_pins(REPO_ROOT)
    freeze = tmp_path / "freeze.txt"
    freeze.write_text(
        "\n".join(
            [
                "-e git+https://github.com/x/y@0123abc#egg=defect_risk_analyzer",
                *(f"{name}=={version}" for name, version in constraints.items()),
                *(f"{name}=={version}" for name, version in directs.items()),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rc = check.main(["--freeze", str(freeze), "--constraints", str(CONSTRAINTS)])

    out = capsys.readouterr().out.splitlines()
    assert rc == 0, out
    assert len(out) == 1 and _NOTICE.match(out[0]), out
    installed, constrained, direct = map(int, _NOTICE.match(out[0]).groups())
    assert (constrained, direct) == (len(constraints), len(directs))
    assert installed == constrained + direct


def test_package_installed_without_a_constraint_is_red():
    installed = {**CONSTRAINED, **DIRECT, "colorama": "0.4.6"}
    verdict = check.compare(installed, CONSTRAINED, DIRECT)
    assert not verdict.ok
    assert verdict.unconstrained == ("colorama",)
    assert verdict.not_installed == () and verdict.version_diffs == ()


def test_constraint_that_was_not_installed_is_red():
    installed = {"certifi": "2026.9.15", **DIRECT}
    verdict = check.compare(installed, CONSTRAINED, DIRECT)
    assert not verdict.ok
    assert verdict.not_installed == ("uvloop",)
    assert verdict.unconstrained == ()


def test_version_differing_from_the_constraint_is_red():
    installed = {**CONSTRAINED, "certifi": "2026.10.1", **DIRECT}
    verdict = check.compare(installed, CONSTRAINED, DIRECT)
    assert not verdict.ok
    assert verdict.version_diffs == ("certifi: kisit 2026.9.15, kurulu 2026.10.1",)


def test_direct_pin_not_installed_at_its_version_is_red():
    installed = {**CONSTRAINED, "openai": "3.29.0"}
    verdict = check.compare(installed, CONSTRAINED, DIRECT)
    assert not verdict.ok
    assert verdict.direct_diffs == (
        "openai: requirements 3.26.1, kurulu 3.29.0",
        "pytest: requirements 9.1.1, kurulu yok",
    )


def test_unreadable_freeze_is_red():
    """Bekçinin bekçisi: boş ya da okunamayan bir freeze yeşil geçmez."""
    for text in ("", "\n\n", "# yalniz yorum\n-e .\n", "pip==26.2.1\n"):
        with pytest.raises(check.CheckError, match="freeze bos"):
            check.parse_freeze(text)
    with pytest.raises(check.CheckError, match="tanimsiz satir"):
        check.parse_freeze("certifi==2026.9.15\npkg @ file:///tmp/pkg\n")


def test_editable_comments_and_installer_lines_are_ignored():
    freeze = "\n".join(
        [
            "# Editable Git install with no remote (defect-risk-analyzer==0.1.0)",
            "-e c:\\olcum\\snap",
            "-e git+https://github.com/x/y@0123abc#egg=defect_risk_analyzer",
            "certifi==2026.9.15",
            "pip==26.2.1",
            "setuptools==84.0.0",
            "wheel==0.47.0",
        ]
    )
    assert check.parse_freeze(freeze) == {"certifi": "2026.9.15"}


def test_names_are_normalized_on_both_sides():
    installed = check.parse_freeze("PyYAML==6.0.3\ntyping_extensions==4.16.0\n")
    constraints = check.parse_pins("pyyaml==6.0.3\ntyping-extensions==4.16.0\n")
    verdict = check.compare(installed, constraints, {})
    assert verdict.ok, verdict
