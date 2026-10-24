"""
`commit-checks.yml`, job "Secret scan": gizli bilgi taramasının iş akışı.

İDDİA (Faz 6D-7b). Taramanın değeri iş akışının dört özelliğine bağlı, ve
dördü de tek satırlık bir düzenlemeyle sessizce bozulabilir:

  * `test_gitleaks_pin_is_in_one_place` — gitleaks sürümü ve arşivin sha256'sı
    dosyada tek yerde ve biçimi doğru; indirme ikisini de oradan okur ve
    `sha256sum -c` ile denetler (kullanıcı kararı K3, 2026-10-18). İkinci bir
    kopya ya da bozuk bir biçim kırmızı: iki değerden biri güncellenip öteki
    unutulamaz.
  * `test_scanner_prints_no_value_and_no_address` — iki gitleaks çağrısı da
    `--redact` ve yalnız kural + dosya:satır + commit basan bir şablonla
    koşar. `-v`, JSON/SARIF/CSV raporu, artifact yüklemesi ve PR yorumu yok:
    6D-7 keşfi `-v`'nin ve SARIF'in yazar e-postasını bastığını ölçtü
    (2026-10-16). Şablon `.Secret`, `.Match`, `.Email` ya da `.Author`'a
    dokunursa kırmızı.
  * `test_positive_control_runs_before_the_scan` — tarayıcı, sessizliği bir
    şey ifade etmeden önce çalışma anında üretilen sahte bir tokenı bulmak
    zorunda (kullanıcı kararı K8, 2026-10-16); kontrol adımı taramadan önce
    gelir ve bulamazsa kırmızı verir. Dosyada anahtar biçimli bir literal
    yok: token yalnız koşu anında, geçici bir depoda var.
  * `test_scan_job_reads_full_history_with_the_config` — checkout
    `fetch-depth: 0` (aralığın tabanı klonda olmalı), izin yalnız
    `contents: read`, iki çağrı da `.gitleaks.toml`'u açıkça alır ve dosya
    diskte, tarama yalnız `SCAN_BASE..SCAN_HEAD`'e bakar ve ikisini kendisi de
    yeniden denetler (boş bir `--log-opts` bütün geçmişi tarardı), ve aralığı
    veren betik diskte.
    Dosyadaki adım adları tekil: `tests/test_commit_checks_workflow.py`
    adımları adla bulur, ve tekrarlanan bir ad e-posta job'unun adımını
    sessizce bu job'unkiyle değiştirirdi.

Ağsız, alt süreçsiz; yalnız metin okur. YAML ayrıştırıcısı kullanılmıyor —
`tests/test_workflow_runners.py`'deki gerekçe.
"""

import re
from pathlib import Path

# The repo, not the config sandbox — same reason as tests/test_workflow_runners.py.
REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "commit-checks.yml"
CONFIG = ".gitleaks.toml"
RANGE_SCRIPT = ".github/scripts/scan_range.py"

ORDER = ("Install gitleaks", "Positive control", "Scan range", "Secret scan")
TEMPLATE_FIELDS = {"RuleID", "File", "StartLine", "Commit"}

_JOB = re.compile(r"^  [\w-]+:\n    name: (.+)$", re.MULTILINE)
_STEP = re.compile(r"^      - name: (.+)$", re.MULTILINE)
# A gitleaks call, with its backslash-continued lines.
_CALL = re.compile(r'"\$dir/gitleaks" git(?:[^\n]*\\\n)*[^\n]*')


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _job(name: str) -> str:
    text = _text()
    starts = list(_JOB.finditer(text))
    for index, start in enumerate(starts):
        if start.group(1).strip() == name:
            end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
            return text[start.start():end]
    return ""


def _steps(job: str) -> dict[str, str]:
    """Adım adı -> adımın metni, iş akışındaki sırasıyla."""
    starts = list(_STEP.finditer(job))
    return {
        start.group(1).strip(): job[
            start.end():starts[index + 1].start() if index + 1 < len(starts) else len(job)
        ]
        for index, start in enumerate(starts)
    }


def _calls() -> list[str]:
    return _CALL.findall(_job("Secret scan"))


