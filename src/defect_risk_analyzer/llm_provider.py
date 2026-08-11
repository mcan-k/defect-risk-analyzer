"""
BYOK LLM Provider — Strategy Pattern for multi-provider support.

Abstract base class `LLMProvider` with concrete implementations:
  - GroqProvider  (llama-3.3-70b-versatile)
  - OpenAIProvider (gpt-4o-mini)

Both enforce JSON output mode. Selection via LLM_PROVIDER env var.
Adding a new provider (e.g., Anthropic, Ollama) = one new class + register in factory.
"""

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any

from defect_risk_analyzer import config

logger = logging.getLogger(__name__)


# =============================================================================
# Custom Exceptions
# =============================================================================

class RateLimitError(Exception):
    """Raised when the LLM provider returns a 429 rate limit error."""

    def __init__(self, message: str, retry_after_seconds: float = 0) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class LLMError(Exception):
    """General LLM provider error."""
    pass


# =============================================================================
# Abstract Base Class
# =============================================================================

class LLMProvider(ABC):
    """Abstract LLM provider interface."""

    @abstractmethod
    def analyze(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """
        Send prompts to the LLM and return parsed JSON response.

        Args:
            system_prompt: System-level instructions for the LLM.
            user_prompt: User-level prompt with bug data and statistics.

        Returns:
            Parsed JSON dict with risk analysis results.

        Raises:
            RateLimitError: On 429 responses.
            LLMError: On other provider errors.
        """
        ...

    @abstractmethod
    def test_connection(self) -> bool:
        """Test if the provider is reachable with valid credentials."""
        ...


# =============================================================================
# Groq Provider
# =============================================================================

class GroqProvider(LLMProvider):
    """Groq LLM provider using llama-3.3-70b-versatile."""

    def __init__(self) -> None:
        try:
            from groq import Groq
        except ImportError:
            raise LLMError("groq package is not installed. Run: pip install groq")

        api_key = config.GROQ_API_KEY
        if not api_key:
            raise LLMError("GROQ_API_KEY is not set in .env")

        self._client = Groq(api_key=api_key)
        self._model = config.get_llm_model()

    def analyze(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """Send analysis request to Groq with JSON mode enforced."""
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=2000,
            )
            content = response.choices[0].message.content
            return json.loads(content)

        except Exception as e:
            error_msg = str(e)

            # Detect 429 rate limit and extract retry duration
            if "429" in error_msg or "rate_limit" in error_msg.lower():
                retry_seconds = self._parse_retry_after(error_msg)
                logger.warning(
                    "Groq rate limit hit. Retry after %.1f seconds.", retry_seconds
                )
                raise RateLimitError(
                    f"Groq rate limit exceeded: {error_msg}",
                    retry_after_seconds=retry_seconds,
                )

            logger.error("Groq API error: %s", error_msg)
            raise LLMError(f"Groq API error: {error_msg}")

    def test_connection(self) -> bool:
        """Test Groq connection with a minimal request."""
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": "Say OK"}],
                max_tokens=5,
            )
            return bool(response.choices[0].message.content)
        except Exception as e:
            logger.error("Groq connection test failed: %s", e)
            return False

    @staticmethod
    def _parse_retry_after(error_message: str) -> float:
        """
        Extract retry duration from Groq error messages.
        Handles formats like: "try again in 1m 30s", "try again in 45s"
        """
        total_seconds = 60.0  # Default fallback

        # Pattern: Xm Ys or Xs
        match = re.search(r"(\d+)m\s*(\d+\.?\d*)s", error_message)
        if match:
            minutes = int(match.group(1))
            seconds = float(match.group(2))
            return minutes * 60 + seconds

        match = re.search(r"(\d+\.?\d*)s", error_message)
        if match:
            return float(match.group(1))

        return total_seconds


# =============================================================================
# OpenAI Provider
# =============================================================================

class OpenAIProvider(LLMProvider):
    """OpenAI LLM provider using gpt-4o-mini."""

    def __init__(self) -> None:
        try:
            from openai import OpenAI
        except ImportError:
            raise LLMError("openai package is not installed. Run: pip install openai")

        api_key = config.OPENAI_API_KEY
        if not api_key:
            raise LLMError("OPENAI_API_KEY is not set in .env")

        self._client = OpenAI(api_key=api_key)
        self._model = config.get_llm_model()

    def analyze(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """Send analysis request to OpenAI with JSON mode enforced."""
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=2000,
            )
            content = response.choices[0].message.content
            return json.loads(content)

        except Exception as e:
            error_msg = str(e)

            if "429" in error_msg or "rate limit" in error_msg.lower():
                logger.warning("OpenAI rate limit hit.")
                raise RateLimitError(
                    f"OpenAI rate limit exceeded: {error_msg}",
                    retry_after_seconds=60.0,
                )

            logger.error("OpenAI API error: %s", error_msg)
            raise LLMError(f"OpenAI API error: {error_msg}")

    def test_connection(self) -> bool:
        """Test OpenAI connection with a minimal request."""
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": "Say OK"}],
                max_tokens=5,
            )
            return bool(response.choices[0].message.content)
        except Exception as e:
            logger.error("OpenAI connection test failed: %s", e)
            return False


# =============================================================================
# Factory Function
# =============================================================================

_PROVIDERS: dict[str, type[LLMProvider]] = {
    "groq": GroqProvider,
    "openai": OpenAIProvider,
}


def create_llm_provider(provider_name: str | None = None) -> LLMProvider:
    """
    Factory function — creates the appropriate LLM provider.

    Args:
        provider_name: "groq" or "openai". Defaults to LLM_PROVIDER from .env.

    Returns:
        Configured LLMProvider instance.

    Raises:
        LLMError: If the provider name is unknown or initialization fails.
    """
    name = (provider_name or config.LLM_PROVIDER).lower().strip()

    provider_class = _PROVIDERS.get(name)
    if provider_class is None:
        available = ", ".join(_PROVIDERS.keys())
        raise LLMError(
            f"Unknown LLM provider: '{name}'. Available: {available}"
        )

    logger.info("Initializing LLM provider: %s", name)
    return provider_class()
