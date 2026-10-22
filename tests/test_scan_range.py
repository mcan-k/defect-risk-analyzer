"""
Gizli bilgi taramasının aralığı (`.github/scripts/scan_range.py`).

İDDİA (Faz 6D-7b). Tarama adımı aralığını bu betikten alır, ve betik aralığı
commit e-posta bekçisinin işlevleriyle hesaplar. Burada tutulan, betiğin kendi
işi: aralığı `GITHUB_ENV`'e doğru yazmak ve kötü bir aralıkta hiçbir şey
yazmadan kırmızı vermek. Aralık hesabının kenar durumları
`tests/test_commit_email_check.py`'de; burada yalnız kırmızının bu betikten de
geçtiği gösteriliyor.

  * `test_range_is_handed_to_the_scan` — `tmp_path`'te gerçek bir git deposu,
    `pull_request` yükü: `GITHUB_ENV`'e tam dört satır — olay, taban, uç ve
    aralıktaki commit sayısı; yeşilde hiçbir şey basılmaz.
  * `test_bad_range_is_red_and_hands_nothing` — boş aralık, 40 sıfırlı
    `before` ve tanımsız `GITHUB_ENV`: kırmızı, başlık "secret scan", neden
    yazılı, ve `GITHUB_ENV` dosyası boş kalır. Yazılmış bir aralık tarama
    adımını yeşile götürebilirdi.
  * `test_only_validated_values_reach_github_env` — `GITHUB_ENV`'e yazılan her
    değer kendi deseniyle tam eşleşmeli (denetleyici şartı, 2026-10-18): büyük
    harf, eksik hane, sonda satır sonu ile ikinci bir atama, `=`, bilinmeyen
    olay, sıfır ya da satır sonlu sayı, eksik ya da fazla anahtar reddedilir
    ve hata değişkenin adını söyler, değeri değil. `main` de yalnız bu
    denetimden geçen metni yazar: `event_range`'in denetimi atlatıldığında
    bile kırmızı verir ve hiçbir şey yazmaz.

KULLANICININ GIT AYARINA DAYANMAZ. `GIT_CONFIG_GLOBAL` boş bir dosyaya,
`GIT_CONFIG_NOSYSTEM` 1'e çevriliyor; kimlik yalnız commit komutunun ortam
değişkenleriyle veriliyor (uydurma bir noreply adresi).

Ağsız. git alt süreç olarak çağrılıyor; yalnız `tmp_path` altındaki depoya.
"""

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

# The repo, not the config sandbox — same reason as tests/test_commit_email_check.py.
REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / ".github" / "scripts"


