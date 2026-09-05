"""
Gerekçesi ölçülmüş bir sürüm pini, gerekçesiyle birlikte tutulur.

WHY. `anyio` 4.15.0 `anyio` ve `anyio.abc` modüllerini tembel importa çevirdi ve
geriye-uyum re-export'larını uyaran alias'lara dönüştürdü. `starlette 1.6.0`
`testclient.py:53`'te modül düzeyinde `anyio.abc.BlockingPortal`'a dokunuyor, bu
yüzden CI'ın `pytest` çıktısında `The anyio.abc.BlockingPortal alias is
deprecated` uyarısı beliriyor. 4.14.2'de aynı ad düz bir re-export
(`from ..from_thread import BlockingPortal as BlockingPortal`), yani uyarı orada
fiziksel olarak imkânsız. Faz 6D-3a `requirements-dev.txt`'e `anyio==4.14.2`
koyarak uyarıyı kaldırıyor.

Pinin kendisi tek satır. Tek satırın sorunu, sessizce kaldırılabilmesi: altı ay
sonra biri satırı siler, CI yeşil kalır, uyarı geri gelir ve kimse görmez. Bu
depo bu sınıfın bedelini iki kez ödedi — `desktop` extra'sı 23 yerde yazılıp hiç
beyan edilmemişti, KNOWN-DEBT'in lint bakiyesi üç tur yanlış kaldı.

İKİ TEST, İKİ AYRI İŞ — VE BİRİ ÖTEKİNİN YERİNİ TUTMUYOR.

  * `test_requirements_dev_still_carries_the_expected_anyio_pin` =
    **mutasyon bekçisi**. Pin satırının beklenen literal olduğunu doğrular.
    Ağsız, alt süreçsiz, her makinede aynı sonucu verir; "pini sil" ve "pini
    4.15.1 yap" mutasyonlarının ikisinde de kırmızıya döner.
  * `test_starlette_testclient_emits_no_anyio_alias_deprecation` =
    **gerekçe bekçisi**. Pinin ne için konduğunu tutar: uyarının yokluğu.

BEYAN EDİLMİŞ: GEREKÇE BEKÇİSİ BU MAKİNEDE MUTASYON-GEÇİRMEZ. İkinci test
"pini sil" mutasyonundan **sağ çıkar**, çünkü mutasyon yalnız bir metin
dosyasını değiştirir — kurulu `anyio` yerinde kalır ve burada zaten 4.15
öncesidir, dolayısıyla kırmızı fiziksel olarak imkânsızdır. Bu bir kusur değil,
iki testin farklı şeyi tutmasının sonucu; ama gizlenirse ileride "iki testimiz
var, korunuyoruz" yanılgısı üretir. Birleşik takım mutasyon protokolünü
**yalnız birinci test sayesinde** geçiyor. İkinci testin kırmızısı geçici bir
venv'de (`anyio==4.15.1`) gözlendi; ölçüm docs/KNOWN-DEBT.md'de.

BU DOSYA BİR YIĞINAK DEĞİL. Adı genel, ama buraya eklenen her yeni pin kendi
mutasyonunu gerektirir — gerekçesi ölçülmemiş bir pin buraya girmez.
"""

import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# The repo, not the config sandbox: conftest points every config path at a
# temporary directory, so the shipped tree is only reachable from here. Same
# reason as tests/test_entry_points.py and tests/test_known_debt_tally.py.
REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS_DEV = REPO_ROOT / "requirements-dev.txt"

# Faz 6D-3a'da ölçülen ve dosyaya yazılan satır. Değiştirmek, ölçümü
# tekrarlamayı gerektirir — docstring'e bakın.
EXPECTED_ANYIO_PIN = "anyio==4.14.2"

# Yorum satırlarını ve boşluğu atlayarak `anyio` gereksinim satırını bulur.
# `test_known_debt_tally.py`'nin regex idiomu: belgede/dosyada aranan şey bir
# desendir, ve desen bulunamazsa test ne yapılacağını söyler.
_ANYIO_REQUIREMENT = re.compile(r"^\s*(anyio\b[^\s#]*)", re.MULTILINE)


def _anyio_requirement_line() -> str:
    """`requirements-dev.txt`'teki `anyio` gereksinim spec'i, ham metin."""
    text = REQUIREMENTS_DEV.read_text(encoding="utf-8")
    match = _ANYIO_REQUIREMENT.search(text)
    assert match is not None, (
        "requirements-dev.txt'te bir `anyio` gereksinim satiri bulunamadi. "
        f"Beklenen: `{EXPECTED_ANYIO_PIN}`. Pin, starlette.testclient'in "
        "anyio.abc.BlockingPortal alias'ini tetiklemesini onlemek icin var "
        "(Faz 6D-3a); silinmeden once docs/KNOWN-DEBT.md'deki tetikleyiciye "
        "bakin."
    )
    return match.group(1)


