"""
Data Anonymizer — PII masking before any external LLM call.

Provides reversible tokenization for data found in Jira bug records.
Masks: emails, IP addresses, URLs, phone numbers, Bearer tokens and known API
key prefixes. Person names are NOT masked — no name recogniser ships here, and
the Settings page says so.

WHAT THIS IS AND IS NOT. Pattern-based masking reduces what leaves the process;
it does not guarantee that nothing does. IPv6, unusual phone shapes and
identifiers these patterns have never seen pass straight through. The module
used to open with "Non-negotiable rule: NO PII ever reaches the LLM" — that is
a promise the implementation cannot keep, so it is gone rather than restated.

SCOPE, NOT STATE. A mapping belongs to exactly one analysis call. Open one with
`DataAnonymizer.session()`:

    with anonymizer.session() as anon:
        prompt = anon.anonymize_query(query)
        ...
        reasoning = anon.deanonymize_text(llm_reasoning)

The `DataAnonymizer` itself holds no mapping at all — `session()` builds a fresh
`AnonymizationScope` and hands it over, so a token issued for one call can never
be restored into another call's output. That matters because the dashboard's
service handle is `@st.cache_resource`, which means every browser session shares
one anonymizer; before Faz 6B they also shared one mapping, and
`deanonymize_text` replaced every token it had ever issued without asking
whether that token appeared in this call's prompt.

The guarantee is structural rather than a cleanup step: the scope is a local
that goes out of reach when the `with` block ends, whether it ends normally or
by exception. There is no `finally` here because there is nothing to undo.

NOT PERSISTED. Before Faz 6B the mapping was written to `data/anon_map.json`
after every call and reloaded at construction. Measured: nothing read it back —
the round trip completes inside a single call — while the file accumulated
secrets in plain text and was never pruned. `config.init()` deletes any file
left behind by those versions.
"""

import contextlib
import re
from collections.abc import Iterator
from typing import Any

# ---------------------------------------------------------------------------
# Patterns. Module-level because they are pure — no scope owns them.
# ---------------------------------------------------------------------------

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

# Phone numbers. THREE ALTERNATIVES, and the reason there is not one:
#
# The pattern this replaced was `(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?
# \d{3,4}[-.\s]?\d{2,4}\b` — three digit groups with optional separators. Every
# separator being optional is what broke it, because a run of seven or more
# digits satisfies all three groups by itself, and so does any three numbers
# with spaces between them. Measured against synthetic bug text: build numbers
# (`Build 20241105123`), trace ids (`Trace id 1234567890`), measurements
# (`Memory grew 1024 2048 4096 MB`) and quantities (`SKU 4512 8890 12`) were
# all replaced with a PHONE token, which deletes from the prompt the very
# identifier the report is about. Sixteen digits in four groups was worse than
# a miss: it matched the first twelve and left the last four sitting next to
# the token, so the output read as masked while a fragment survived.
#
# So a separator is now mandatory, and a bare space is not enough on its own —
# a space-separated triple is a measurement far more often than a phone number.
# What remains is the three shapes that carry their own evidence:
#
#   A  an explicit `+` country prefix       +90 532 111 2233, +1-800-555-0199
#   B  a parenthesised area code            (555) 123-4567
#   C  `-` or `.` between every group       555-123-4567, 020-7946-0958
#
# B and C end in a 3-4 digit group. That last constraint is what separates a
# phone number from a numeric order reference such as `100-2003-77`, whose
# final group is two digits. It is a heuristic, not a proof: shape alone cannot
# always tell an order code from a phone number, and a 3-4-4 order code still
# matches. See docs/KNOWN-DEBT.md.
#
# The lookaround keeps a match from starting inside a longer number or after a
# version dot (`2.10.3.4567`), and from stopping in the middle of one.
_PHONE_RE = re.compile(
    r"(?<![\d.])"
    r"(?:"
    r"\+\d{1,3}[-.\s]?(?:\(?\d{1,4}\)?[-.\s]?){1,4}\d{2,4}"
    r"|"
    r"\(\d{2,4}\)[-.\s]?\d{3,4}[-.]?\d{3,4}"
    r"|"
    r"\d{2,4}[-.]\d{3,4}[-.]\d{3,4}"
    r")"
    r"(?!\d)"
)


