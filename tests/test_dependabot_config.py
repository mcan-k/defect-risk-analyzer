"""
`dependabot.yml`'de ertelenen her paket, ertelenmesinin gerekçesiyle senkron
kalmalı.

WHY. Faz 6D-3c pip ekosistemini açıyor ama iki paketi `ignore` ile 6D-4'e
erteliyor: `chromadb` (0.5.23 → 1.5.9, MAJOR) ve `streamlit` (1.41.1 → 1.63.0).
İkisi de 6D-4'ün kontrollü yapmak istediği hareket, ve `chromadb` bump'ının
CI'da kırmızı olacağı ölçüldü — `tests.yml` `requirements-webhook.txt`'i
kurmuyor, chromadb 1.x ise `fastapi`yi runtime'dan `dev` extra'sına taşıyor.

ERTELEME KENDİ KENDİNİ HATIRLATMAZ. Bir `.yml` yorumunda "6D-4'te kaldır"
yazmak yeterli değil; 6D-4 biter, `ignore` girdileri unutulur ve iki paket
**kalıcı olarak donar** — üstelik sessizce, çünkü `ignore` GitHub belgelerine
göre güvenlik güncellemelerini de kesiyor ("...when it opens pull requests for
version updates and security updates"). Tam olarak kaçınılan sonuç. Bu dosya
tetikleyiciyi çalıştırılabilir hale getiriyor: 6D-4 `chromadb` pinini
oynattığı an test kırmızıya döner ve `ignore` girdisini silmeye zorlar.

NEDEN REGEX, NEDEN YAML DEĞİL. `PyYAML` bu depoda hiçbir yerde doğrudan
istenmiyor; `uvicorn[standard]` üzerinden transitif geliyor. Bir bekçiyi
transitif bir bağımlılığa bağlamak, bekçinin kendisini sürükleme riskine açar.
`test_known_debt_tally.py`'nin idiomu kullanılıyor: aranan şey bir desendir, ve
desen bulunamazsa test ne yapılacağını söyler.

BEYAN EDİLMİŞ KÖR NOKTA — TUTULAN ŞEY TUTARLILIK, VARLIK DEĞİL.

Döngü `dependabot.yml`'de **bulunan** adlar üzerinde dönüyor, aşağıdaki
`EXPECTED_IGNORED_PINS` tablosu üzerinde değil. Sonucu: bir ad `ignore`
listesinden **silinirse** test onu artık aramaz ve yeşil kalır.
`ignore: streamlit` sessizce silinse bu bekçi görmez (M3 mutasyonu bunu
gösteriyor; hayatta kalması **beklenen** sonuçtur, bir bulgu değil).

Bu bilerek böyle. Varlığı da tutmak, listeyi ikinci bir yerde elle sabitlemek
demekti; o zaman 6D-4'te iki yer birden güncellenmek zorunda kalır ve testin
asıl iddiası — "girdi ile pin senkron mu" — bulanırdı. Ayrıca bir adı listeden
silmek zararsız yönde bir hata: paket donmaktan çıkar, Dependabot onu bump
etmeye başlar. Donmuş kalması ise sessiz ve zararlıdır, tutulan yön o.
Gizlenirse "bekçimiz var, korunuyoruz" yanılgısı üretir — bu yüzden burada
yazılı; aynı idiom `test_dependency_pins.py`'de.
"""

import re
from pathlib import Path

# The repo, not the config sandbox: conftest points every config path at a
# temporary directory, so the shipped tree is only reachable from here. Same
# reason as tests/test_entry_points.py and tests/test_known_debt_tally.py.
REPO_ROOT = Path(__file__).resolve().parents[1]
DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"

# Faz 6D-3c'de ölçülen ve ertelenen paketler: ad → o adı taşıyan gereksinim
# dosyası ve beklenen literal. Erteleme bu literale bağlı; literal değişirse
# erteleme gerekçesini kaybeder.
EXPECTED_IGNORED_PINS = {
    "chromadb": ("requirements.txt", "chromadb==0.5.23"),
    "streamlit": ("requirements.txt", "streamlit==1.41.1"),
}

