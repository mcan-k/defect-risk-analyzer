"""
Blind Spot Detector — Identifies untested risky areas and neglected bugs.

Analyzes bug data to find:
  1. High-risk modules with no analysis coverage
  2. Neglected critical bugs (high priority, no progress)
  3. Stale bugs (open too long without attention)
  4. Rising risk areas (increasing trend, no mitigation)

No LLM needed — pure data analysis.
"""

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


def detect_blind_spots(
    bugs: list[dict[str, Any]],
    module_stats: dict[str, dict[str, Any]],
    analysis_results: list[dict[str, Any]],
    risk_scores: dict[str, int],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Detect blind spots in QA coverage.

    Args:
        bugs: All loaded bugs.
        module_stats: Per-module statistics from calculate_module_stats().
        analysis_results: Previously saved analysis results.
        risk_scores: Per-module risk scores {module_name: score}.
        now: Reference time for every "days open" calculation. Defaults to the
            current time. Passing it explicitly makes the result reproducible,
            which is what lets the two bug categories be pinned by a test at
            all — see tests/test_blind_spots.py. Keyword-only so the
            positional contract stays fixed when Phase 5B moves this module.
            Pass an *aware* datetime: the bugs carry a Jira UTC offset, and
            subtracting a naive reference from those raises TypeError, which
            _days_since swallows into a silent 0.

    Returns:
        Dict with categorized blind spots:
        {
            "unanalyzed_risky_modules": [...],
            "neglected_critical_bugs": [...],
            "stale_bugs": [...],
            "rising_unattended": [...],
            "summary": {...},
        }
    """
    # Resolved here rather than in the signature default, which would freeze
    # the value at import time and silently skew "days open" after midnight.
    # Resolved once rather than per bug, so a run that straddles midnight
    # cannot put two bugs on opposite sides of the 14-day staleness line.
    now = now or datetime.now(UTC)

    result = {
        "unanalyzed_risky_modules": _find_unanalyzed_risky_modules(
            module_stats, analysis_results, risk_scores
        ),
        "neglected_critical_bugs": _find_neglected_critical_bugs(bugs, now),
        "stale_bugs": _find_stale_bugs(bugs, now=now),
        "rising_unattended": _find_rising_unattended(bugs, module_stats),
    }

    # Summary counts
    total_spots = sum(len(v) for v in result.values() if isinstance(v, list))
    critical_spots = (
        len(result["neglected_critical_bugs"])
        + len([m for m in result["unanalyzed_risky_modules"] if m.get("risk_level") == "CRITICAL"])
    )

    result["summary"] = {
        "total_blind_spots": total_spots,
        "critical_spots": critical_spots,
        "categories": {
            "unanalyzed_risky_modules": len(result["unanalyzed_risky_modules"]),
            "neglected_critical_bugs": len(result["neglected_critical_bugs"]),
            "stale_bugs": len(result["stale_bugs"]),
            "rising_unattended": len(result["rising_unattended"]),
        },
    }

    logger.info("Blind spot detection complete. Total: %d spots.", total_spots)
    return result


def _find_unanalyzed_risky_modules(
    module_stats: dict[str, dict],
    analysis_results: list[dict],
    risk_scores: dict[str, int],
) -> list[dict[str, Any]]:
    """Find modules with high risk but no LLM analysis performed."""
    # Modules that have been analyzed
    analyzed_modules = set()
    for result in analysis_results:
        for module in result.get("affected_modules", []):
            analyzed_modules.add(module)

    unanalyzed = []
    for module_name, stats in module_stats.items():
        score = risk_scores.get(module_name, 0)
        if score >= 35 and module_name not in analyzed_modules:
            unanalyzed.append({
                "module": module_name,
                "risk_score": score,
                "risk_level": _score_to_level(score),
                "bug_count": stats.get("total_bugs", 0),
                "open_bugs": stats.get("open_bugs", 0),
                "recommendation": f"{module_name} modülü {_score_to_level(score)} risk seviyesinde "
                                  f"ancak henüz analiz edilmemiş. Canlı Analiz sayfasından analiz yapın.",
            })

    unanalyzed.sort(key=lambda x: x["risk_score"], reverse=True)
    return unanalyzed


def _find_neglected_critical_bugs(
    bugs: list[dict[str, Any]],
    now: datetime,
) -> list[dict[str, Any]]:
    """Find high-priority bugs still in To Do with no progress."""
    high_priorities = {"Highest", "High"}
    no_progress_statuses = {"to do", "open", "backlog", "new"}

    neglected = []
    for bug in bugs:
        priority = bug.get("priority", "Medium")
        status = bug.get("status", "").lower()

        if priority in high_priorities and status in no_progress_statuses:
            created = bug.get("created", "")
            days_open = _days_since(created, now) if created else 0

            neglected.append({
                "key": bug.get("key", "?"),
                "summary": bug.get("summary", ""),
                "priority": priority,
                "status": bug.get("status", ""),
                "component": bug.get("component", "Genel"),
                "days_open": days_open,
                "recommendation": f"{bug.get('key', '?')} — {priority} öncelikli bug {days_open} gündür "
                                  f"'{bug.get('status', '')}' durumunda. Acil müdahale gerekiyor.",
            })

    neglected.sort(key=lambda x: (x["priority"] == "Highest", x["days_open"]), reverse=True)
    return neglected


def _find_stale_bugs(
    bugs: list[dict[str, Any]],
    stale_days: int = 14,
    *,
    now: datetime,
) -> list[dict[str, Any]]:
    """Find bugs open for too long without resolution."""
    open_statuses = {"to do", "open", "in progress", "in review", "backlog", "new", "reopened"}

    stale = []
    for bug in bugs:
        status = bug.get("status", "").lower()
        if status not in open_statuses:
            continue

        created = bug.get("created", "")
        days_open = _days_since(created, now) if created else 0

        if days_open >= stale_days:
            stale.append({
                "key": bug.get("key", "?"),
                "summary": bug.get("summary", ""),
                "priority": bug.get("priority", "Medium"),
                "status": bug.get("status", ""),
                "component": bug.get("component", "Genel"),
                "days_open": days_open,
                "recommendation": f"{bug.get('key', '?')} — {days_open} gündür açık. "
                                  f"Çözüm süresi beklentinin üzerinde.",
            })

    stale.sort(key=lambda x: x["days_open"], reverse=True)
    return stale


def _find_rising_unattended(
    bugs: list[dict[str, Any]],
    module_stats: dict[str, dict],
) -> list[dict[str, Any]]:
    """Find modules with increasing bug trend but no bugs being worked on."""
    rising = []

    for module_name, stats in module_stats.items():
        trend = stats.get("trend", "stable")
        if trend != "increasing":
            continue

        # Check if any bugs in this module are being actively worked on
        module_bugs = [b for b in bugs if b.get("component", "") == module_name]
        in_progress = [
            b for b in module_bugs
            if b.get("status", "").lower() in ("in progress", "in review")
        ]

        if not in_progress:
            rising.append({
                "module": module_name,
                "total_bugs": stats.get("total_bugs", 0),
                "open_bugs": stats.get("open_bugs", 0),
                "recent_bugs": stats.get("recent_bug_count", 0),
                "in_progress": 0,
                "recommendation": f"{module_name} modülünde bug sayısı artıyor "
                                  f"({stats.get('recent_bug_count', 0)} yeni bug) "
                                  f"ancak üzerinde çalışılan bug yok. "
                                  f"Bu modüle kaynak ayrılması önerilir.",
            })

    rising.sort(key=lambda x: x["recent_bugs"], reverse=True)
    return rising


# =============================================================================
# Helpers
# =============================================================================

def _days_since(date_str: str, now: datetime) -> int:
    """Calculate days since a given ISO date string, against a fixed reference.

    `now` replaces what used to be `datetime.now(created.tzinfo)` inline. That
    expression did two different things depending on the bug, and both are
    preserved here:

      * aware `created` (every real Jira timestamp, e.g. "+0300") compared
        against the same instant — aware minus aware is instant arithmetic, so
        the offset the reference carries does not matter;
      * naive `created` (no offset in the string) compared in local wall time,
        which is what datetime.now(None) returned.

    The TypeError branch below is load-bearing and unchanged: passing a *naive*
    `now` while the bugs are aware raises there and every result silently
    becomes 0. Pinned in tests/test_blind_spots.py rather than fixed — this
    commit changes no behaviour.
    """
    try:
        if "T" in date_str:
            created = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        else:
            created = datetime.fromisoformat(date_str)
        reference = now if created.tzinfo is not None else now.astimezone().replace(tzinfo=None)
        delta = reference - created
        return max(0, delta.days)
    except (ValueError, TypeError):
        return 0


def _score_to_level(score: int) -> str:
    """Convert risk score to level string."""
    if score >= 80:
        return "CRITICAL"
    if score >= 60:
        return "HIGH"
    if score >= 35:
        return "MEDIUM"
    return "LOW"
