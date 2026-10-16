"""
Commit e-posta bekçisi (`.github/scripts/commit_email_check.py`).

İDDİA (Faz 6D-7a). Olayın aralığındaki her commit'in yazar ve committer
adresi GitHub'ın noreply adresi; değilse kırmızı, ve kırmızı yalnız commit
hash'ini ve alanı söyler — adresi de adı da asla. Testler iki katmanda:

  * saf kısım — adres kuralı (izin verilen ve reddedilen adres tablosu), alan
    adı, olay yükünden aralık;
  * `tmp_path`'te gerçek bir git deposu — `main` uçtan uca: yeşil sayı
    söyler; kırmızı hash + alan verir ve adres sızdırmaz; denetlenen uç
    olay yükündeki `head.sha`, checkout'un HEAD'i değil; merge commit'leri
    aralıkta; `.mailmap` bir adresi örtemez; 40 sıfırlı `before`, depoda
    olmayan `before`, boş aralık ve okunamayan olay yükü kırmızı.

BEKÇİNİN BEKÇİSİ. Boş ya da hesaplanamayan bir aralık yeşil geçmez; yeşil
mesaj kaç commit'e bakıldığını söyler, ve sayıyı tutan test (`I1`) aralık
hesabı bozulduğunda kırmızıya döner. Adres sızıntısı testi, kırmızı commit'lerin
gerçekten listelendiğini de ister: hiçbir şey basılmasaydı "adres yok" boşuna
geçerdi.

KULLANICININ GIT AYARINA DAYANMAZ. Her test `GIT_CONFIG_GLOBAL`'i boş bir
dosyaya, `GIT_CONFIG_NOSYSTEM`'i 1'e çeviriyor; kimlik yalnız commit
komutlarının ortam değişkenleriyle veriliyor. Kişisel adres yok: kötü
kimlikler `example.com`, iyi kimlikler uydurma noreply adresleri.

Ağsız. git alt süreç olarak çağrılıyor; yalnız `tmp_path` altındaki depolara.
"""

import importlib.util
import itertools
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

# The repo, not the config sandbox — same reason as tests/test_constraints_check.py.
REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / ".github" / "scripts" / "commit_email_check.py"

# A CI script, not part of the package, so it is loaded by path.
_spec = importlib.util.spec_from_file_location("commit_email_check", SCRIPT_PATH)
check = importlib.util.module_from_spec(_spec)
sys.modules["commit_email_check"] = check
_spec.loader.exec_module(check)

NOREPLY = ("Noreply Kisi", "12345678+ornek-kullanici@users.noreply.github.com")
WEB_FLOW = ("GitHub", "noreply@github.com")
BAD = ("Ornek Kisi", "ornek.kisi@example.com")
OTHER_BAD = ("Baska Kisi", "baska.kisi@example.com")

_COUNTER = itertools.count()

_ANNOTATION = re.compile(r"^::(notice|error) title=commit e-mail check::(.*)$")
_NOTICE = re.compile(
    r"^(\d+) commit, hepsi noreply \((pull_request|push) ([0-9a-f]{7})\.\.([0-9a-f]{7})\)$"
)


@pytest.fixture(autouse=True)
def _isolated_git(tmp_path_factory, monkeypatch):
    """git, kullanıcının global ve sistem ayarı olmadan çalışır."""
    empty = tmp_path_factory.mktemp("gitconfig") / "empty"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return result.stdout.strip()


def _identity(author: tuple[str, str], committer: tuple[str, str]) -> dict[str, str]:
    return {
        **os.environ,
        "GIT_AUTHOR_NAME": author[0],
        "GIT_AUTHOR_EMAIL": author[1],
        "GIT_COMMITTER_NAME": committer[0],
        "GIT_COMMITTER_EMAIL": committer[1],
    }


