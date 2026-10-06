"""
Bir pinin gerekçesi, pin kalktıktan sonra da tutulur.

TARİHÇE. Faz 6D-3a `requirements-dev.txt`'e `anyio==4.14.2` koydu: anyio 4.15.0
`anyio.abc`'nin geriye-uyum re-export'larını uyaran alias'lara çevirdi, ve
`starlette 1.6.0` `testclient.py:53`'te modül düzeyinde
`anyio.abc.BlockingPortal`'a dokunuyordu; CI'ın `pytest` çıktısında
`The anyio.abc.BlockingPortal alias is deprecated` beliriyordu. `starlette
1.7.0` o satırı `anyio.from_thread.BlockingPortal`'a çevirdi, KNOWN-DEBT'teki
tetikleyici ateşlendi ve pin Faz 6D-4d'de kalktı. Pinin literalini tutan
mutasyon bekçisi onunla birlikte silindi: tutacağı satır kalmadı.

KALAN TEK TEST NEYİ TUTUYOR. Uyarının yokluğunu — artık bir pinle değil,
`starlette`'in 1.7.0'ın altına inmemesiyle. `anyio` serbest çözülüyor;
`starlette` bir gün geri giderse (bir kısıt, bir yanlış pin, bir tavan) uyarı
geri gelir ve bu test kırmızıya döner.

BEYAN 1 — BU MAKİNEDE MUTASYON-GEÇİRMEZ. Kırmızısı yalnız `starlette 1.6.0` +
`anyio 4.15.x` bir ortamda mümkün. O ortam depo dışında taze bir venv'de
kuruldu ve kırmızı gözlendi; ölçüm docs/KNOWN-DEBT.md'de.

BEYAN 2 — ÖLÇEMEYEN TEST GEÇMEZ. Ölçüm alınamazsa — alt süreç sıfırdan farklı
döner, çıktısı JSON değildir, ya da `starlette.testclient` import edilemez —
test skip değil KIRMIZI olur (6D-4d kararı; o güne kadar üçü de skip'ti).
Beklenen tek gerçek durum Faz 6D-5: chromadb 1.x `fastapi`yi, dolayısıyla
`starlette`'i, runtime'dan `dev` extra'sına taşıyor. O PR bu testi bilerek
siler — koruyacağı şey kalmamıştır — ya da `starlette` başka bir yoldan
kuruluyorsa testi o kaynağa göre günceller. Skip'e çevirmek kararın tersidir.
Alt süreç ve JSON dallarının doğal bir kırmızısı yok; yalnız kod mutasyonuyla
gözlendiler.

BEYAN 3 — FİLTRENİN KÖR NOKTASI. Eleme mesaj bazlı (`"anyio.abc"` ve
`"deprecat"`). anyio uyarının metnini bu iki parçayı içermeyecek biçimde
değiştirirse test boşuna yeşil geçer. Bunu tutan bir test yok (6D-4d kararı);
filtrenin bugünkü mesajı gördüğü 6D-4d'de bir kez kanıtlandı: starlette 1.6.0
mutasyonu kırmızıydı.

BU DOSYA BİR YIĞINAK DEĞİL. Adı genel ve 6D-4d'den beri içinde pin yok; buraya
yeniden eklenen her pin kendi mutasyonunu gerektirir — gerekçesi ölçülmemiş
bir pin buraya girmez.
"""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

