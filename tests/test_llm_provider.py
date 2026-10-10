"""
Tests for llm_provider error mapping.

Both providers decide between RateLimitError and LLMError by the SDK's
exception TYPE: the SDK's own RateLimitError becomes ours, everything else
LLMError. Until phase 6D-4e they matched the error text instead ("429",
"rate_limit", "rate limit"), so any error that merely mentioned 429 tripped the
circuit breaker — a JSON decode error at "char 429" included. The tests below
pin both directions: a quiet SDK RateLimitError is a rate limit, and a loud
message is not.

No network. The SDK is never contacted — providers are built with
object.__new__ to bypass __init__ (which would demand an API key) and given a
fake client that raises. The exceptions it raises are real SDK instances, so
these tests do need the installed SDKs and their HTTP libraries.
"""

import json
from types import SimpleNamespace

import groq
import httpx
import httpx2
import openai
import pytest

from defect_risk_analyzer.llm_provider import (
    GroqProvider,
    LLMError,
    OpenAIProvider,
    RateLimitError,
)


def _client(error: Exception | None = None, content: str = "{}"):
    """Fake SDK client exposing just .chat.completions.create."""

    def create(**kwargs):
        if error is not None:
            raise error
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def make_provider(cls, error: Exception | None = None, content: str = "{}"):
    """Build a provider without running __init__.

    __init__ imports the vendor client and reads config.<PROVIDER>_API_KEY.
    Neither is relevant to error mapping, and bypassing it keeps these tests
    independent of configuration. Not of the installed SDK: `analyze` imports
    the SDK's RateLimitError itself.
    """
    provider = object.__new__(cls)
    provider._client = _client(error, content)
    provider._model = "test-model"
    return provider


PROVIDERS = [GroqProvider, OpenAIProvider]

# Each SDK with the HTTP library its exceptions are built on: openai 3.x moved
# to httpx2, groq is still on httpx.
SDKS = {GroqProvider: (groq, httpx), OpenAIProvider: (openai, httpx2)}

# Carries none of the words the old text matching looked for, so a test using
# it can only pass by the exception's type.
QUIET_MESSAGE = "quota gone"


def sdk_error(cls, name: str, message: str, status: int) -> Exception:
    """A real SDK exception of class `name`, built the way the SDK builds it."""
    sdk, http = SDKS[cls]
    request = http.Request("POST", "https://example.invalid/chat/completions")
    response = http.Response(status, request=request)
    return getattr(sdk, name)(message, response=response, body=None)


# ===========================================================================
# The type relationship the whole design rests on
# ===========================================================================

def test_rate_limit_error_is_not_a_subclass_of_llm_error():
    """These must stay independent exception types.

    Callers catch them separately and act differently: AnalysisService.analyze_bulk
    trips its circuit breaker on RateLimitError but merely skips one bug on
    LLMError. If RateLimitError ever became a subclass of LLMError, an
    `except LLMError` clause placed first would swallow every 429 and the
    breaker would stop tripping — silently.
    """
    assert not issubclass(RateLimitError, LLMError)
    assert not issubclass(LLMError, RateLimitError)


# ===========================================================================
# The fake client is actually reached
# ===========================================================================

@pytest.mark.parametrize("cls", PROVIDERS)
def test_successful_call_returns_parsed_json(cls):
    """Guards the negative tests below against a false pass.

    `analyze` catches bare Exception, so a malformed fake client would raise
    AttributeError inside the try and surface as LLMError — making the
    "maps to LLMError" cases pass without the branch ever being exercised.
    This proves the client plumbing is real.
    """
    provider = make_provider(cls, content=json.dumps({"reasoning": "ok"}))
    assert provider.analyze("system", "user") == {"reasoning": "ok"}


# ===========================================================================
# The fixture the type tests rest on
# ===========================================================================

@pytest.mark.parametrize("cls", PROVIDERS)
def test_the_sdk_error_factory_builds_the_real_class(cls):
    """Guards the rate limit tests below against a false pass.

    They prove "the type decides, not the text" only if the error really is
    the SDK's class with a 429 and its text carries none of the old trigger
    words. If either slipped, text matching would pass them too.
    """
    sdk, _http = SDKS[cls]
    error = sdk_error(cls, "RateLimitError", QUIET_MESSAGE, 429)

    assert type(error) is sdk.RateLimitError
    assert error.status_code == 429
    for word in ("429", "rate_limit", "rate limit"):
        assert word not in str(error).lower()


