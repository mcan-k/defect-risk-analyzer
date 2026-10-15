"""
İki iş akışı aynı kısıt dosyasıyla kurar, ve eşitlik adımı yerinde durur.

İDDİA (Faz 6D-3b-2b). `tests.yml` ve `pr-risk-analysis.yml` paketleri aynı
`-c .github/constraints/ci-linux-py311.txt` ile kuruyor. pr-risk yalnız
`requirements.txt` kuruyor ve ayrı bir eşitlik adımı taşımıyor: kurduğu küme
`tests.yml`'inkinin alt kümesi, `-c` altında her paketi aynı sürüme zorluyor,
ve orada kısıtsız kalabilecek her paket `tests.yml`'in kümesinde de kurulup
oradaki eşitlik adımında kırmızıya döner. Bu yüzden iki dosyanın aynı `-c`'yi
taşıması bir kural değil, o akıl yürütmenin ön koşulu. Üç test:

  * `test_every_requirements_install_uses_the_constraints_file` — her
    `pip install … -r …` satırı aynı `-c` yolunu taşıyor ve dosya diskte var;
  * `test_install_scan_is_not_vacuous` — tarama iki dosyada da en az bir
    satır buluyor. Olmasa birinci test, desen bir gün hiçbir satırı
    yakalamadığında "yanlış satır yok" diye geçerdi (`test_workflow_runners`
    ile aynı ders);
  * `test_equality_step_follows_pytest_and_a_successful_install` — eşitlik
    adımı Pytest'ten sonra, ve o adımla iki pip-audit adımı yalnız kurulum
    başarılıysa koşuyor (kullanıcı kararı 2026-10-12: kurulum düşerse ortamda
    pip-audit bile yok, kapı ikinci, yanıltıcı bir kırmızı verir).

BEYAN EDİLMİŞ KÖR NOKTA. pr-risk'in kendi çözümlemesi ayrıca denetlenmiyor;
yukarıdaki alt küme akıl yürütmesine dayanıyor.

Ağsız, alt süreçsiz; yalnız metin okur. YAML ayrıştırıcısı kullanılmıyor —
`tests/test_workflow_runners.py`'deki gerekçe: PyYAML bu depoda doğrudan bir
bağımlılık değil.
"""

import re
from pathlib import Path

# The repo, not the config sandbox — same reason as tests/test_workflow_runners.py.
REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

CONSTRAINTS = ".github/constraints/ci-linux-py311.txt"
INSTALLING_WORKFLOWS = ("tests.yml", "pr-risk-analysis.yml")
GUARDED_STEPS = ("Constraints equality check", "pip-audit (report only)", "pip-audit gate")
AFTER_INSTALL = "${{ !cancelled() && steps.install.outcome == 'success' }}"

# `pip install` satırı (önünde `python -m` olabilir); `-r` taşıyanlar aşağıda süzülür.
_PIP_INSTALL = re.compile(r"^[ \t]*(?:python -m )?pip install (.*)$", re.MULTILINE)
_REQUIREMENT = re.compile(r"(?:^|\s)(?:-r|--requirement)\s")
_CONSTRAINT = re.compile(r"(?:^|\s)(?:-c|--constraint)\s+(\S+)")
_STEP = re.compile(r"^      - name: (.+)$", re.MULTILINE)
_KEY = re.compile(r"^        (if|id): (.+)$", re.MULTILINE)


def _requirement_installs() -> dict[str, list[str]]:
    """Her iş akışı için `-r` taşıyan `pip install` satırlarının argümanları."""
    return {
        name: [
            args
            for args in _PIP_INSTALL.findall(
                (WORKFLOWS_DIR / name).read_text(encoding="utf-8")
            )
            if _REQUIREMENT.search(args)
        ]
        for name in INSTALLING_WORKFLOWS
    }


def _steps(name: str) -> list[tuple[str, dict[str, str]]]:
    """Adımlar sırasıyla: (ad, {"if": …, "id": …})."""
    text = (WORKFLOWS_DIR / name).read_text(encoding="utf-8")
    starts = list(_STEP.finditer(text))
    steps = []
    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        block = text[start.end():end]
        steps.append((start.group(1).strip(), dict(_KEY.findall(block))))
    return steps


def test_every_requirements_install_uses_the_constraints_file():
    wrong = [
        (name, args)
        for name, installs in _requirement_installs().items()
        for args in installs
        if _CONSTRAINT.findall(args) != [CONSTRAINTS]
    ]
    assert not wrong, (
        "Kisit dosyasiz ya da baska bir kisitla kuran satir(lar):\n"
        + "\n".join(f"  {name}: pip install {args}" for name, args in wrong)
        + f"\nbeklenen: -c {CONSTRAINTS} (Faz 6D-3b-2b). Iki is akisi ayni "
        "dosyayla kurmali; pr-risk'in ayri bir esitlik adimi yok."
    )
    assert (REPO_ROOT / CONSTRAINTS).is_file(), f"{CONSTRAINTS} diskte yok"


def test_install_scan_is_not_vacuous():
    empty = [name for name, installs in _requirement_installs().items() if not installs]
    assert not empty, (
        f"Su is akislarinda `pip install ... -r ...` satiri yakalanmadi: {empty}. "
        "Desen ya da kurulum bicimi degismis; birinci test bos yere gecer."
    )


def test_equality_step_follows_pytest_and_a_successful_install():
    steps = _steps("tests.yml")
    names = [name for name, _ in steps]
    keys = dict(steps)
    missing = [n for n in ("Install dependencies", "Pytest", *GUARDED_STEPS) if n not in keys]
    assert not missing, f"tests.yml'de beklenen adim(lar) yok: {missing}"

    assert keys["Install dependencies"].get("id") == "install", (
        "Kurulum adiminin `id: install`'u yok; asagidaki kosullar onu okuyor."
    )
    assert names.index("Constraints equality check") > names.index("Pytest"), (
        "Esitlik adimi Pytest'ten sonra olmali: bayat bir kisit dosyasi testlerin "
        "kanitini gizlememeli."
    )
    wrong = {n: keys[n].get("if") for n in GUARDED_STEPS if keys[n].get("if") != AFTER_INSTALL}
    assert not wrong, (
        f"Kosulu yanlis adim(lar): {wrong}\nbeklenen: if: {AFTER_INSTALL} "
        "(kullanici karari 2026-10-12: Ruff/Pytest kirmiziyken kosar, kurulum "
        "dustugunde atlanir)."
    )