# The repo, not the config sandbox: conftest points every config path at a
# temporary directory, so the shipped tree is only reachable from here. Same
# reason as tests/test_entry_points.py and tests/test_known_debt_tally.py.
REPO_ROOT = Path(__file__).resolve().parents[1]


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

    6D-3a'dan 6D-4d'ye kadar bu test `anyio==4.14.2` pininin gerekçesini
    tutuyordu. Pin kalktı; test artık aynı yokluğu `starlette`'in 1.7.0 altına
    inmemesi üzerinden tutuyor. Ölçemezse kırmızı olur (modül docstring'i,
    BEYAN 2).

    FİLTRE KASTEN DAR — VE DARLIĞI 6D-4c'DE KARŞILIĞINI VERDİ. Assert "hiç
    uyarı yok" değildir. 6D-3a'dan 6D-4c'ye kadar beklenen ve kalması gereken
    ikinci bir uyarı vardı:

        StarletteDeprecationWarning: Using `httpx` with `starlette.testclient`
        is deprecated; install `httpx2` instead.

    **O uyarı 6D-4c'de kapandı ve filtre değişmedi** — istenen tam olarak
    buydu. `openai 3.13.0` `httpx2<3,>=2.7.0` istiyor, `starlette/testclient.py`
    ise önce `import httpx2` deniyor ve başarılı olunca uyarıyı hiç üretmiyor
    (`testclient.py:33-51`). Ölçüldü: `starlette.testclient.httpx` artık
    `httpx2 2.12.0` modülünün kendisi, ve CI'ın uyarı özeti boş.

    Geniş bir "DeprecationWarning'leri yok say" filtresi olsaydı bu kapanış
    görünmez olurdu ve test sessizce izin verici hâle gelirdi. Mesaj bazlı
    eleme — yalnızca `anyio.abc` alias'ını adlandıran uyarılar — o yüzden
    seçilmişti ve o yüzden **değiştirilmiyor**: bir gün üçüncü bir uyarı
    çıkarsa yine görünür olacak.
    """
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    # OLCEMEYEN TEST GECMEZ (Faz 6D-4d karari). Asagidaki uc assert 6D-4d'ye
    # kadar pytest.skip idi: olcum alinamazsa test sessizce atlaniyordu ve CI
    # yesil kaliyordu. Simdi uc dal da kirmizi - modul docstring'i, BEYAN 2.
    assert proc.returncode == 0, (
        f"olcum alt sureci {proc.returncode} ile dondu; uyari olculemedi.\n"
        f"--- stderr ---\n{proc.stderr.strip()[:500]}\n"
        "Bu test olcum yapamadiginda yesil ya da skip gecmez (Faz 6D-4d)."
    )

    lines = proc.stdout.strip().splitlines()
    try:
        result = json.loads(lines[-1]) if lines else None
    except ValueError:  # pragma: no cover
        result = None
    assert isinstance(result, dict), (
        "olcum alt sureci JSON cikti vermedi; uyari olculemedi.\n"
        f"--- stdout ---\n{proc.stdout.strip()[:500]}\n"
        "Bu test olcum yapamadiginda yesil ya da skip gecmez (Faz 6D-4d)."
    )

    # 6D-5 ISARETI. `starlette` buraya chromadb -> fastapi -> starlette
    # zincirinden geliyor; chromadb 1.x `fastapi`yi runtime'dan `dev`
    # extra'sina tasiyor (1.5.9'da olculdu). O gecis bu assert'u kirmiziya
    # cevirir - bilerek: testin olcecegi sey kalmaz, ve 6D-5'in PR'i testi ya
    # siler ya da starlette'in yeni kaynagina gore gunceller. Skip'e cevirmez.
    assert "import_error" not in result, (
        f"starlette.testclient import edilemedi ({result.get('import_error')}).\n"
        "Bu testin olcecegi sey kalmadi. Beklenen tek durum Faz 6D-5: chromadb "
        "1.x fastapi'yi (onunla starlette'i) runtime'dan dev extra'sina "
        "tasiyor. O PR bu testi bilerek silmeli ya da guncellemeli; skip'e "
        "cevirmeyin. docs/KNOWN-DEBT.md, anyio bolumu."
    )

    offenders = [
        w
        for w in result["warnings"]
        if "anyio.abc" in w["message"] and "deprecat" in w["message"].lower()
    ]
    assert not offenders, (
        "starlette.testclient import'u anyio.abc alias uyarisi uretti:\n"
        + "\n".join(f"  {w['category']}: {w['message']}" for w in offenders)
        + "\nstarlette 1.7.0'in altina inmis olabilir: 1.7.0 testclient.py:53'u "
        "anyio.from_thread.BlockingPortal'a cevirmisti. anyio pini Faz 6D-4d'de "
        "kaldirildi; geri koymadan once starlette'in neden geriledigine bakin "
        "(docs/KNOWN-DEBT.md, anyio bolumu)."
    )
