"""
Component Classifier — Auto-categorizes bugs when Jira component is empty.

Uses keyword matching on bug summary and description to infer the module/area.
No LLM needed — fast, deterministic, and configurable.

Users can customize keyword mappings via the COMPONENT_KEYWORDS dict.
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# =============================================================================
# Default Keyword → Component Mappings
# =============================================================================
# Each key is a component name, value is a list of keywords/phrases.
# Matching is case-insensitive. First match wins (ordered by specificity).
# Turkish and English keywords are both included.

COMPONENT_KEYWORDS: dict[str, list[str]] = {
    "Authentication": [
        "login", "giriş", "giris", "oturum", "session", "token",
        "jwt", "oauth", "sso", "password", "şifre", "sifre", "parola",
        "2fa", "mfa", "two-factor", "iki faktör", "doğrulama", "dogrulama",
        "ldap", "authentication", "auth", "logout", "çıkış", "cikis",
        "brute force", "hesap kilitle", "account lock",
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
    ],
    "Security": [
        "güvenlik", "guvenlik", "security", "xss", "csrf",
        "injection", "sql injection", "vulnerability", "zafiyet",
        "encryption", "şifreleme", "sifreleme", "ssl", "tls",
        "certificate", "sertifika",
    ],
}


# =============================================================================
# Classifier
# =============================================================================

def classify_component(bug: dict[str, Any]) -> str:
    """
    Classify a bug into a component based on keyword matching.

    Searches bug summary and description for keywords from COMPONENT_KEYWORDS.
    Returns the first matching component or "Genel" if no match.

    Args:
        bug: Bug dictionary with 'summary' and 'description' fields.

    Returns:
        Component name string.
    """
    text = (
        f"{bug.get('summary', '')} {bug.get('description', '')}"
    ).lower()

    if not text.strip():
        return "Genel"

    # Score each component by number of keyword matches
    scores: dict[str, int] = {}

    for component, keywords in COMPONENT_KEYWORDS.items():
        score = 0
        for keyword in keywords:
            # Use word boundary for short keywords to avoid false matches
            if len(keyword) <= 3:
                pattern = rf"\b{re.escape(keyword)}\b"
                score += len(re.findall(pattern, text))
            else:
                score += text.count(keyword.lower())
        if score > 0:
            scores[component] = score

    if not scores:
        return "Genel"

    # Return component with highest score
    best = max(scores, key=scores.get)
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
