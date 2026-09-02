"""
`docs/KNOWN-DEBT.md`'nin lint bakiye cümlesi ölçümle eşleşmeli.

WHY. Bu satır üç turdur yanlış. Faz 5B'de ölçüldüğünde doğruydu. `anonymizer.py`
karantinası kaldırıldığında `pyproject.toml`'un yorumu güncellendi — "the
isolated E501 count stays at 9" diyor — ama KNOWN-DEBT'in özet satırı 5B
ölçümünde kaldı. 6C'de görüldü ve kapsam dışı bırakıldı. 6D-1 düzeltiyor.

Elle düzeltilen bir sayı dördüncü kez bayatlar, ve bayatladığında hiçbir şey
kırmızıya dönmez: belgeyi okuyan kişi yanlış sayıyı doğru sanar, ve bu depoda
aynı sınıf bu turda iki kez daha bedel ödetti (`desktop` extra'sı 23 yerde
yazılıp hiç beyan edilmemişti; `ROADMAP-v2.md:114-126` bayatlamıştı). Ödenen
bedel bir alt süreç çağrısından pahalı.

NE TUTULUYOR. Yalnız "bugünkü bakiye" cümlesindeki iki sayı ve toplamı. Aynı
paragraftaki 70 / 54 / 5 sayıları Faz 3 anındaki ölçümdür, belgenin kendisi
tarihsel kayıt olduklarını ve geriye dönük düzeltilmediklerini yazıyor — bu
bekçi onlara bakmaz.

ÖLÇÜM KARANTİNASIZ ALINIR. `ruff check .` bugün temiz; bakiye
`per-file-ignores` boşaltılarak ölçülür, yani belgede yazan sayı "karantinada
duran ihlal" sayısıdır, "CI'ın gördüğü" değil.

BEYAN EDİLMİŞ KÖR NOKTALAR:

  * Bekçi Türkçe bir cümleye regex'le bağlı. Cümle yeniden yazılırsa test
    kırmızıya döner — istenen davranış, ve `test_balance_sentence_is_findable`
    bunu çıplak bir `AssertionError` yerine ne yapılacağını söyleyen bir
    mesajla verir.
  * Dosya bazındaki döküm (`api_models.py` 4, ...) denetlenmiyor; yalnız
    toplamlar. Dökümü de tutmak, her satır sarmasında testi kırardı.
  * `ruff` yoksa ya da çalıştırılamıyorsa test atlanır, kırmızıya dönmez.
    Ölçüm aracının yokluğu belgenin yanlış olduğunu göstermez.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

# The repo, not the config sandbox — same reason as tests/test_entry_points.py.
REPO_ROOT = Path(__file__).resolve().parents[1]
KNOWN_DEBT = REPO_ROOT / "docs" / "KNOWN-DEBT.md"

# `**24 açık**` ve ardından `(9 E501 + 15 B904)`. Araya satır sonu girebilir:
# belgede bugün tam olarak öyle, cümle iki satıra sarıyor.
_BALANCE = re.compile(r"\*\*(\d+) açık\*\*\s*\((\d+) E501 \+ (\d+) B904\)")

# ruff --statistics satırı: "     9\tE501\tline-too-long"
_STAT_LINE = re.compile(r"^\s*(\d+)\s+([A-Z]+\d+)\s")


def _measured_counts() -> dict[str, int]:
    """`ruff`u karantinasız çalıştır, kural başına ihlal sayısını döndür."""
    command = [
        sys.executable, "-m", "ruff", "check", ".",
        "--config", "lint.per-file-ignores={}",
        "--statistics",
    ]
    try:
        proc = subprocess.run(
            command, cwd=REPO_ROOT, capture_output=True, text=True
        )
    except OSError as exc:  # pragma: no cover
        pytest.skip(f"ruff calistirilamadi: {exc}")

    # ruff ihlal bulduğunda 1 döner, temizken 0. Başka bir kod aracın kendi
    # sorunudur ve belgeyi kırmızıya çevirmemeli.
    if proc.returncode not in (0, 1):  # pragma: no cover
        pytest.skip(f"ruff beklenmeyen cikis kodu {proc.returncode}: {proc.stderr[:200]}")

    counts = {
        match.group(2): int(match.group(1))
        for match in (_STAT_LINE.match(line) for line in proc.stdout.splitlines())
        if match
    }

    # Çıkış 1 ama okunabilir istatistik yok: ruff kurulu değil ya da bozuk.
    # "İhlal bulundu" ile aynı çıkış kodunu paylaştığı için ayırt edilen tek yer.
    if proc.returncode == 1 and not counts:  # pragma: no cover
        pytest.skip(f"ruff calistirilamadi: {proc.stderr.strip()[:200]}")

    return counts


def _declared() -> tuple[int, int, int]:
    """Belgedeki (toplam, E501, B904) üçlüsü."""
    match = _BALANCE.search(KNOWN_DEBT.read_text(encoding="utf-8"))
    assert match is not None, (
        "docs/KNOWN-DEBT.md'de bakiye cumlesi bulunamadi. Beklenen bicim: "
        "'**<n> acik** (<n> E501 + <n> B904)'. Cumle yeniden yazildiysa "
        "tests/test_known_debt_tally.py'deki _BALANCE desenini de guncelle."
    )
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def test_declared_lint_balance_matches_ruff():
    """Belgedeki bakiye, bugün ölçülen bakiyeye eşit olmalı.

    Toplamın kendi içinde tutarlılığı da denetleniyor: iki sayıyı düzeltip
    toplamı güncellemeyi unutmak, bu satırın geçmişte bozulma biçimlerinden
    biriydi.
    """
    declared_total, declared_e501, declared_b904 = _declared()
    measured = _measured_counts()

    assert declared_total == declared_e501 + declared_b904, (
        f"belgedeki toplam kendi dokumuyle tutarsiz: "
        f"{declared_total} != {declared_e501} + {declared_b904}"
    )
    assert (declared_e501, declared_b904) == (
        measured.get("E501", 0),
        measured.get("B904", 0),
    ), (
        "docs/KNOWN-DEBT.md'nin bakiye cumlesi olcumden farkli. "
        f"belge: {declared_e501} E501 + {declared_b904} B904. "
        f"olculen: {measured.get('E501', 0)} E501 + {measured.get('B904', 0)} B904. "
        "Olcumu su komutla tekrarla: "
        'ruff check . --config "lint.per-file-ignores={}" --statistics'
    )