def test_requirements_dev_still_carries_the_expected_anyio_pin():
    """Pin satırı **beklenen literal** olmalı.

    İDDİA KASTEN DAR. Bu test düz metin karşılaştırması yapar, dolayısıyla
    literal bir iddia taşır: satır tam olarak `anyio==4.14.2` mi. "Spec 4.15+'ı
    dışlıyor" demek semantik bir iddia olurdu ve düz metin karşılaştırması onu
    vermez; vermek için `packaging` ile spec cebiri gerekirdi, ki bu testin işi
    o değil ve yeni bir bağımlılık gerektirir. Semantiği tutan, aşağıdaki ikinci
    testtir.

    Bu daraltma testi zayıflatmıyor: ölçülen ve yazılan tek bir sürüm var, ve
    pinin `4.15.1`'e çevrilmesi de silinmesi kadar kırmızı vermeli. İkisi ayrı
    mutasyon olarak denendi.
    """
    assert _anyio_requirement_line() == EXPECTED_ANYIO_PIN, (
        f"requirements-dev.txt'teki anyio pini beklenen literal degil.\n"
        f"  dosyada: {_anyio_requirement_line()}\n"
        f"  beklenen: {EXPECTED_ANYIO_PIN}\n"
        "anyio 4.15.0 anyio.abc'yi tembel importa cevirdi ve "
        "starlette/testclient.py:53 uyaran alias'i tetikliyor. Pini yukseltmek "
        "CI'a `The anyio.abc.BlockingPortal alias is deprecated` uyarisini geri "
        "getirir. Kaldirma tetikleyicisi docs/KNOWN-DEBT.md'de."
    )


# Alt süreçte koşan gerekçe bekçisi. `tests/test_core_boundary.py` ve
# `tests/test_known_debt_tally.py` ile aynı idiom: ölçüm taze bir yorumlayıcıda
# alınır, çünkü bir uyarı modül başına yalnız bir kez ateşlenir ve
# `starlette.testclient` bu takımda `tests/test_api_auth.py` tarafından zaten
# import edilmiş olabilir.
_PROBE = textwrap.dedent(
    """
    import json, sys, warnings

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            import starlette.testclient  # noqa: F401
        except Exception as exc:
            print(json.dumps({"import_error": f"{type(exc).__name__}: {exc}"}))
            sys.exit(0)

    print(json.dumps({"warnings": [
        {"category": w.category.__name__, "message": str(w.message)}
        for w in caught
    ]}))
    """
)


def test_starlette_testclient_emits_no_anyio_alias_deprecation():
    """`starlette.testclient` import'u anyio alias uyarısı üretmemeli.

    Bu, pinin **gerekçesini** tutan test: satırın varlığını değil, satırın var
    olma nedenini ölçer.

    FİLTRE KASTEN DAR — 6D-4 İŞARETİ. Assert "hiç uyarı yok" değildir. Bugün
    beklenen ve **kalması gereken** ikinci bir uyarı var:

        StarletteDeprecationWarning: Using `httpx` with `starlette.testclient`
        is deprecated; install `httpx2` instead.

    O uyarı ayrı bir kaynaktan (`testclient.py:40-51`) geliyor, 6D-3a onu
    kaldırmıyor ve sahibi **6D-4**. Bu yüzden eleme mesaj bazında yapılıyor:
    yalnızca `anyio.abc` alias'ını adlandıran uyarılar aranıyor. Geniş bir
    "DeprecationWarning'leri yok say" filtresi, 6D-4 httpx2'yi çözdüğünde ya da
    üçüncü bir uyarı çıktığında bu testi sessizce izin verici hale getirirdi.
    """
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    if proc.returncode != 0:  # pragma: no cover
        pytest.skip(f"alt surec calistirilamadi: {proc.stderr.strip()[:200]}")

    try:
        result = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):  # pragma: no cover
        pytest.skip(f"alt surec cikti veremedi: {proc.stdout.strip()[:200]}")

    if "import_error" in result:  # pragma: no cover
        # 6D-4 İŞARETİ. `starlette` buraya chromadb -> fastapi -> starlette
        # zincirinden geliyor. chromadb 1.5.9 `fastapi`yi runtime'dan `dev`
        # extra'sina tasidi; 6D-4'un chromadb bump'i sonrasi `starlette`
        # requirements-dev.txt'in kapanisindan dusebilir. O an bu test sessizce
        # atlanir, birinci test yesil kalir ve pin gerekcesiz bir kisit olarak
        # dosyada kalir.
        pytest.skip(
            f"starlette import edilemedi ({result['import_error']}). "
            "starlette kapanistan dustuyse requirements-dev.txt'teki anyio pini "
            "gerekcesini kaybetmis olabilir — 6D-4'te kontrol edilecek."
        )

    offenders = [
        w
        for w in result["warnings"]
        if "anyio.abc" in w["message"] and "deprecat" in w["message"].lower()
    ]
    assert not offenders, (
        "starlette.testclient import'u anyio.abc alias uyarisi uretti:\n"
        + "\n".join(f"  {w['category']}: {w['message']}" for w in offenders)
        + "\nrequirements-dev.txt'teki `anyio==4.14.2` pini kalkmis ya da "
        "cozunurlukte etkisiz kalmis olabilir (Faz 6D-3a)."
    )
