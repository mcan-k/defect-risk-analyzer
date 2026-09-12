"""`llm_provider.py`'nin çağırdığı SDK yüzeyi, KURULU SDK'da gerçekten var mı?

NEDEN VAR. `tests/test_llm_provider.py` SDK'yı tamamen sahteliyor, ve bunu
bilerek yapıyor — docstring'i "keeps these tests independent of installed
packages ... entirely" diyor. Doğru bir karar, ama bedeli ölçüldü: o dosyadaki
sahte istemci `def create(**kwargs)` (satır 30), yani **her kwarg'ı kabul
eder**, SDK'dan kalkmış olanı dahil. Yapıcıyı test eden dördü ise
`monkeypatch.setitem(sys.modules, "groq", ...)` ile paketi baştan değiştiriyor.

Sonuç: 6D-4c'den önce `llm_provider.py` ile kurulu SDK arasındaki sözleşmeyi
ölçen **hiçbir şey yoktu**. İki major bump (groq 0.13 → 1.7, openai 1.58 → 3.13)
o boşluktan sessizce geçebilirdi. Bu dosya o boşluğu kapatıyor.

BEYAN — BU TESTİN DOĞAL KIRMIZISI YOK. "Kırmızıyı önce gözle" protokolü burada
uygulanmadı, çünkü uygulanamaz: bu test 6D-4c'nin taşıdığı iki major'dan ÖNCE de
SONRA da yeşil. Faz keşfinde ölçüldü — `model`, `messages`, `response_format`,
`temperature`, `max_tokens` ve `api_key`, ayrıca `choices[0].message.content`
zinciri, her iki SDK'nın yeni majorunda da duruyor. Yani **bu test bu bump'ı
yakalamıyor**, ve yakalamaması bir kusur değil, o ölçümün sonucu.

Kırmızısı yalnız MUTASYONLA gözlendi, iki yönde:
  - kaynak mutasyonu: bir `create(...)` çağrısına `foo=1` eklendi →
    `test_the_extractor_found_every_call_site` (küme değişti) ve
    `test_every_create_kwarg_exists_in_the_sdk_signature` (`foo` imzada yok)
    birlikte kırmızı.
  - test mutasyonu: `_create_call_sites()` `{}` döndürecek şekilde sakatlandı →
    `test_the_extractor_found_every_call_site` kırmızı.

Bu, `tests/test_dependency_pins.py`'nin gerekçe bekçisiyle aynı sınıf
(docs/KNOWN-DEBT.md:1262-1267) ve aynı dürüstlük borcunu taşıyor. Gizlenirse
"kontrat testimiz var, korunuyoruz" yanılgısı üretir.

AĞ YOK. İstemciler sahte anahtarla kuruluyor. Ölçüldü: `groq/_client.py` ve
openai'nin karşılığı yapıcıda yalnız `api_key is None` kontrolü yapıyor, ağa
çıkmıyor. Hiçbir istek gönderilmiyor — yalnızca `inspect.signature` okunuyor.
"""

import ast
import importlib
import inspect
import typing
from dataclasses import dataclass
from pathlib import Path

import pytest

PROVIDER_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "src" / "defect_risk_analyzer" / "llm_provider.py"
)

# `self._client.chat.completions.create(...)` — üretim kodunun yürüdüğü yol.
CREATE_PATH = ("chat", "completions", "create")


@dataclass(frozen=True)
class Provider:
    """Bir sağlayıcının iki ucu: kaynaktaki sınıf, kurulu paketteki istemci."""

    provider_class: str   # llm_provider.py'deki sınıf adı
    module: str           # import edilecek paket
    client: str           # paketten alınacak istemci sınıfı


PROVIDERS = [
    Provider(provider_class="GroqProvider", module="groq", client="Groq"),
    Provider(provider_class="OpenAIProvider", module="openai", client="OpenAI"),
]

# ---------------------------------------------------------------------------
# Bekçinin bekçisi için BEKLENEN değerler.
# ---------------------------------------------------------------------------
# Bunlar `llm_provider.py`'nin bugünkü hâlinden ELLE yazıldı, extractor'dan
# türetilmedi. Türetilseydi extractor'ın boş dönmesi sessizce geçerdi.
EXPECTED_CALL_SITES: dict[tuple[str, str], frozenset[str]] = {
    ("GroqProvider", "analyze"): frozenset(
        {"model", "messages", "response_format", "temperature", "max_tokens"}
    ),
    ("GroqProvider", "test_connection"): frozenset(
        {"model", "messages", "max_tokens"}
    ),
    ("OpenAIProvider", "analyze"): frozenset(
        {"model", "messages", "response_format", "temperature", "max_tokens"}
    ),
    ("OpenAIProvider", "test_connection"): frozenset(
        {"model", "messages", "max_tokens"}
    ),
}

