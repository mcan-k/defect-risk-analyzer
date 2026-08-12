"""
Deterministic risk scoring — the heart of the engine.

Risk scores are calculated here, in Python, never by the LLM. The LLM only
interprets these pre-calculated statistics and writes the reasoning.

Every function in this module is pure: it takes plain dicts and returns plain
dicts. No file access, no network, no ChromaDB, no configuration lookup — which
makes the scoring rules directly testable and lets the refactor baseline
reproduce them exactly.
"""

from collections import Counter
from datetime import datetime, timedelta
from typing import Any

# =============================================================================
# Priority Weights (ISTQB Risk-Based Testing)
# =============================================================================

PRIORITY_WEIGHTS: dict[str, float] = {
    "Highest": 5.0,
    "High": 4.0,
    "Medium": 3.0,
    "Low": 2.0,
    "Lowest": 1.0,
}

# Fallback weight for unknown priorities
DEFAULT_PRIORITY_WEIGHT: float = 2.5


# =============================================================================
# Risk Score Thresholds
# =============================================================================
# These are fixed product rules, not user settings — they are never read from
# .env, which is why they live here rather than in config.py.

RISK_CRITICAL: int = 80
RISK_HIGH: int = 60
RISK_MEDIUM: int = 35


def get_risk_level(score: int) -> str:
    """Map a numeric risk score to a human-readable level."""
    if score >= RISK_CRITICAL:
        return "CRITICAL"
    if score >= RISK_HIGH:
        return "HIGH"
    if score >= RISK_MEDIUM:
        return "MEDIUM"
    return "LOW"


# =============================================================================
# Module Statistics
# =============================================================================

def calculate_module_stats(
    bugs: list[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """
    Calculate per-module statistics from a list of bugs.

    Args:
        bugs: All bugs to aggregate.
        now: Reference time for the 30-day trend window. Defaults to the
            current time. Passing it explicitly makes the result reproducible,
            which the refactor baseline relies on.

    Returns:
        Dict mapping module names to their statistics:
        {
            "Authentication": {
                "total_bugs": 8,
                "open_bugs": 5,
                "closed_bugs": 3,
                "open_ratio": 0.625,
                "bug_density": 1.6,
                "priority_distribution": {"High": 3, "Medium": 4, "Low": 1},
                "trend": "increasing",
                "weighted_priority_score": 26.0,
                "recent_bug_count": 4,
            },
            ...
        }
    """
    if not bugs:
        return {}

    # Resolved here rather than in the signature default, which would freeze
    # the value at import time and silently skew trends after midnight.
    now = now or datetime.now()

    # Group bugs by module/component
    module_bugs: dict[str, list[dict]] = {}
    for bug in bugs:
        module = bug.get("component", "Unknown") or "Unknown"
        module_bugs.setdefault(module, []).append(bug)

    total_all_bugs = len(bugs)
    stats: dict[str, dict[str, Any]] = {}

    for module, bugs_in_module in module_bugs.items():
        total = len(bugs_in_module)
        open_bugs = sum(
            1 for b in bugs_in_module
            if b.get("status", "").lower() not in ("done", "closed", "resolved")
        )
        closed_bugs = total - open_bugs
        open_ratio = open_bugs / total if total > 0 else 0

        # Bug density: module's share of total bugs (normalized)
        bug_density = total / total_all_bugs if total_all_bugs > 0 else 0

        # Priority distribution
        priority_dist = Counter(b.get("priority", "Medium") for b in bugs_in_module)

        # Weighted priority score
        weighted_score = sum(
            PRIORITY_WEIGHTS.get(p, DEFAULT_PRIORITY_WEIGHT) * count
            for p, count in priority_dist.items()
        )

        # Trend detection: count bugs created in last 30 days vs older.
        # Note: this compares two ISO strings lexicographically, not datetimes.
        # Preserved deliberately — switching to parsed datetimes changes results
        # for timezone-suffixed Jira timestamps.
        thirty_days_ago = (now - timedelta(days=30)).isoformat()
        recent_count = 0
        old_count = 0
        for b in bugs_in_module:
            created = b.get("created", "")
            if created and created >= thirty_days_ago:
                recent_count += 1
            else:
                old_count += 1

        if recent_count > old_count:
            trend = "increasing"
        elif recent_count < old_count:
            trend = "decreasing"
        else:
            trend = "stable"

        stats[module] = {
            "total_bugs": total,
            "open_bugs": open_bugs,
            "closed_bugs": closed_bugs,
            "open_ratio": open_ratio,
            "bug_density": bug_density,
            "priority_distribution": dict(priority_dist),
            "weighted_priority_score": weighted_score,
            "trend": trend,
            "recent_bug_count": recent_count,
        }

    return stats


# =============================================================================
# Risk Score
# =============================================================================

def calculate_risk_score(module_name: str, module_stats: dict[str, Any]) -> int:
    """
    Calculate deterministic risk score for a module.

    Formula: base_score = (priority_factor × 60) + (bug_density × 40)
             adjusted  = base_score × open_ratio_factor × trend_multiplier × volume_factor
             clamped   = clamp(adjusted, 0, 100)

    Volume factor prevents modules with 1-2 bugs from reaching CRITICAL.
    You need statistical significance (3+ bugs) for a high confidence score.

    Args:
        module_name: Name of the module. Currently unused by the formula —
            see docs/KNOWN-DEBT.md; the signature is kept until that is decided.
        module_stats: Statistics dict for this module from calculate_module_stats().

    Returns:
        Risk score integer (0-100).
    """
    if not module_stats:
        return 0

    total_bugs = module_stats.get("total_bugs", 0)
    if total_bugs == 0:
        return 0

    # Component 1: Weighted priority contribution
    weighted_score = module_stats.get("weighted_priority_score", 0)
    max_possible = total_bugs * 5.0  # If all were "Highest"
    priority_factor = weighted_score / max_possible if max_possible > 0 else 0

    # Component 2: Bug density (this module's share of all bugs)
    bug_density = module_stats.get("bug_density", 0)

    # Component 3: Open bug ratio (more open = higher risk)
    open_ratio = module_stats.get("open_ratio", 0)
    open_ratio_factor = 1.0 + (open_ratio * 0.5)  # 1.0 to 1.5

    # Component 4: Trend multiplier
    trend = module_stats.get("trend", "stable")
    trend_multipliers = {
        "increasing": 1.3,
        "stable": 1.0,
        "decreasing": 0.8,
    }
    trend_multiplier = trend_multipliers.get(trend, 1.0)

    # Component 5: Volume factor (statistical confidence)
    # 1 bug = 0.55, 2 bugs = 0.70, 3 bugs = 0.85, 4+ bugs = 1.0
    volume_threshold = 4
    volume_factor = min(total_bugs / volume_threshold, 1.0)
    volume_factor = 0.4 + (volume_factor * 0.6)  # Range: 0.55 (1 bug) to 1.0 (4+ bugs)

    # Calculate base score
    base_score = (
        (priority_factor * 60)      # Severity contributes up to 60
        + (bug_density * 40)         # Concentration contributes up to 40
    )

    # Apply multipliers
    adjusted = base_score * open_ratio_factor * trend_multiplier * volume_factor

    # Clamp to 0-100
    return max(0, min(100, int(round(adjusted))))
