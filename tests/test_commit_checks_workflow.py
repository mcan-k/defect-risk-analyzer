"""
`commit-checks.yml`: commit e-posta bekçisinin iş akışı.

İDDİA (Faz 6D-7a). Betiğin doğru sonucu iş akışının üç özelliğine bağlı, ve
üçü de tek satırlık bir düzenlemeyle sessizce bozulabilir:

  * `test_triggers_and_permissions` — tetikleyiciler `push` (yalnız `main`)
    ve `pull_request`; izin yalnız `contents: read`. Bekçi okur, yazmaz.
  * `test_checkout_fetches_full_history` — checkout `fetch-depth: 0`.
    Varsayılan 1'de aralığın tabanı (`base.sha` ya da `before`) klonda yok ve
    betik her koşuda "nesnesi depoda yok" ile kırmızı verir.
  * `test_email_job_runs_the_script_without_expressions` — "Commit e-mail
    check" job'u betiği tek bir komutla çağırır ve dosyada hiçbir `${{`
    ifadesi yoktur: olay adı ve yükü runner'ın ortamından okunur, uç olay
    yükündeki `head.sha`'dır (betiğin docstring'i). Çağrılan betik diskte
    var — betiği silen bir revert burada kırmızı.

Ağsız, alt süreçsiz; yalnız metin okur. YAML ayrıştırıcısı kullanılmıyor —
`tests/test_workflow_runners.py`'deki gerekçe.
"""

import re
from pathlib import Path

# The repo, not the config sandbox — same reason as tests/test_workflow_runners.py.
REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "commit-checks.yml"
SCRIPT = ".github/scripts/commit_email_check.py"

_STEP = re.compile(r"^      - name: (.+)$", re.MULTILINE)


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _steps() -> dict[str, str]:
    """Adım adı -> adımın metni."""
    text = _text()
    starts = list(_STEP.finditer(text))
    return {
        start.group(1).strip(): text[
            start.end():starts[index + 1].start() if index + 1 < len(starts) else len(text)
        ]
        for index, start in enumerate(starts)
    }


def test_triggers_and_permissions():
    text = _text()
    assert re.search(r"^on:\n  push:\n    branches: \[main\]\n  pull_request:\n", text, re.M), (
        "Tetikleyiciler degismis: beklenen push (yalniz main) ve pull_request."
    )
    assert re.search(r"^permissions:\n  contents: read\n(?!  )", text, re.M), (
        "Izin blogu yalniz `contents: read` olmali (bekci yazmaz)."
    )
    assert text.count("permissions:") == 1, "Job duzeyinde ikinci bir izin blogu var."


def test_checkout_fetches_full_history():
    checkout = _steps().get("Checkout repository", "")
    assert "uses: actions/checkout@v7" in checkout, checkout
    assert re.search(r"^\s+fetch-depth: 0\s*$", checkout, re.M), (
        "Checkout `fetch-depth: 0` tasimiyor: aralik tabani klonda olmaz, bekci her "
        "kosuda 'nesnesi depoda yok' ile kirmizi verir."
    )


def test_email_job_runs_the_script_without_expressions():
    text = _text()
    assert re.search(r"^    name: Commit e-mail check$", text, re.M), (
        "'Commit e-mail check' job'u bulunamadi."
    )
    step = _steps().get("Commit e-mail check", "")
    assert re.search(rf"^        run: python {re.escape(SCRIPT)}$", step, re.M), step
    assert (REPO_ROOT / SCRIPT).is_file(), f"{SCRIPT} diskte yok"
    assert "${{" not in text, (
        "Is akisinda bir `${{ }}` ifadesi var. Olay adi ve yuku runner'in ortamindan "
        "okunur; uc olay yukundeki head.sha'dir."
    )
