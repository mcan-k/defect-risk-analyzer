"""
Component Classifier — Auto-categorizes bugs when Jira component is empty.

Uses keyword matching on bug summary and description to infer the module/area.
No LLM needed — fast, deterministic, and configurable.

Users can customize keyword mappings via the COMPONENT_KEYWORDS dict.
"""

import logging
import re
from functools import cache
from typing import Any

logger = logging.getLogger(__name__)


# =============================================================================
# Default Keyword → Component Mappings
# =============================================================================
# Each key is a component name, value is a list of keywords/phrases.
# Matching is case-insensitive and Turkish-aware: İ, I, ı and i count as the
# same letter. A keyword matches as a whole word, optionally followed by ONE
# inflection — a Turkish suffix chain ("girişte", "ödemede", "ürünlerin") or an
# English -s/-es/-d/-ed/-ing ("payments") — and never inside another word
# ("Author" is not "auth", "Parametre" is not "para"). Each match scores one
# point; the highest-scoring component wins, and a tie goes to the component
# listed first. Turkish and English keywords are both included.

COMPONENT_KEYWORDS: dict[str, list[str]] = {
    "Authentication": [
        "login", "giriş", "giris", "oturum", "session", "token",
        "jwt", "oauth", "sso", "password", "şifre", "sifre", "parola",
        "2fa", "mfa", "two-factor", "iki faktör", "doğrulama", "dogrulama",
        "ldap", "authentication", "auth", "logout", "çıkış", "cikis",
        "brute force", "hesap kilitle", "account lock",
        "authorization", "authenticate",
    ],
    "Payment": [
        "ödeme", "odeme", "payment", "kredi kartı", "kredi karti",
        "credit card", "3d secure", "3dsecure", "iade", "refund",
        "fatura", "invoice", "billing", "havale", "eft", "banka",
        "bank", "checkout", "satın al", "satin al", "purchase",
        "kdv", "vat", "tax", "para", "money", "tutar", "amount",
    ],
    "Frontend": [
        "ui", "arayüz", "arayuz", "frontend", "css", "responsive",
        "mobil", "mobile", "menü", "menu", "buton", "button",
        "sayfa", "page", "modal", "dialog", "popup", "form",
        "input", "dropdown", "select", "checkbox", "radio",
        "dark mode", "karanlık", "karanlik", "tema", "theme",
        "görünüm", "gorunum", "layout", "tasarım", "tasarim",
        "sepet", "cart", "tıklama", "tiklama", "click", "scroll",
        "infinite scroll", "pagination", "z-index",
    ],
    "Backend API": [
        "api", "endpoint", "rest", "graphql", "request", "response",
        "timeout", "504", "500", "502", "400", "401", "403", "404",
        "rate limit", "cors", "header", "json", "xml",
        "microservice", "servis", "service",
    ],
    "Database": [
        "database", "veritabanı", "veritabani", "sql", "query",
        "migration", "index", "tablo", "table", "kayıt", "kayit",
        "record", "transaction", "deadlock", "race condition",
        "connection pool", "bağlantı havuzu",
    ],
    "Reporting": [
        "rapor", "report", "export", "excel", "csv", "pdf",
        "grafik", "chart", "graph", "dashboard", "istatistik",
        "statistic", "analiz", "analysis", "filtre", "filter",
        "tarih aralığı", "date range", "timezone", "saat dilimi",
        "filtreleme",
    ],
    "Notifications": [
        "bildirim", "notification", "push", "e-posta", "email",
        "sms", "mesaj", "message", "alert", "uyarı", "uyari",
        "hatırlatma", "hatirlatma", "reminder", "spam",
    ],
    "Inventory": [
        "stok", "stock", "inventory", "envanter", "depo",
        "warehouse", "ürün", "urun", "product", "miktar",
        "quantity", "transfer", "tedarik", "supply",
    ],
    "Performance": [
        "yavaş", "yavas", "slow", "performans", "performance",
        "hız", "hiz", "speed", "memory", "bellek", "cpu",
        "cache", "önbellek", "onbellek", "optimize", "lag",
        "yavaşladı", "yavasladi", "slower",
    ],
    "Security": [
        "güvenlik", "guvenlik", "security", "xss", "csrf",
        "injection", "sql injection", "vulnerability", "zafiyet",
        "encryption", "şifreleme", "sifreleme", "ssl", "tls",
        "certificate", "sertifika",
    ],
}


# =============================================================================
# Matching
# =============================================================================

_TURKISH_I = str.maketrans({"İ": "i", "I": "i", "ı": "i"})


def _normalize(text: str) -> str:
    """Lower-case, with every form of i folded to "i".

    `str.lower()` alone turns "İ" into "i" + U+0307 (a combining dot), so
    "GİRİŞ" never equalled "giriş"; and it turns "I" into "i", so "ÇIKIŞ"
    became "çikiş", matching neither "çıkış" nor "cikis". A Turkish-only
    lower-casing would fix those but turn the English "I" into "ı" and break
    "LOGIN". Folding all four forms keeps both languages working; keywords go
    through the same function, so "çıkış" and "ÇIKIŞ" meet at "çikiş".
    """
    return text.translate(_TURKISH_I).lower().replace("̇", "")