def _commit(repo: Path, author, committer=None) -> str:
    """Yeni bir dosyayla bir commit; hash'ini döndürür.

    Sayaç modül genelinde: iki dalda aynı saniyede aynı içerikle yapılan iki
    commit aynı hash'i alırdı ve merge "Already up to date" derdi.
    """
    count = next(_COUNTER)
    (repo / f"f{count}.txt").write_text(f"{count}\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"c{count}", env=_identity(author, committer or author))
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    return path


def _pull_request(base: str, head: str) -> dict:
    return {"pull_request": {"base": {"sha": base}, "head": {"sha": head}}}


def _run(repo: Path, event: str, payload: dict, capsys) -> tuple[int, str, list[str]]:
    """`main`'i olay yüküyle koştur: (rc, düzey, mesaj satırları)."""
    path = repo.parent / "event.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    rc = check.main(
        ["--repo", str(repo)],
        environ={"GITHUB_EVENT_NAME": event, "GITHUB_EVENT_PATH": str(path)},
    )
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 1, out
    match = _ANNOTATION.match(out[0])
    assert match, out
    return rc, match.group(1), match.group(2).split("%0A")


# --- saf kısım -------------------------------------------------------------


@pytest.mark.parametrize(
    "email",
    [
        "12345678+ornek-kullanici@users.noreply.github.com",
        "ornek-kullanici@users.noreply.github.com",
        "12345678+ornek-bot[bot]@users.noreply.github.com",
        "noreply@github.com",
    ],
)
def test_noreply_addresses_are_allowed(email):
    assert check.is_noreply(email)


@pytest.mark.parametrize(
    "email",
    [
        "ornek@example.com",
        "noreply@example.com",
        "ornek@users.noreply.github.com.example.com",
        "users.noreply.github.com@example.com",
        "noreply@github.com.example.com",
        "ornek@users.noreply.github.com\n",
        "",
    ],
)
def test_other_addresses_are_rejected(email):
    assert not check.is_noreply(email)


def test_field_is_named_for_each_side():
    good, bad = NOREPLY[1], BAD[1]
    assert check.field(good, WEB_FLOW[1]) is None
    assert check.field(bad, good) == "yazar"
    assert check.field(good, bad) == "committer"
    assert check.field(bad, bad) == "yazar+committer"


def test_pull_request_range_is_base_to_head():
    """PR'da aralık `base.sha..head.sha`; yükteki `before`/`after` okunmaz."""
    base, head, decoy = "a" * 40, "b" * 40, "c" * 40
    payload = {**_pull_request(base, head), "before": decoy, "after": decoy}
    assert check.event_range("pull_request", payload) == (base, head)


def test_push_range_is_before_to_after():
    before, after, decoy = "a" * 40, "b" * 40, "c" * 40
    payload = {"before": before, "after": after, **_pull_request(decoy, decoy)}
    assert check.event_range("push", payload) == (before, after)


def test_unsupported_event_is_red():
    with pytest.raises(check.CheckError, match="desteklenmeyen olay"):
        check.event_range("workflow_dispatch", {})


# --- uçtan uca, tmp_path deposunda ----------------------------------------


def test_noreply_range_passes_and_says_how_many(repo, capsys):
    base = _commit(repo, NOREPLY, WEB_FLOW)
    _commit(repo, NOREPLY)
    head = _commit(repo, ("dependabot[bot]", "12345+ornek-bot[bot]@users.noreply.github.com"),
                   WEB_FLOW)

    rc, level, lines = _run(repo, "pull_request", _pull_request(base, head), capsys)

    assert (rc, level) == (0, "notice"), lines
    assert len(lines) == 1 and _NOTICE.match(lines[0]), lines
    assert _NOTICE.match(lines[0]).groups() == ("2", "pull_request", base[:7], head[:7])


def test_non_noreply_commits_are_red_with_hash_and_field(repo, capsys):
    base = _commit(repo, NOREPLY)
    author_only = _commit(repo, BAD, NOREPLY)
    committer_only = _commit(repo, NOREPLY, BAD)
    both = _commit(repo, BAD, OTHER_BAD)
    head = _commit(repo, NOREPLY, WEB_FLOW)

    rc, level, lines = _run(repo, "pull_request", _pull_request(base, head), capsys)

    assert (rc, level) == (1, "error"), lines
    assert lines[0].startswith("3 / 4 commit noreply olmayan bir adres tasiyor "), lines
    assert lines[1:4] == [
        f"{both} yazar+committer",
        f"{committer_only} committer",
        f"{author_only} yazar",
    ]
    assert head not in "\n".join(lines)


