"""
Her workflow aynı, sabitlenmiş runner imajında koşar.

WHY. GitHub `ubuntu-latest` etiketini 2026-10-19'dan itibaren Ubuntu 26'ya
taşıyor (actions/runner-images#14748). CI'ın çözdüğü paket kümesi platforma
bağlı — 6D-3'te ölçüldü: Linux `uvloop` çözüyor, Windows `colorama` — ve
6D-3b'nin kısıt dosyası CI ile aynı imajda üretilmek zorunda. Faz 6D-4d-1 bu
yüzden `tests.yml` ile `pr-risk-analysis.yml`'yi `ubuntu-24.04`'e sabitledi.
İki iş akışı zaten farklı çözünürlük test ediyor (biri `requirements-dev.txt`,
öteki yalnız `requirements.txt` kuruyor); buna bir de platform farkı
eklenmemeli.

Sabitlemenin kendisi tek satır, ve tek satırın sorunu yine aynı: biri bir gün
yalnız bir dosyayı değiştirir, CI yeşil kalır ve iki iş akışı sessizce ayrışır.
Yorum bunu söyler ama tutmaz. Bu dosya tutar.

İKİ TEST, İKİ AYRI İŞ.

  * `test_every_workflow_job_runs_on_the_pinned_runner` — iddianın kendisi:
    `.github/workflows/` altındaki her `runs-on:` değeri `EXPECTED_RUNNER`.
    Yalnız iki dosyaya değil her workflow'a bakar; sonradan eklenen bir
    workflow (6D-4d-3'ün haftalık işi gibi) da kapsamda.
  * `test_runner_scan_is_not_vacuous` — birinci testin boşuna geçmediğini
    tutar. Desen hiçbir satırı yakalamazsa birinci test "her değer doğru"
    der, çünkü hiç değer yoktur. 6D-4c'nin imza kontrat testi aynı sebeple
    `**kwargs`'ın yokluğunu ayrıca assert ediyordu.

Ağsız, alt süreçsiz; yalnız metin okur. YAML ayrıştırıcısı kullanılmıyor:
`PyYAML` bu depoda doğrudan bir bağımlılık değil, chromadb üzerinden geliyor ve
6D-5'in chromadb işi kapanışı değiştirebilir. Bir testin kendi bağımlılığını
transitif bir zincire bırakması, 6D-3a'nın gerekçe bekçisinin `skip` riskiyle
aynı sınıf.

SABİTLEMEYİ KALDIRMAK BİR KARAR, KAZA DEĞİL. 26.04'e geçiş kendi PR'ında yapılır
ve `EXPECTED_RUNNER` orada değişir; tetikleyici docs/KNOWN-DEBT.md'de.
"""

import re
from pathlib import Path

# The repo, not the config sandbox — same reason as tests/test_dependency_pins.py.
REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

# Faz 6D-4d-1'de seçilen imaj. Değiştirmek bir geçiş kararıdır — docstring'e
# ve docs/KNOWN-DEBT.md'deki tetikleyiciye bakın.
EXPECTED_RUNNER = "ubuntu-24.04"

# Varlığı bilinen iş akışları. Taramanın boş dönmediğinin kanıtı bunlar.
KNOWN_WORKFLOWS = ("tests.yml", "pr-risk-analysis.yml")

# `runs-on:` değerini satır içi yorumu ve tırnakları atarak yakalar.
_RUNS_ON = re.compile(r"^\s*runs-on:\s*['\"]?([^'\"\s#]+)", re.MULTILINE)


def _runners_by_workflow() -> dict[str, list[str]]:
    """Her workflow dosyası için bulunan `runs-on:` değerleri, dosya sırasıyla."""
    files = sorted([*WORKFLOWS_DIR.glob("*.yml"), *WORKFLOWS_DIR.glob("*.yaml")])
    return {
        path.name: _RUNS_ON.findall(path.read_text(encoding="utf-8"))
        for path in files
    }


def test_every_workflow_job_runs_on_the_pinned_runner():
    """Her `runs-on:` değeri `EXPECTED_RUNNER` olmalı.

    "İki workflow aynı" ile "ikisi de 24.04" tek assert'te: hepsi aynı sabit
    değere eşitse birbirine de eşittir. Ayrı bir "aynı mı" testi, ikisi birlikte
    `ubuntu-latest`'e dönerse yeşil kalırdı.
    """
    wrong = [
        (name, runner)
        for name, runners in _runners_by_workflow().items()
        for runner in runners
        if runner != EXPECTED_RUNNER
    ]
    assert not wrong, (
        "Bir workflow sabitlenmis runner disinda kosuyor:\n"
        + "\n".join(f"  {name}: runs-on: {runner}" for name, runner in wrong)
        + f"\nbeklenen: runs-on: {EXPECTED_RUNNER} (Faz 6D-4d-1). Iki workflow "
        "ayni imajda kosmali; cozunen paket kumesi platforma bagli. 26.04'e "
        "gecis kendi PR'inda yapilir, tetikleyici docs/KNOWN-DEBT.md'de."
    )


def test_runner_scan_is_not_vacuous():
    """Bilinen her workflow bulunmalı ve en az bir `runs-on:` taşımalı.

    Bu olmadan birinci test, desen bir gün hiçbir satırı yakalamazsa — dosya
    taşınırsa, anahtar yeniden biçimlenirse — "yanlış değer yok" diye geçer.
    """
    runners = _runners_by_workflow()
    missing = [name for name in KNOWN_WORKFLOWS if name not in runners]
    assert not missing, (
        f"Beklenen workflow dosyalari bulunamadi: {missing} "
        f"({WORKFLOWS_DIR} altinda). Tarama bos donuyor olabilir."
    )
    empty = [name for name in KNOWN_WORKFLOWS if not runners[name]]
    assert not empty, (
        f"Su workflow'larda hic `runs-on:` satiri yakalanmadi: {empty}. "
        "Desen ya da dosya bicimi degismis; birinci test bos yere gecer."
    )
