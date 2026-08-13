"""
Tests for llm_provider error mapping.

Both providers wrap their SDK call in a single `except Exception` and decide
between RateLimitError and LLMError by matching the error text. That branch
order is what these tests pin: a 429 must become RateLimitError, everything
else LLMError.

No network. The SDK is never contacted — providers are built with
object.__new__ to bypass __init__ (which would import the SDK and demand an
API key) and given a fake client that raises.
"""

import json
from types import SimpleNamespace

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

    __init__ imports the vendor SDK and reads config.<PROVIDER>_API_KEY. Neither
    is relevant to error mapping, and bypassing it keeps these tests independent
    of installed packages and configuration entirely.
    """
    provider = object.__new__(cls)
    provider._client = _client(error, content)
    provider._model = "test-model"
    return provider


PROVIDERS = [GroqProvider, OpenAIProvider]


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
# Rate limit detection
# ===========================================================================

@pytest.mark.parametrize("cls", PROVIDERS)
def test_http_429_maps_to_rate_limit_error(cls):
    """Both providers key off the literal "429" in the message."""
    provider = make_provider(cls, error=Exception("Error code: 429 - quota exceeded"))
    with pytest.raises(RateLimitError):
        provider.analyze("system", "user")


@pytest.mark.parametrize("cls", PROVIDERS)
def test_server_error_maps_to_llm_error(cls):
    provider = make_provider(cls, error=Exception("500 internal server error"))
    with pytest.raises(LLMError):
        provider.analyze("system", "user")


def test_groq_matches_underscore_rate_limit_form():
    """Groq checks for "rate_limit" (underscore), as in rate_limit_exceeded."""
    provider = make_provider(GroqProvider, error=Exception("rate_limit_exceeded"))
    with pytest.raises(RateLimitError):
        provider.analyze("system", "user")


def test_openai_matches_spaced_rate_limit_form():
    """OpenAI checks for "rate limit" (space)."""
    provider = make_provider(OpenAIProvider, error=Exception("Rate limit reached"))
    with pytest.raises(RateLimitError):
        provider.analyze("system", "user")


@pytest.mark.parametrize(
    ("cls", "message"),
    [
        # Groq looks for "rate_limit"; a spaced message without a 429 misses.
        (GroqProvider, "Rate limit reached"),
        # OpenAI looks for "rate limit"; an underscored message without a 429 misses.
        (OpenAIProvider, "rate_limit_exceeded"),
    ],
)
def test_providers_do_not_share_rate_limit_wording(cls, message: str):
    """Documents a real asymmetry, deliberately not papered over.

    Groq matches "rate_limit" and OpenAI matches "rate limit", so each misses
    the other's wording when the message carries no "429". Both then degrade to
    LLMError, which means no circuit breaker. Recorded as current behaviour;
    a fix belongs with the provider code, not with this test.
    """
    provider = make_provider(cls, error=Exception(message))
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
    provider = make_provider(
        GroqProvider, error=Exception("Error code: 429 - try again in 1m 30s")
    )
    with pytest.raises(RateLimitError) as excinfo:
        provider.analyze("system", "user")
    assert excinfo.value.retry_after_seconds == 90.0


def test_openai_rate_limit_error_uses_fixed_retry_after():
    """OpenAI does not parse a duration; it always reports 60 seconds."""
    provider = make_provider(OpenAIProvider, error=Exception("Error code: 429"))
    with pytest.raises(RateLimitError) as excinfo:
        provider.analyze("system", "user")
    assert excinfo.value.retry_after_seconds == 60.0