# ===========================================================================
# Rate limit detection — by the SDK's exception type
# ===========================================================================

@pytest.mark.parametrize("cls", PROVIDERS)
def test_sdk_rate_limit_error_maps_to_rate_limit_error(cls):
    error = sdk_error(cls, "RateLimitError", QUIET_MESSAGE, 429)
    provider = make_provider(cls, error=error)
    with pytest.raises(RateLimitError):
        provider.analyze("system", "user")


@pytest.mark.parametrize("cls", PROVIDERS)
def test_rate_limit_error_chains_the_sdk_error(cls):
    """`raise ... from e`: the SDK's error stays reachable as __cause__."""
    error = sdk_error(cls, "RateLimitError", QUIET_MESSAGE, 429)
    provider = make_provider(cls, error=error)
    with pytest.raises(RateLimitError) as excinfo:
        provider.analyze("system", "user")
    assert excinfo.value.__cause__ is error


@pytest.mark.parametrize("cls", PROVIDERS)
def test_server_error_maps_to_llm_error(cls):
    provider = make_provider(cls, error=Exception("500 internal server error"))
    with pytest.raises(LLMError):
        provider.analyze("system", "user")


@pytest.mark.parametrize("cls", PROVIDERS)
def test_sdk_server_error_mentioning_429_maps_to_llm_error(cls):
    """A 500 whose text says 429 is still a 500.

    Also the case that fails if the type check widens to APIStatusError,
    which every 4xx/5xx shares; the plain-Exception test above cannot see that.
    """
    error = sdk_error(cls, "InternalServerError", "upstream said 429", 500)
    provider = make_provider(cls, error=error)
    with pytest.raises(LLMError):
        provider.analyze("system", "user")


@pytest.mark.parametrize(
    "message", ["Error code: 429", "rate_limit_exceeded", "Rate limit reached"]
)
@pytest.mark.parametrize("cls", PROVIDERS)
def test_error_text_alone_never_means_rate_limit(cls, message: str):
    """The three wordings the old matching keyed on, for both providers.

    Before 6D-4e, Groq matched "rate_limit" and OpenAI "rate limit", so each
    missed the other's wording; that asymmetry is gone with the matching.
    """
    provider = make_provider(cls, error=Exception(message))
    with pytest.raises(LLMError):
        provider.analyze("system", "user")


@pytest.mark.parametrize("cls", PROVIDERS)
def test_json_decode_error_at_char_429_maps_to_llm_error(cls):
    """Measured before 6D-4e: this became RateLimitError on both providers.

    json.loads sits inside the same try, and its message names the position.
    """
    content = " " * 429 + "x"
    with pytest.raises(json.JSONDecodeError, match=r"\(char 429\)"):
        json.loads(content)

    provider = make_provider(cls, content=content)
    with pytest.raises(LLMError):
        provider.analyze("system", "user")


# ===========================================================================
# Retry-after extraction (Groq only; OpenAI hardcodes 60.0)
# ===========================================================================

@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("try again in 1m 30s", 90.0),    # minutes + seconds
        ("try again in 45s", 45.0),       # seconds only
        ("try again in 2.5s", 2.5),       # fractional seconds
        ("no duration here", 60.0),       # fallback
    ],
)
def test_groq_parses_retry_after(message: str, expected: float):
    assert GroqProvider._parse_retry_after(message) == expected


def test_groq_rate_limit_error_carries_retry_after():
    """The duration is still read from the text; only the detection moved."""
    error = sdk_error(GroqProvider, "RateLimitError", "Please try again in 1m 30s.", 429)
    provider = make_provider(GroqProvider, error=error)
    with pytest.raises(RateLimitError) as excinfo:
        provider.analyze("system", "user")
    assert excinfo.value.retry_after_seconds == 90.0