class AnonymizationScope:
    """The reversible mapping for ONE analysis call.

    Obtained from `DataAnonymizer.session()`, never constructed by callers.

    Deliberately has no `session()` of its own, so a nested scope is impossible
    rather than merely undefined: `with anon.session() as inner` inside a scope
    raises AttributeError at the point of misuse. Pinning a behaviour for
    nesting would mean choosing whether the inner scope inherits the outer
    mapping, and neither answer has a caller asking for it — the analysis path
    opens exactly one scope, under `_llm_lock`.
    """

    def __init__(self) -> None:
        self._forward: dict[str, str] = {}   # original → token
        self._reverse: dict[str, str] = {}   # token → original
        self._counters: dict[str, int] = {
            # PERSON has no pattern behind it. Kept because it is the honest
            # record of a category this project claims nothing about; removing
            # the counter would not add a name recogniser, it would only hide
            # that there is none.
            "PERSON": 0,
            "EMAIL": 0,
            "IP": 0,
            "URL": 0,
            "PHONE": 0,
            "TOKEN": 0,
            "APIKEY": 0,
        }

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

        return anonymized

    def anonymize_query(self, text: str) -> str:
        """Anonymize a single text string (e.g., user query)."""
        return self._anonymize_string(text)

    def deanonymize_text(self, text: str) -> str:
        """Restore original values for tokens THIS scope issued.

        A token this scope never issued is left exactly as it is. That is the
        common case for LLM output, which can echo a token-shaped string on its
        own; corrupting the reasoning text would be worse than showing an
        unresolved token, and the reasoning is what the user reads.
        """
        result = text
        # Sort by token length descending to avoid partial replacements
        for token, original in sorted(
            self._reverse.items(), key=lambda x: len(x[0]), reverse=True
        ):
            result = result.replace(token, original)
        return result

    # ------------------------------------------------------------------
    # Internal methods
    # ------------------------------------------------------------------

    def _anonymize_string(self, text: str) -> str:
        """Apply all patterns to a string. Order matters for accuracy."""
        if not text:
            return text

        # 1. Bearer tokens first (before URL/email could match sub-parts)
        result = _BEARER_RE.sub(lambda m: self._get_token(m.group(), "TOKEN"), text)
        # 2. Known API key prefixes (gsk_, sk-, ghp_, ATATT, etc.)
        result = _APIKEY_PREFIX_RE.sub(lambda m: self._get_token(m.group(), "APIKEY"), result)
        # 3. Generic key=value patterns (api_key=..., token=..., secret=...)
        result = _APIKEY_RE.sub(
            lambda m: m.group(0).replace(m.group(1), self._get_token(m.group(1), "APIKEY")),
            result,
        )
        # 4. URLs before emails (URLs may contain email-like parts)
        result = _URL_RE.sub(lambda m: self._get_token(m.group(), "URL"), result)
        # 5. Emails
        result = _EMAIL_RE.sub(lambda m: self._get_token(m.group(), "EMAIL"), result)
        # 6. IP addresses — before phones, so an IPv4 is never read as a number run
        result = _IP_RE.sub(lambda m: self._get_token(m.group(), "IP"), result)
        # 7. Phone numbers
        result = _PHONE_RE.sub(lambda m: self._get_token(m.group(), "PHONE"), result)

        return result

    def _get_token(self, original: str, category: str) -> str:
        """Return existing token or create a new one for the given value."""
        if original in self._forward:
            return self._forward[original]

        self._counters[category] += 1
        token = f"[{category}_{self._counters[category]:03d}]"

        self._forward[original] = token
        self._reverse[token] = original
        return token


class DataAnonymizer:
    """Hands out one-call anonymization scopes. Holds no mapping itself.

    Long-lived and shared: `AnalysisService` builds one, and under the dashboard
    that service lives behind `@st.cache_resource` for the whole process. Since
    nothing is stored here, sharing it is harmless by construction rather than
    by discipline.
    """

    @contextlib.contextmanager
    def session(self) -> Iterator[AnonymizationScope]:
        """Open a mapping scope for exactly one analysis call."""
        yield AnonymizationScope()
