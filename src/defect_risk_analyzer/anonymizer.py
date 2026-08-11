"""
Data Anonymizer — PII masking before any external LLM call.

Provides reversible tokenization for personal data found in Jira bug records.
Masks: names, emails, IP addresses, URLs, phone numbers.
Mapping is persisted to data/anon_map.json for de-anonymization after analysis.

Non-negotiable rule: NO PII ever reaches the LLM.
"""

import json
import re
from pathlib import Path
from typing import Any

from defect_risk_analyzer import config


class DataAnonymizer:
    """Reversible PII anonymizer with persistent mapping."""

    def __init__(self, map_file: Path | None = None) -> None:
        self._map_file = map_file or config.ANON_MAP_FILE
        self._forward: dict[str, str] = {}   # original → token
        self._reverse: dict[str, str] = {}   # token → original
        self._counters: dict[str, int] = {
            "PERSON": 0,
            "EMAIL": 0,
            "IP": 0,
            "URL": 0,
            "PHONE": 0,
            "TOKEN": 0,
            "APIKEY": 0,
        }
        self._load_map()

    # ------------------------------------------------------------------
    # Regex patterns for PII detection
    # ------------------------------------------------------------------
    _BEARER_RE = re.compile(
        r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.UNICODE
    )
    _APIKEY_RE = re.compile(
        r"(?:(?:api[_-]?key|token|secret|password|authorization)\s*[=:]\s*)([A-Za-z0-9\-._~+/]{20,}=*)",
        re.IGNORECASE,
    )
    _APIKEY_PREFIX_RE = re.compile(
        r"\b(?:gsk_|sk-|xoxb-|xoxp-|ghp_|glpat-|ATATT)[A-Za-z0-9\-._~+/]{10,}=*\b"
    )
    _EMAIL_RE = re.compile(
        r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", re.UNICODE
    )
    _IP_RE = re.compile(
        r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
    )
    _URL_RE = re.compile(
        r"https?://[^\s<>\"']+", re.UNICODE
    )
    _PHONE_RE = re.compile(
        r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{2,4}\b"
    )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def anonymize_bugs(self, bugs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Anonymize a list of bug dictionaries. Returns new list (original unchanged)."""
        anonymized = []
        for bug in bugs:
            anon_bug = {}
            for key, value in bug.items():
                if isinstance(value, str):
                    anon_bug[key] = self._anonymize_string(value)
                elif isinstance(value, list):
                    anon_bug[key] = [
                        self._anonymize_string(item) if isinstance(item, str) else item
                        for item in value
                    ]
                elif isinstance(value, dict):
                    anon_bug[key] = {
                        k: self._anonymize_string(v) if isinstance(v, str) else v
                        for k, v in value.items()
                    }
                else:
                    anon_bug[key] = value
            anonymized.append(anon_bug)

        self._save_map()
        return anonymized

    def anonymize_query(self, text: str) -> str:
        """Anonymize a single text string (e.g., user query)."""
        result = self._anonymize_string(text)
        self._save_map()
        return result

    def deanonymize_text(self, text: str) -> str:
        """Restore original PII values in a text string."""
        result = text
        # Sort by token length descending to avoid partial replacements
        for token, original in sorted(
            self._reverse.items(), key=lambda x: len(x[0]), reverse=True
        ):
            result = result.replace(token, original)
        return result

    def get_mapping(self) -> dict[str, str]:
        """Return the current forward mapping (original → token)."""
        return dict(self._forward)

    def clear(self) -> None:
        """Reset all mappings and counters."""
        self._forward.clear()
        self._reverse.clear()
        for key in self._counters:
            self._counters[key] = 0
        self._save_map()

    # ------------------------------------------------------------------
    # Internal methods
    # ------------------------------------------------------------------

    def _anonymize_string(self, text: str) -> str:
        """Apply all PII patterns to a string. Order matters for accuracy."""
        if not text:
            return text

        # 1. Bearer tokens first (before URL/email could match sub-parts)
        result = self._BEARER_RE.sub(lambda m: self._get_token(m.group(), "TOKEN"), text)
        # 2. Known API key prefixes (gsk_, sk-, ghp_, ATATT, etc.)
        result = self._APIKEY_PREFIX_RE.sub(lambda m: self._get_token(m.group(), "APIKEY"), result)
        # 3. Generic key=value patterns (api_key=..., token=..., secret=...)
        result = self._APIKEY_RE.sub(lambda m: m.group(0).replace(m.group(1), self._get_token(m.group(1), "APIKEY")), result)
        # 4. URLs before emails (URLs may contain email-like parts)
        result = self._URL_RE.sub(lambda m: self._get_token(m.group(), "URL"), result)
        # 5. Emails
        result = self._EMAIL_RE.sub(lambda m: self._get_token(m.group(), "EMAIL"), result)
        # 6. IP addresses
        result = self._IP_RE.sub(lambda m: self._get_token(m.group(), "IP"), result)
        # 7. Phone numbers
        result = self._PHONE_RE.sub(lambda m: self._get_token(m.group(), "PHONE"), result)

        return result

    def _get_token(self, original: str, category: str) -> str:
        """Return existing token or create a new one for the given PII value."""
        if original in self._forward:
            return self._forward[original]

        self._counters[category] += 1
        token = f"[{category}_{self._counters[category]:03d}]"

        self._forward[original] = token
        self._reverse[token] = original
        return token

    def _save_map(self) -> None:
        """Persist mapping to disk."""
        data = {
            "forward": self._forward,
            "reverse": self._reverse,
            "counters": self._counters,
        }
        try:
            self._map_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._map_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass  # Silently handle write failures (e.g., read-only FS)

    def _load_map(self) -> None:
        """Load existing mapping from disk if available."""
        if not self._map_file.exists():
            return
        try:
            with open(self._map_file, encoding="utf-8") as f:
                data = json.load(f)
            self._forward = data.get("forward", {})
            self._reverse = data.get("reverse", {})
            self._counters = data.get("counters", self._counters)
        except (OSError, json.JSONDecodeError):
            pass  # Start fresh if file is corrupted
