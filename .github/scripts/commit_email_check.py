"""
Commit e-posta bekçisi: aralıktaki her commit'in yazar ve committer adresi
GitHub'ın noreply adresi olmalı.

İDDİA (Faz 6D-7a). Geçmişteki commit'lerin bir kısmı kişisel bir e-posta
adresi taşıyor ve geçmiş yeniden yazılmıyor (kullanıcı kararı, 2026-10-12).
Asıl koruma yerel ayar — depo düzeyinde `user.email` noreply — ve bu betik
onun tutup tutmadığını her PR'da ve her `main` push'unda denetler: yalnız
o olayın getirdiği commit'lere bakar, geçmişe değil.

ARALIK. Olay adı ve yükü runner'ın ortam değişkenlerinden okunur
(`GITHUB_EVENT_NAME`, `GITHUB_EVENT_PATH`); iş akışı `${{ }}` ile hiçbir
değeri komut satırına gömmez.

  * `pull_request`: `base.sha..head.sha`. Checkout'un HEAD'i GitHub'ın test
    merge'ü (`refs/pull/N/merge`); uç olay yükündeki `head.sha` olduğu için
    o merge aralığa girmez.
  * `push`: `before..after`. Web'den yapılan bir merge'ün push'unda aralık =
    PR'ın commit'leri + merge commit'i.

Merge commit'leri aralıkta sayılır. `git log --no-mailmap`: biçim `%ae`/`%ce`
ham adresi okur (git 2.51.2'de `.mailmap` onu `--use-mailmap` ile de
değiştirmedi, yalnız `%aE`'yi; ölçüldü), bayrak ikinci kat. Ad hiç okunmaz.

İZİN VERİLEN ADRESLER (kullanıcı kararı K2, 2026-10-16). Genel desen
`^(\\d+\\+)?[A-Za-z0-9-]+(\\[bot\\])?@users\\.noreply\\.github\\.com$` ve tam
olarak `noreply@github.com` (web'den yapılan commit'lerin committer'ı).
Desen tüm dizeye uygulanır (`fullmatch`): sondaki bir satır sonu da
reddedilir. Depoda hiçbir kullanıcı ID'si sabitlenmez; amaç gizlilik, kimlik
denetimi değil.

ÇIKTI. Sonuç tek bir GitHub annotation'ı, öteki CI betikleri gibi. Yeşilde
kaç commit'e bakıldığı; kırmızıda her kötü commit'in tam hash'i ve alanı
("yazar", "committer" ya da "yazar+committer"). **Adres de ad da asla
basılmaz** — olay yükündekiler (pusher, head_commit) dahil.

Bekçinin bekçisi (kullanıcı kararı K5, 2026-10-16): 40 sıfırlı bir uç (yeni
dal), depoda olmayan bir uç (force-push ya da sığ klon) ve boş aralık
kırmızıdır. Boş bir kontrol iyi haber değil — pip-audit kapısının ilkesi.

TESPİT, ÖNLEME DEĞİL. Bekçi koştuğunda commit zaten GitHub'da.
Ayrıntı: docs/KNOWN-DEBT.md, "Faz 6D-7a eki".

Ağsız ve bağımlılıksız: yalnız standart kütüphane ve git. Testler
`tests/test_commit_email_check.py`'de.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

TITLE = "commit e-mail check"
ZERO_SHA = "0" * 40
WEB_FLOW = "noreply@github.com"
LABELS = {"pull_request": ("base.sha", "head.sha"), "push": ("before", "after")}

_NOREPLY = re.compile(r"(\d+\+)?[A-Za-z0-9-]+(\[bot\])?@users\.noreply\.github\.com", re.ASCII)
_SHA = re.compile(r"[0-9a-f]{40}")


class CheckError(Exception):
    """Aralık hesaplanamıyor ya da girdi okunamıyor: bekçi bunu kırmızı sayar."""


def is_noreply(email: str) -> bool:
    return email == WEB_FLOW or _NOREPLY.fullmatch(email) is not None


def field(author_email: str, committer_email: str) -> str | None:
    """Noreply olmayan alan(lar): "yazar", "committer", "yazar+committer" ya da None."""
    bad = [
        name
        for name, email in (("yazar", author_email), ("committer", committer_email))
        if not is_noreply(email)
    ]
    return "+".join(bad) or None


def event_range(event_name: str, payload: Mapping) -> tuple[str, str]:
    """Olay yükünden (taban, uç); yalnız biçim denetlenir."""
    if event_name == "pull_request":
        pull = payload.get("pull_request") or {}
        shas = ((pull.get("base") or {}).get("sha"), (pull.get("head") or {}).get("sha"))
    elif event_name == "push":
        shas = (payload.get("before"), payload.get("after"))
    else:
        raise CheckError(f"desteklenmeyen olay: {event_name} (yalniz pull_request ve push)")
    for label, sha in zip(LABELS[event_name], shas, strict=True):
        if not isinstance(sha, str) or not _SHA.fullmatch(sha):
            raise CheckError(f"aralik hesaplanamiyor: olay yukunde gecerli bir {label} yok")
    return shas


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise CheckError(f"git calistirilamadi ({type(exc).__name__})") from exc


def range_commits(
    repo: Path, base: str, head: str, labels: tuple[str, str]
) -> list[tuple[str, str, str]]:
    """`base..head`'deki commit'ler: (hash, yazar adresi, committer adresi)."""
    for label, sha in zip(labels, (base, head), strict=True):
        if sha == ZERO_SHA:
            raise CheckError(
                f"aralik hesaplanamiyor: {label} 40 sifir (yeni ya da silinen dal); "
                "karsilastirilacak onceki uc yok"
            )
    for label, sha in zip(labels, (base, head), strict=True):
        if _git(repo, "cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
            raise CheckError(
                f"aralik hesaplanamiyor: {label} nesnesi depoda yok ({sha[:7]}); "
                "force-push ya da sig klon (checkout fetch-depth: 0 olmali)"
            )
    result = _git(repo, "log", "--no-mailmap", "--format=%H%x00%ae%x00%ce", f"{base}..{head}")
    if result.returncode != 0:
        raise CheckError(f"git log basarisiz (rc {result.returncode})")
    commits = []
    for number, line in enumerate(result.stdout.splitlines(), start=1):
        parts = line.split("\0")
        if len(parts) != 3 or not _SHA.fullmatch(parts[0]):
            # The line itself is not printed: it may carry an address.
            raise CheckError(f"git log ciktisinin {number}. satiri tanimsiz (icerik basilmaz)")
        commits.append((parts[0], parts[1], parts[2]))
    if not commits:
        raise CheckError(f"aralik bos: {base[:7]}..{head[:7]} hic commit vermedi")
    return commits


def load_event(environ: Mapping[str, str]) -> tuple[str, dict]:
    """Runner'ın ortam değişkenlerinden olay adı ve yükü."""
    name = environ.get("GITHUB_EVENT_NAME")
    path = environ.get("GITHUB_EVENT_PATH")
    if not name:
        raise CheckError("olay adi yok: GITHUB_EVENT_NAME tanimsiz")
    if not path:
        raise CheckError("olay yuku yok: GITHUB_EVENT_PATH tanimsiz")
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CheckError(f"olay yuku okunamadi ({type(exc).__name__})") from exc
    if not isinstance(payload, dict):
        raise CheckError("olay yuku okunamadi (JSON nesnesi degil)")
    return name, payload