def _load(name: str):
    """A CI script, not part of the package, so it is loaded by path."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# scan_range imports commit_email_check by name, as it does next to it in CI.
_load("commit_email_check")
scan_range = _load("scan_range")

ZERO = "0" * 40
IDENTITY = {
    "GIT_AUTHOR_NAME": "Noreply Kisi",
    "GIT_AUTHOR_EMAIL": "12345678+ornek-kullanici@users.noreply.github.com",
    "GIT_COMMITTER_NAME": "Noreply Kisi",
    "GIT_COMMITTER_EMAIL": "12345678+ornek-kullanici@users.noreply.github.com",
}
_ERROR = re.compile(r"^::error title=secret scan::(.+)$")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True, env={**os.environ, **IDENTITY},
    ).stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    empty = tmp_path / "empty.gitconfig"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q")
    return path


def _commit(repo: Path, number: int) -> str:
    (repo / "dosya.txt").write_text(f"{number}\n", encoding="utf-8")
    _git(repo, "add", "dosya.txt")
    _git(repo, "commit", "-q", "-m", f"commit {number}")
    return _git(repo, "rev-parse", "HEAD").strip()


def _environ(tmp_path: Path, event: str, payload: dict, github_env: Path | None) -> dict:
    path = tmp_path / "event.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    environ = {"GITHUB_EVENT_NAME": event, "GITHUB_EVENT_PATH": str(path)}
    if github_env is not None:
        environ["GITHUB_ENV"] = str(github_env)
    return environ


def _pull(base: str, head: str) -> dict:
    return {"pull_request": {"base": {"sha": base}, "head": {"sha": head}}}


def test_range_is_handed_to_the_scan(repo, tmp_path, capsys):
    base = _commit(repo, 1)
    _commit(repo, 2)
    head = _commit(repo, 3)
    github_env = tmp_path / "github_env"
    github_env.write_text("", encoding="utf-8")

    environ = _environ(tmp_path, "pull_request", _pull(base, head), github_env)
    assert scan_range.main(["--repo", str(repo)], environ) == 0

    assert github_env.read_text(encoding="utf-8").splitlines() == [
        "SCAN_EVENT=pull_request",
        f"SCAN_BASE={base}",
        f"SCAN_HEAD={head}",
        "SCAN_COUNT=2",
    ]
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("bos-aralik", "aralik bos"),
        ("sifir-before", "40 sifir"),
        ("github-env-yok", "GITHUB_ENV tanimsiz"),
    ],
)
def test_bad_range_is_red_and_hands_nothing(repo, tmp_path, capsys, case, reason):
    base = _commit(repo, 1)
    head = _commit(repo, 2)
    github_env = tmp_path / "github_env"
    github_env.write_text("", encoding="utf-8")

    if case == "bos-aralik":
        environ = _environ(tmp_path, "pull_request", _pull(head, head), github_env)
    elif case == "sifir-before":
        environ = _environ(tmp_path, "push", {"before": ZERO, "after": head}, github_env)
    else:
        # A valid range: only the missing GITHUB_ENV can make this red.
        environ = _environ(tmp_path, "pull_request", _pull(base, head), None)

    assert scan_range.main(["--repo", str(repo)], environ) == 1

    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1, out
    match = _ERROR.match(out[0])
    assert match and reason in match.group(1), out[0]
    assert github_env.read_text(encoding="utf-8") == "", (
        "Kirmizi bir aralikta GITHUB_ENV'e bir sey yazildi; tarama adimi onu kullanabilirdi."
    )


def test_only_validated_values_reach_github_env(repo, tmp_path, capsys, monkeypatch):
    good = {"SCAN_EVENT": "push", "SCAN_BASE": "a" * 40, "SCAN_HEAD": "b" * 40, "SCAN_COUNT": "12"}
    assert scan_range.env_lines(good).splitlines(keepends=True) == [
        "SCAN_EVENT=push\n",
        f"SCAN_BASE={'a' * 40}\n",
        f"SCAN_HEAD={'b' * 40}\n",
        "SCAN_COUNT=12\n",
    ]
    bad = [
        ("SCAN_BASE", "A" * 40),
        ("SCAN_HEAD", "b" * 39),
        ("SCAN_HEAD", "b" * 40 + "\nSCAN_EXTRA=1"),
        ("SCAN_BASE", "a" * 20 + "=" + "a" * 19),
        ("SCAN_EVENT", "push\nSCAN_EXTRA"),
        ("SCAN_EVENT", "workflow_dispatch"),
        ("SCAN_COUNT", "0"),
        ("SCAN_COUNT", "2\n"),
        ("SCAN_COUNT", None),
        ("SCAN_EXTRA", "1"),
    ]
    for name, value in bad:
        values = {key: val for key, val in {**good, name: value}.items() if val is not None}
        with pytest.raises(scan_range.CheckError, match=name):
            scan_range.env_lines(values)

    # main writes only what passed the check, even when the range's own check
    # is bypassed.
    head = _commit(repo, 1)
    github_env = tmp_path / "github_env"
    github_env.write_text("", encoding="utf-8")
    monkeypatch.setattr(scan_range, "event_range", lambda event, payload: (head, head.upper()))
    monkeypatch.setattr(scan_range, "range_commits", lambda *args: [("x", "y", "z")])
    environ = _environ(tmp_path, "pull_request", _pull(head, head), github_env)

    assert scan_range.main(["--repo", str(repo)], environ) == 1

    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1 and _ERROR.match(out[0]) and "SCAN_HEAD" in out[0], out
    assert head.upper() not in out[0], "Reddedilen deger basildi."
    assert github_env.read_text(encoding="utf-8") == ""