def test_openai_rate_limit_error_uses_fixed_retry_after():
    """OpenAI does not parse a duration; it always reports 60 seconds."""
    error = sdk_error(OpenAIProvider, "RateLimitError", QUIET_MESSAGE, 429)
    provider = make_provider(OpenAIProvider, error=error)
    with pytest.raises(RateLimitError) as excinfo:
        provider.analyze("system", "user")
    assert excinfo.value.retry_after_seconds == 60.0


# ===========================================================================
# Faz 6B — the key comes in as an argument, not out of the environment
# ===========================================================================
# WRITTEN BEFORE THE FIX. Measured on today's code (Ö-B): the Settings page
# writes the typed key into os.environ and then builds a provider — but the
# provider reads config.GROQ_API_KEY, a module global that only reload() ever
# writes, and that branch never calls reload(). So the write does nothing for
# the test it was meant to enable, AND it persists for the life of the process.
# Both halves are wrong, and an optional api_key argument closes both.

def test_an_explicit_key_reaches_the_provider(monkeypatch):
    """EXPECTED RED. The typed key must be the one used.

    Today there is no way to hand a provider a key: it reads the configured
    global, so "Test Connection" validates whatever was last SAVED rather than
    what is on screen. On a fresh install with nothing saved, typing a valid key
    and pressing the button reports "GROQ_API_KEY is not set in .env".
    """
    import defect_risk_analyzer.llm_provider as provider_module

    monkeypatch.setattr(provider_module.config, "GROQ_API_KEY", "saved-key")
    seen = {}

    class FakeGroq:
        def __init__(self, api_key):
            seen["api_key"] = api_key

    monkeypatch.setitem(
        __import__("sys").modules, "groq", SimpleNamespace(Groq=FakeGroq)
    )

    provider_module.GroqProvider(api_key="typed-key")

    assert seen["api_key"] == "typed-key"


def test_no_explicit_key_still_reads_the_configured_one(monkeypatch):
    """EXPECTED GREEN. The argument is optional, and its absence is the old path.

    Ö-C measured three callers of create_llm_provider; two pass no key and must
    keep working exactly as before. This is the guard that the new parameter is
    an addition rather than a replacement.
    """
    import defect_risk_analyzer.llm_provider as provider_module

    monkeypatch.setattr(provider_module.config, "GROQ_API_KEY", "saved-key")
    seen = {}

    class FakeGroq:
        def __init__(self, api_key):
            seen["api_key"] = api_key

    monkeypatch.setitem(
        __import__("sys").modules, "groq", SimpleNamespace(Groq=FakeGroq)
    )

    provider_module.GroqProvider()

    assert seen["api_key"] == "saved-key"


def test_the_factory_forwards_an_explicit_key(monkeypatch):
    """EXPECTED RED. create_llm_provider is what the Settings page calls."""
    import defect_risk_analyzer.llm_provider as provider_module

    monkeypatch.setattr(provider_module.config, "OPENAI_API_KEY", "saved-key")
    seen = {}

    class FakeOpenAI:
        def __init__(self, api_key):
            seen["api_key"] = api_key

    monkeypatch.setitem(
        __import__("sys").modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI)
    )

    provider_module.create_llm_provider("openai", api_key="typed-key")

    assert seen["api_key"] == "typed-key"


def test_building_a_provider_does_not_touch_the_environment(monkeypatch):
    """EXPECTED GREEN today, and it must STAY green after the fix.

    The second half of Ö-B. The leak was in the Settings page rather than here,
    but the fix moves the key through this constructor, so this is where the
    rule belongs: receiving a credential as an argument must not cause it to be
    written anywhere.
    """
    import os

    import defect_risk_analyzer.llm_provider as provider_module

    monkeypatch.setattr(provider_module.config, "GROQ_API_KEY", "saved-key")

    class FakeGroq:
        def __init__(self, api_key):
            pass

    monkeypatch.setitem(
        __import__("sys").modules, "groq", SimpleNamespace(Groq=FakeGroq)
    )

    before = dict(os.environ)
    provider_module.GroqProvider(api_key="typed-key")

    assert dict(os.environ) == before, "building a provider wrote to os.environ"