def _escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "").replace("\n", "%0A")


def _annotate(level: str, lines: list[str]) -> None:
    # Same rule as the pip-audit gate: the title stays free of ':' and ','.
    print(f"::{level} title={_escape(TITLE)}::{_escape(chr(10).join(lines))}")


def main(argv: list[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--repo", type=Path, default=Path("."))
    args = parser.parse_args(argv)

    try:
        event, payload = load_event(os.environ if environ is None else environ)
        base, head = event_range(event, payload)
        commits = range_commits(args.repo, base, head, LABELS[event])
    except CheckError as exc:
        _annotate("error", [
            str(exc),
            "Bos ya da hesaplanamayan bir aralik iyi haber degil; bekci yesil gecmez.",
        ])
        return 1

    span = f"{event} {base[:7]}..{head[:7]}"
    red = [(sha, bad) for sha, author, committer in commits if (bad := field(author, committer))]
    if not red:
        _annotate("notice", [f"{len(commits)} commit, hepsi noreply ({span})"])
        return 0
    _annotate("error", [
        f"{len(red)} / {len(commits)} commit noreply olmayan bir adres tasiyor ({span}); "
        "adres ve ad basilmaz",
        *(f"{sha} {bad}" for sha, bad in red),
        "Duzeltme: CONTRIBUTING.md, 'Commit e-postasi'.",
    ])
    return 1


if __name__ == "__main__":
    sys.exit(main())
