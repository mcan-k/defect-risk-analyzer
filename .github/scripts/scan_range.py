"""
Gizli bilgi taramasının aralığı — commit e-posta bekçisinin aralığının aynısı.

İDDİA (Faz 6D-7b). "Secret scan" job'u gitleaks'i yalnız olayın getirdiği
commit'lere uygular, ve o aralık 6D-7a'nın bekçisiyle aynı hesapla bulunur:
`pull_request`'te `base.sha..head.sha`, `push`'ta `before..after`. Hesap
burada yeniden yazılmıyor; `commit_email_check.py`'nin işlevleri
(`load_event`, `event_range`, `range_commits`) olduğu gibi çağrılıyor. İki
job'un aralığı bu yüzden ayrışamaz, ve kenar durumların gerekçesi de orada,
o betiğin docstring'inde.

ÇIKTI. Aralık tarama adımına `GITHUB_ENV` ile geçer, dört satır:

  * `SCAN_EVENT` — `pull_request` ya da `push`;
  * `SCAN_BASE`, `SCAN_HEAD` — aralığın tabanı ve ucu, 40 küçük harf hex;
    tarama adımı `--log-opts`'u bunlardan kurar;
  * `SCAN_COUNT` — aralıktaki commit sayısı (merge'ler dahil), pozitif.

YAZMADAN ÖNCE DOĞRULAMA (Faz 6D-7b, denetleyici şartı). `GITHUB_ENV`'e
yazılan bir satır sonraki adımların ortamı olur; içine bir satır sonu giren
bir değer ikinci bir değişken tanımlayabilirdi. Bu yüzden `env_lines` her
değeri kendi deseniyle tam eşleşmeyle (`fullmatch`) denetler, anahtar
kümesinin tam bu dört ad olduğunu ister, ve yazma yalnız onun çıktısıyla
yapılır. Desenler satır sonuna, boşluğa, `=`'e ya da başka bir ayırıcıya
izin vermez; satırın tek ayırıcısı ilk `=`. Değerler bugün zaten
`event_range`'den denetlenmiş geliyor (`commit_email_check.py`, `_SHA`); bu
denetim o bağa güvenmiyor. Tutmazsa kırmızı ve değişkenin adı; değer
basılmaz.

Bekçinin bekçisi (kullanıcı kararı K5, 2026-10-16; tarayıcı için de): 40
sıfırlı uç, depoda olmayan uç ve boş aralık kırmızı, ve kırmızıda
`GITHUB_ENV`'e hiçbir şey yazılmaz. `GITHUB_ENV` tanımsızsa da kırmızı:
aralık tarama adımına ulaşamaz. Tarama adımı taban ve ucu ayrıca yeniden
denetler — boş bir `--log-opts` bütün geçmişi tarardı.

`range_commits` yazar ve committer adresini de okur; bu betik onları
kullanmaz ve basmaz. Yeşilde hiçbir şey basılmaz; bildirimi tarama adımı
verir.

Ağsız ve bağımlılıksız: yalnız standart kütüphane ve git. Testler
`tests/test_scan_range.py`'de.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path

from commit_email_check import LABELS, CheckError, event_range, load_event, range_commits

TITLE = "secret scan"

# Every value written to GITHUB_ENV, and the only shape it may have.
_VALUES = {
    "SCAN_EVENT": re.compile(r"pull_request|push"),
    "SCAN_BASE": re.compile(r"[0-9a-f]{40}"),
    "SCAN_HEAD": re.compile(r"[0-9a-f]{40}"),
    "SCAN_COUNT": re.compile(r"[1-9][0-9]*"),
}


def env_lines(values: Mapping[str, str]) -> str:
    """`GITHUB_ENV` satırları; her değer önce kendi deseniyle denetlenir."""
    for name in sorted(set(values) | set(_VALUES)):
        value = values.get(name)
        pattern = _VALUES.get(name)
        if pattern is None or not isinstance(value, str) or not pattern.fullmatch(value):
            # The value itself is not printed: it is what failed the check.
            raise CheckError(f"GITHUB_ENV'e yazilmadi: {name} beklenen bicimde degil")
    return "".join(f"{name}={values[name]}\n" for name in _VALUES)


def _escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "").replace("\n", "%0A")


def main(argv: list[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--repo", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    env = os.environ if environ is None else environ

    try:
        target = env.get("GITHUB_ENV")
        if not target:
            raise CheckError("GITHUB_ENV tanimsiz: aralik tarama adimina aktarilamaz")
        event, payload = load_event(env)
        base, head = event_range(event, payload)
        commits = range_commits(args.repo, base, head, LABELS[event])
        lines = env_lines({
            "SCAN_EVENT": event,
            "SCAN_BASE": base,
            "SCAN_HEAD": head,
            "SCAN_COUNT": str(len(commits)),
        })
    except CheckError as exc:
        message = "\n".join([
            str(exc),
            "Bos ya da hesaplanamayan bir aralik iyi haber degil; tarama yesil gecmez.",
        ])
        # Same rule as the other CI scripts: the title stays free of ':' and ','.
        print(f"::error title={TITLE}::{_escape(message)}")
        return 1

    with open(target, "a", encoding="utf-8", newline="\n") as out:
        out.write(lines)
    return 0


if __name__ == "__main__":
    sys.exit(main())