def test_output_never_contains_the_address_or_name(repo, capsys):
    """Ne commit'teki adres ve ad, ne olay yükündeki (pusher) basılır."""
    before = _commit(repo, NOREPLY)
    red = {_commit(repo, BAD, OTHER_BAD), _commit(repo, OTHER_BAD, NOREPLY)}
    payload = {
        "before": before,
        "after": _git(repo, "rev-parse", "HEAD"),
        "pusher": {"name": BAD[0], "email": BAD[1]},
        "head_commit": {"author": {"name": OTHER_BAD[0], "email": OTHER_BAD[1]}},
    }

    rc, level, lines = _run(repo, "push", payload, capsys)
    text = "\n".join(lines)

    assert (rc, level) == (1, "error"), lines
    assert {line.split()[0] for line in lines[1:3]} == red, lines
    assert text.count("@") == 0, text
    for secret in (*BAD, *OTHER_BAD, "example.com", "Kisi"):
        assert secret not in text, secret


def test_payload_head_is_checked_not_the_checkout(repo, capsys):
    """GitHub'ın test merge'ü checkout'un HEAD'i; uç olay yükündeki head.sha."""
    base = _commit(repo, NOREPLY)
    head = _commit(repo, NOREPLY)
    _commit(repo, BAD)  # checkout'un HEAD'i: aralığın dışında

    rc, level, lines = _run(repo, "pull_request", _pull_request(base, head), capsys)

    assert (rc, level) == (0, "notice"), lines
    assert _NOTICE.match(lines[0]).group(1) == "1", lines


def test_merge_commits_in_the_range_are_checked(repo, capsys):
    before = _commit(repo, NOREPLY)
    _git(repo, "switch", "-q", "-c", "konu")
    _commit(repo, NOREPLY)
    _git(repo, "switch", "-q", "main")
    _commit(repo, NOREPLY)
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge", "konu", env=_identity(NOREPLY, BAD))
    merge = _git(repo, "rev-parse", "HEAD")

    rc, level, lines = _run(repo, "push", {"before": before, "after": merge}, capsys)

    assert (rc, level) == (1, "error"), lines
    assert lines[0].startswith("1 / 3 commit "), lines
    assert f"{merge} committer" in lines


def test_mailmap_cannot_hide_an_address(repo, capsys):
    base = _commit(repo, NOREPLY)
    red = _commit(repo, BAD, NOREPLY)
    (repo / ".mailmap").write_text(
        f"{NOREPLY[0]} <{NOREPLY[1]}> <{BAD[1]}>\n", encoding="utf-8"
    )
    _git(repo, "add", ".mailmap")
    _git(repo, "commit", "-q", "-m", "mailmap", env=_identity(NOREPLY, NOREPLY))
    head = _git(repo, "rev-parse", "HEAD")

    rc, level, lines = _run(repo, "pull_request", _pull_request(base, head), capsys)

    assert (rc, level) == (1, "error"), lines
    assert f"{red} yazar" in lines


def test_zero_before_is_red(repo, capsys):
    after = _commit(repo, NOREPLY)

    rc, level, lines = _run(repo, "push", {"before": "0" * 40, "after": after}, capsys)

    assert (rc, level) == (1, "error"), lines
    assert "before 40 sifir" in lines[0], lines


def test_missing_before_object_is_red(repo, capsys):
    after = _commit(repo, NOREPLY)

    rc, level, lines = _run(repo, "push", {"before": "1234abcd" * 5, "after": after}, capsys)

    assert (rc, level) == (1, "error"), lines
    assert "before nesnesi depoda yok" in lines[0], lines


def test_empty_range_is_red(repo, capsys):
    after = _commit(repo, NOREPLY)

    rc, level, lines = _run(repo, "push", {"before": after, "after": after}, capsys)

    assert (rc, level) == (1, "error"), lines
    assert lines[0].startswith("aralik bos"), lines


def test_missing_event_payload_is_red(repo, capsys):
    rc = check.main(
        ["--repo", str(repo)],
        environ={"GITHUB_EVENT_NAME": "push", "GITHUB_EVENT_PATH": str(repo / "yok.json")},
    )

    out = capsys.readouterr().out
    assert rc == 1, out
    assert out.startswith("::error title=commit e-mail check::olay yuku okunamadi"), out