EXPECTED_CONSTRUCTOR_KWARGS: dict[str, frozenset[str]] = {
    "GroqProvider": frozenset({"api_key"}),
    "OpenAIProvider": frozenset({"api_key"}),
}


# ===========================================================================
# AST yarısı — kaynakta ne çağrılıyor
# ===========================================================================

def _dotted(node: ast.AST) -> tuple[str, ...]:
    """`a.b.c` düğümünü ("a", "b", "c")'ye çevirir; çözülemezse boş demet."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    else:  # self.x gibi olmayan bir kök — bu dosyada beklenmiyor
        return ()
    return tuple(reversed(parts))


def _kwargs(call: ast.Call) -> frozenset[str]:
    """Çağrının anahtar kelime argüman adları. `**kwargs` yayılımı None gelir."""
    return frozenset(kw.arg for kw in call.keywords if kw.arg is not None)


def _walk_methods(tree: ast.Module):
    """(sınıf adı, metot adı, metot düğümü) üçlüleri."""
    for klass in ast.walk(tree):
        if not isinstance(klass, ast.ClassDef):
            continue
        for method in klass.body:
            if isinstance(method, ast.FunctionDef):
                yield klass.name, method.name, method


def _source_tree() -> ast.Module:
    return ast.parse(PROVIDER_SOURCE.read_text(encoding="utf-8"))


def _create_call_sites() -> dict[tuple[str, str], frozenset[str]]:
    """`*.chat.completions.create(...)` çağrılarının kwarg adları.

    Anahtar (sınıf, metot); değer o çağrının kwarg kümesi. Bir metotta birden
    fazla çağrı olsaydı birleşirlerdi — bugün yok, ve
    `test_the_extractor_found_every_call_site` tam kümeyi tuttuğu için bir gün
    olursa görünür olur.
    """
    sites: dict[tuple[str, str], set[str]] = {}
    for class_name, method_name, method in _walk_methods(_source_tree()):
        for node in ast.walk(method):
            if not isinstance(node, ast.Call):
                continue
            if _dotted(node.func)[-len(CREATE_PATH):] != CREATE_PATH:
                continue
            sites.setdefault((class_name, method_name), set()).update(_kwargs(node))
    return {key: frozenset(value) for key, value in sites.items()}


def _constructor_call_sites() -> dict[str, frozenset[str]]:
    """`Groq(...)` / `OpenAI(...)` çağrılarının kwarg adları, sınıf başına."""
    wanted = {provider.client: provider.provider_class for provider in PROVIDERS}
    sites: dict[str, set[str]] = {}
    for class_name, _method_name, method in _walk_methods(_source_tree()):
        for node in ast.walk(method):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id not in wanted:
                continue
            if wanted[node.func.id] != class_name:
                continue
            sites.setdefault(class_name, set()).update(_kwargs(node))
    return {key: frozenset(value) for key, value in sites.items()}


# ===========================================================================
# Runtime yarısı — kurulu SDK ne kabul ediyor
# ===========================================================================

def _sdk_client(provider: Provider):
    """Sahte anahtarla istemci. Ağa çıkmaz; yalnız imza okunacak."""
    module = importlib.import_module(provider.module)
    return getattr(module, provider.client)(api_key="not-a-real-key")


def _create_parameters(provider: Provider) -> inspect.Signature:
    return inspect.signature(_sdk_client(provider).chat.completions.create)


def _chat_completion_model(provider: Provider):
    return importlib.import_module(f"{provider.module}.types.chat").ChatCompletion


def _ids(provider: Provider) -> str:
    return provider.module


# ===========================================================================
# BEKÇİNİN BEKÇİLERİ — test mutasyonu bu ikisini kırmızıya çevirir
# ===========================================================================

def test_the_extractor_found_every_call_site():
    """Extractor'ın gerçekten bir şey bulduğunun kanıtı.

    Aşağıdaki imza testlerinin hepsi extractor'ın döndürdüğü kümeler üzerinde
    döner. Extractor boş dönerse o testler **hiçbir şey assert etmeden** yeşil
    kalır — `assert x <= y` boş `x` için doğrudur. Bu yüzden beklenen değerler
    yukarıda ELLE yazıldı ve burada TAM eşitlik aranıyor.

    Kaynak mutasyonu da burada yakalanır: bir `create(...)` çağrısına `foo=1`
    eklemek bu kümeyi değiştirir.
    """
    assert _create_call_sites() == EXPECTED_CALL_SITES, (
        "llm_provider.py'deki create() cagri yuzeyi degismis.\n"
        f"  beklenen: {dict(EXPECTED_CALL_SITES)}\n"
        f"  bulunan : {_create_call_sites()}\n"
        "Degisiklik kasitliysa EXPECTED_CALL_SITES guncellenir; degilse "
        "cagri yerinde bir hata var."
    )
    assert _constructor_call_sites() == EXPECTED_CONSTRUCTOR_KWARGS, (
        "llm_provider.py'deki SDK yapici cagrilari degismis.\n"
        f"  beklenen: {dict(EXPECTED_CONSTRUCTOR_KWARGS)}\n"
        f"  bulunan : {_constructor_call_sites()}"
    )


@pytest.mark.parametrize("provider", PROVIDERS, ids=_ids)
def test_the_sdk_signature_is_a_closed_set(provider: Provider):
    """`create` bir `**kwargs` yakalayıcısı taşımamalı.

    Taşısaydı aşağıdaki "her kwarg imzada var" testi BOŞ GEÇERDİ: `**kwargs`
    her adı kabul eder, dolayısıyla SDK'dan kalkmış bir parametre de imzada
    "varmış" gibi görünürdü. Faz keşfinde ölçüldü — groq 1.7.0 ve openai
    3.13.0'ın `create`'inde `**kwargs` yok. Bu test o ölçümü kalıcı kılıyor:
    bir gün eklenirse, sessizce izin verici hâle gelmek yerine kırmızı olur.
    """
    offenders = [
        name
        for name, parameter in _create_parameters(provider).parameters.items()
        if parameter.kind is inspect.Parameter.VAR_KEYWORD
    ]
    assert not offenders, (
        f"{provider.module}.{provider.client}.chat.completions.create bir "
        f"**kwargs yakalayicisi kazanmis ({offenders}). Bu testin asagidaki "
        "kardesi artik hicbir sey olcmuyor — imza tabanli kontrol yerine "
        "baska bir yontem gerekir."
    )


# ===========================================================================
# Asıl sözleşme — kaynağın çağırdığı, SDK'nın kabul ettiği
# ===========================================================================

@pytest.mark.parametrize("provider", PROVIDERS, ids=_ids)
def test_every_create_kwarg_exists_in_the_sdk_signature(provider: Provider):
    """Kaynaktaki her `create(...)` kwarg'ı kurulu SDK'da kabul edilmeli."""
    accepted = set(_create_parameters(provider).parameters)
    used = set().union(
        *(
            kwargs
            for (class_name, _method), kwargs in _create_call_sites().items()
            if class_name == provider.provider_class
        )
    )

    missing = used - accepted
    assert not missing, (
        f"llm_provider.py {provider.provider_class} icinde {sorted(missing)} "
        f"geciriyor ama {provider.module} {_installed_version(provider)} "
        "bunlari kabul etmiyor.\n"
        f"  kabul edilenler: {sorted(accepted)}"
    )


@pytest.mark.parametrize("provider", PROVIDERS, ids=_ids)
def test_the_constructor_accepts_api_key(provider: Provider):
    """`Groq(api_key=...)` / `OpenAI(api_key=...)` — Faz 6B'nin taşıyıcısı.

    Anahtar bu argümandan geçiyor; kalkarsa Ayarlar sayfasının "Bağlantıyı
    test et" düğmesi ekrandaki anahtar yerine kayıtlı olanı doğrulamaya geri
    döner — 6B'nin düzelttiği hatanın ta kendisi.
    """
    module = importlib.import_module(provider.module)
    accepted = set(inspect.signature(getattr(module, provider.client)).parameters)
    used = _constructor_call_sites()[provider.provider_class]

    missing = used - accepted
    assert not missing, (
        f"{provider.module}.{provider.client} artik {sorted(missing)} "
        f"kabul etmiyor (surum {_installed_version(provider)}).\n"
        f"  kabul edilenler: {sorted(accepted)}"
    )


@pytest.mark.parametrize("provider", PROVIDERS, ids=_ids)
def test_the_response_shape_survives(provider: Provider):
    """`response.choices[0].message.content` zinciri modelde durmalı.

    İmza tarafı bu zinciri göremez — `create` ne döndürdüğünü parametrelerinde
    yazmaz. Pydantic modellerinin alanları üzerinden yürünüyor: `ChatCompletion`
    → `choices: List[Choice]` → `message` → `content`. Bir halka kopsa
    `analyze()` bare `except Exception` içinde AttributeError'a düşer ve
    kullanıcıya LLMError olarak görünür — yani sessiz değil ama yanlış
    teşhisli bir hata. Bu test onu adıyla yakalar.
    """
    completion = _chat_completion_model(provider)

    assert "choices" in completion.model_fields, (
        f"{provider.module}: ChatCompletion.choices kalkmis"
    )

    (choice,) = typing.get_args(completion.model_fields["choices"].annotation)
    assert "message" in choice.model_fields, (
        f"{provider.module}: Choice.message kalkmis"
    )

    message = choice.model_fields["message"].annotation
    assert "content" in message.model_fields, (
        f"{provider.module}: Message.content kalkmis"
    )


def _installed_version(provider: Provider) -> str:
    """Hata mesajlarında hangi sürümün ölçüldüğünü söylemek için."""
    return getattr(importlib.import_module(provider.module), "__version__", "?")