# `  - package-ecosystem: pip` ile başlayan blok, bir sonraki
# `  - package-ecosystem:` satırına ya da dosya sonuna kadar.
_ECOSYSTEM_BLOCK = re.compile(
    r"^[ \t]*-[ \t]*package-ecosystem:[ \t]*[\"']?(?P<name>[\w-]+)[\"']?[ \t]*$"
    r"(?P<body>.*?)"
    r"(?=^[ \t]*-[ \t]*package-ecosystem:|\Z)",
    re.MULTILINE | re.DOTALL,
)

# Blok içindeki `- dependency-name: "x"` satırları. Bu yapılandırmada
# `dependency-name` yalnız `ignore` altında geçiyor; `allow` kullanılmıyor.
_DEPENDENCY_NAME = re.compile(
    r"^[ \t]*-[ \t]*dependency-name:[ \t]*[\"']?(?P<name>[^\"'\s#]+)[\"']?",
    re.MULTILINE,
)


def _ecosystem_blocks() -> dict[str, str]:
    """`dependabot.yml`'deki her ekosistem girdisi: ad → gövde metni."""
    text = DEPENDABOT.read_text(encoding="utf-8")
    return {m.group("name"): m.group("body") for m in _ECOSYSTEM_BLOCK.finditer(text)}


def test_pip_ecosystem_entry_still_exists():
    """`pip` girdisi silinirse Dependabot pip'i sessizce izlemeyi bırakır.

    Silinen bir yapılandırma satırı hiçbir şeyi kırmıyor: CI yeşil kalır,
    PR'lar gelmemeye başlar ve bunu kimse fark etmez. Bu depo bu sınıfın
    bedelini `desktop` extra'sında ödedi — 23 yerde adı geçen, hiç beyan
    edilmemiş bir extra.
    """
    blocks = _ecosystem_blocks()
    assert "pip" in blocks, (
        ".github/dependabot.yml'de `- package-ecosystem: pip` girdisi yok. "
        "Faz 6D-3c onu ekledi; silinmesi Dependabot'un 14 `==` pinini izlemeyi "
        "sessizce birakmasi demektir. Kasitli bir kaldirma ise bu testi ve "
        "docs/KNOWN-DEBT.md'deki 6D-3c girdilerini de kaldirin."
    )


def test_every_ignored_dependency_still_carries_its_recorded_pin():
    """`ignore` edilen her ad, ertelenmesinin dayandığı literali taşımalı.

    İDDİA: `dependabot.yml`'de ertelenen paket ile `requirements*.txt`'teki pin
    senkron. 6D-4 `chromadb`'yi bump ettiği an bu senkron bozulur ve test
    kırmızıya döner — bu bir engel değil, **tetikleyicinin kendisidir**.

    Kör nokta modül docstring'inde: döngü dosyada bulunan adlar üzerinde döner,
    tabloda kalanlar üzerinde değil.
    """
    body = _ecosystem_blocks().get("pip", "")
    ignored = [m.group("name") for m in _DEPENDENCY_NAME.finditer(body)]

    for name in ignored:
        assert name in EXPECTED_IGNORED_PINS, (
            f"dependabot.yml'de `{name}` ignore ediliyor ama bu testte kayitli "
            "bir gerekcesi yok. Her erteleme, dayandigi pin literaliyle birlikte "
            "EXPECTED_IGNORED_PINS'e yazilir ve gerekcesi docs/KNOWN-DEBT.md'ye "
            "gecer; gerekcesi olmayan bir erteleme sessizce kalicilasir."
        )
        filename, expected = EXPECTED_IGNORED_PINS[name]
        text = (REPO_ROOT / filename).read_text(encoding="utf-8")
        assert expected in text, (
            f"`{name}` .github/dependabot.yml'de ignore ediliyor, ama "
            f"{filename} artik `{expected}` tasimiyor.\n"
            f"BUMP YAPILDIYSA dependabot.yml'deki `dependency-name: \"{name}\"` "
            "girdisini de SILIN. Girdi kalirsa paket kalici olarak donar ve "
            "guvenlik guncellemeleri de susmaya devam eder — GitHub belgeleri: "
            "ignore, surum ve guvenlik guncellemelerinin ikisini birden keser. "
            "Erteleme Faz 6D-3c'nin karari ve 6D-4'te kalkmak uzere konuldu; "
            "gerekcesi docs/KNOWN-DEBT.md'de."
        )