def test_gitleaks_pin_is_in_one_place():
    text = _text()
    versions = re.findall(r"^\s+GITLEAKS_VERSION: (\S+)$", text, re.M)
    hashes = re.findall(r"^\s+GITLEAKS_SHA256: (\S+)$", text, re.M)
    assert len(versions) == 1 and re.fullmatch(r"\d+\.\d+\.\d+", versions[0]), versions
    assert len(hashes) == 1 and re.fullmatch(r"[0-9a-f]{64}", hashes[0]), hashes
    assert text.count(versions[0]) == 1, "Surum dizesi dosyada birden cok yerde yaziyor."
    assert len(re.findall(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{64}(?![0-9A-Fa-f])", text)) == 1, (
        "Dosyada ikinci bir sha256 kopyasi var: iki deger ayrisabilir."
    )
    install = _steps(_job("Secret scan")).get("Install gitleaks", "")
    assert "releases/download/v${GITLEAKS_VERSION}/" in install, install
    assert re.search(r'echo "\$GITLEAKS_SHA256  [^"]+" \| sha256sum -c -', install), install


def test_scanner_prints_no_value_and_no_address():
    text = _text()
    calls = _calls()
    assert len(calls) == 2, (
        f"Beklenen iki gitleaks cagrisi (kontrol + tarama), bulunan {len(calls)}"
    )
    for call in calls:
        assert re.search(r"--redact(?=\s)", call), f"`--redact` yok ya da degerli: {call}"
        assert "--no-banner" in call, call
        assert "--report-format template" in call, call
        assert '--report-template "$dir/findings.tmpl"' in call, call
    assert not re.search(r"(?<![\w-])(-v|--verbose)(?![\w-])", text), (
        "Is akisinda `-v`/`--verbose` var: ayrintili cikti yazar e-postasini basar."
    )
    # The long flag anywhere in the file; the short one only inside the calls,
    # where `-f` is gitleaks' and not the shell's file test.
    formats = re.findall(r"--report-format[ =](\S+)", text) + re.findall(
        r"(?<![\w-])-f[ =](\S+)", "\n".join(calls)
    )
    assert formats and set(formats) == {"template"}, f"Rapor bicimleri: {formats}"
    template = _steps(_job("Secret scan")).get("Install gitleaks", "")
    fields = set(re.findall(r"\{\{\s*\.(\w+)\s*\}\}", template))
    assert fields and fields <= TEMPLATE_FIELDS, (
        f"Rapor sablonu izin verilmeyen alan basiyor: {sorted(fields - TEMPLATE_FIELDS)}"
    )
    for forbidden in ("upload-artifact", "github-script"):
        assert forbidden not in text, f"Is akisinda {forbidden} var: rapor yuklenmez, yorumlanmaz."


def test_positive_control_runs_before_the_scan():
    steps = _steps(_job("Secret scan"))
    names = list(steps)
    assert all(name in names for name in ORDER), f"Eksik adim: {set(ORDER) - set(names)}"
    positions = [names.index(name) for name in ORDER]
    assert positions == sorted(positions), f"Adim sirasi bozuk: {names}"
    control = steps["Positive control"]
    assert "/dev/urandom" in control, "Sahte token calisma aninda uretilmiyor."
    assert 'ctl="$RUNNER_TEMP/' in control, "Kontrol deposu RUNNER_TEMP altinda degil."
    assert re.search(r"tarayici kor:.*\n\s+exit 1", control), (
        "Kontrol, tokeni bulamayinca kirmizi vermiyor."
    )
    assert not re.search(r"gh[pousr]_[A-Za-z0-9]{36}|github_pat_\w{22,}", _text()), (
        "Is akisinda anahtar bicimli bir literal var."
    )


def test_scan_job_reads_full_history_with_the_config():
    text = _text()
    steps = _steps(_job("Secret scan"))
    checkout = next((body for body in steps.values() if "actions/checkout@" in body), "")
    assert re.search(r"^\s+fetch-depth: 0\s*$", checkout, re.M), (
        "Secret scan job'unun checkout'u `fetch-depth: 0` tasimiyor: aralik tabani klonda olmaz."
    )
    assert text.count("permissions:") == 1, "Job duzeyinde ikinci bir izin blogu var."
    assert re.search(r"^permissions:\n  contents: read\n(?!  )", text, re.M), (
        "Izin blogu yalniz `contents: read` olmali."
    )
    names = _STEP.findall(text)
    assert len(names) == len(set(names)), f"Adim adlari tekil degil: {names}"
    calls = _calls()
    assert calls and all(f"--config {CONFIG}" in call for call in calls), calls
    assert (REPO_ROOT / CONFIG).is_file(), f"{CONFIG} diskte yok"
    scan = _CALL.findall(steps.get("Secret scan", ""))
    assert len(scan) == 1 and '--log-opts="$SCAN_BASE..$SCAN_HEAD"' in scan[0], scan
    assert re.search(
        r'^\s+\[\[ "\$SCAN_BASE" =~ \^\[0-9a-f\]\{40\}\$ && '
        r'"\$SCAN_HEAD" =~ \^\[0-9a-f\]\{40\}\$ \]\] \|\| \{$',
        steps.get("Secret scan", ""), re.M,
    ), "Tarama adimi taban ve ucu yeniden denetlemiyor."
    assert re.search(
        rf"^        run: python {re.escape(RANGE_SCRIPT)}$", steps.get("Scan range", ""), re.M
    ), steps.get("Scan range")
    assert (REPO_ROOT / RANGE_SCRIPT).is_file(), f"{RANGE_SCRIPT} diskte yok"