# A Turkish inflection chain, in the order the language stacks it: plural,
# possessive, case, then "-ki" ("arayüzdeki"). Spelled after _normalize, so
# "ı" is written "i". Derivational suffixes (-lik, -leme, -siz, -li, -la-) are
# deliberately absent: they make new words — "tutarsız" is not "tutar",
# "depolama" is not "depo" — and accepting them brings the word-fragment
# matches back.
_PLURAL = r"(?:lar|ler)"
_POSSESSIVE = (
    r"(?:imiz|umuz|ümüz|iniz|unuz|ünüz|miz|muz|müz|niz|nuz|nüz|lari|leri"
    r"|si|su|sü|im|um|üm|in|un|ün|i|u|ü|m|n)"
)
_CASE = (
    r"(?:ndan|nden|dan|den|tan|ten|nda|nde|da|de|ta|te|nin|nun|nün|yin|yun|yün"
    r"|in|un|ün|yla|yle|la|le|ya|ye|yi|yu|yü|na|ne|ni|nu|nü|ca|ce|a|e|i|u|ü)"
)
# One of: the Turkish chain (which may be empty — the bare keyword), or an
# English inflection. An apostrophe needs no branch: it is not a word
# character, so "API'ye" already ends the keyword at a word boundary.
_SUFFIX = rf"(?:{_PLURAL}?{_POSSESSIVE}?{_CASE}?(?:ki)?|s|es|d|ed|ing)"


@cache
def _pattern(keyword: str) -> re.Pattern[str]:
    """A normalized keyword as a word: nothing word-like before it, at most
    one _SUFFIX after it, then nothing word-like. Group 1 is the keyword."""
    return re.compile(rf"(?<!\w)({re.escape(keyword)}){_SUFFIX}(?!\w)")


def _matches(text: str) -> list[tuple[int, int, str]]:
    """Every keyword match in normalized `text`, as (start, end, component)
    spanning the keyword itself.

    A match that lies inside a LONGER match of ANOTHER component is dropped:
    "sql injection" is Security's and must not also count as Database's
    "sql", nor "z-index" as Database's "index". Nesting within one component
    still counts, as it always has.
    """
    found = []
    for component, keywords in COMPONENT_KEYWORDS.items():
        # "kayıt" and "kayit" normalize to the same keyword: count it once.
        for keyword in dict.fromkeys(_normalize(k) for k in keywords):
            if keyword not in text:  # cheap pre-check: no substring, no word
                continue
            for m in _pattern(keyword).finditer(text):
                found.append((*m.span(1), component))
    return [
        (s, e, c) for s, e, c in found
        if not any(
            c2 != c and s2 <= s and e <= e2 and e2 - s2 > e - s
            for s2, e2, c2 in found
        )
    ]


# =============================================================================
# Classifier
# =============================================================================

def classify_component(bug: dict[str, Any]) -> str:
    """
    Classify a bug into a component based on keyword matching.

    Searches bug summary and description for keywords from COMPONENT_KEYWORDS
    and scores each component by its number of matches. Returns the
    highest-scoring component — on a tie, the one listed first in
    COMPONENT_KEYWORDS — or "Genel" if nothing matches.

    Args:
        bug: Bug dictionary with 'summary' and 'description' fields.

    Returns:
        Component name string.
    """
    text = _normalize(
        f"{bug.get('summary', '')} {bug.get('description', '')}"
    )

    if not text.strip():
        return "Genel"

    scores: dict[str, int] = {}
    for _, _, component in _matches(text):
        scores[component] = scores.get(component, 0) + 1

    if not scores:
        return "Genel"

    # Highest score; on a tie max() keeps the first, so walk COMPONENT_KEYWORDS order.
    best = max((c for c in COMPONENT_KEYWORDS if c in scores), key=scores.__getitem__)
    logger.debug("Classified bug '%s' → %s (score: %d)", bug.get("key", "?"), best, scores[best])
    return best


def classify_bugs(bugs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Auto-classify bugs that have no component assigned.

    Modifies bugs in-place: if component is empty or "Unknown",
    replaces it with the classified component.

    Args:
        bugs: List of bug dictionaries.

    Returns:
        Same list with components filled in.
    """
    classified_count = 0

    for bug in bugs:
        component = bug.get("component", "").strip()
        if not component or component == "Unknown":
            new_component = classify_component(bug)
            bug["component"] = new_component
            classified_count += 1

    if classified_count > 0:
        logger.info(
            "Auto-classified %d/%d bugs with missing components.",
            classified_count, len(bugs),
        )

    return bugs
