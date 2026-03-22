"""
Prompt Templates — ISTQB-standard System & User prompts for LLM analysis.

System prompt establishes the LLM's role as an ISTQB-Certified Senior QA Architect.
User prompt injects pre-calculated statistics and bug data for interpretation.
All prompts are in English for optimal LLM performance.
Output language auto-detected from bug data language.
"""

import json
from typing import Any

# =============================================================================
# System Prompt
# =============================================================================

SYSTEM_PROMPT = """You are an ISTQB-Certified Senior QA Architect with 15+ years of experience in enterprise software quality assurance.

## Your Expertise
- ISTQB Advanced Level Test Analyst and Test Manager
- Risk-Based Testing: You prioritize testing based on probability of failure and business impact
- Defect Clustering (Pareto Principle): You know that 80% of defects cluster in 20% of modules
- Pesticide Paradox: You know that repeating the same tests will not find new defects
- Boundary Value Analysis and Equivalence Partitioning for test design

## Your Task
You will receive:
1. Pre-calculated module statistics (bug counts, priority distribution, open/closed ratios, trends)
2. A deterministic risk score already computed by the system
3. Similar historical bugs from the vector database
4. The specific bug or area being analyzed

Your job is to INTERPRET the pre-calculated data and provide:
- Reasoning: WHY this risk level makes sense given the data
- Test scenarios: WHAT should be tested to mitigate the risk
- Recommended actions: WHAT the QA team should do next

## Critical Rules
1. You do NOT calculate the risk score — it is already provided. Reference it in your reasoning.
2. Apply ISTQB principles in your reasoning (mention Defect Clustering, Pesticide Paradox, Risk-Based Testing where relevant).
3. Your test scenarios must be SPECIFIC and ACTIONABLE — not generic advice.
4. Detect the language of the bug data and respond in the SAME language. If bugs are in Turkish, respond in Turkish. If in English, respond in English.
5. You MUST respond ONLY with a valid JSON object. No markdown, no explanation outside JSON.

## Required JSON Output Schema
{
    "risk_score": <integer 0-100, copy from provided score>,
    "risk_level": "<CRITICAL|HIGH|MEDIUM|LOW, copy from provided level>",
    "reasoning": "<detailed explanation referencing ISTQB principles and the statistics>",
    "affected_modules": ["<module1>", "<module2>"],
    "test_scenarios": ["<specific test scenario 1>", "<specific test scenario 2>", "..."],
    "recommended_actions": ["<action 1>", "<action 2>", "..."]
}

Respond ONLY with this JSON object. No other text."""


# =============================================================================
# User Prompt Builder
# =============================================================================

def build_user_prompt(
    query: str,
    risk_score: int,
    risk_level: str,
    module_stats: dict[str, Any],
    similar_bugs: list[dict[str, Any]],
    bug_data: dict[str, Any] | None = None,
) -> str:
    """
    Build the user prompt with pre-calculated data for LLM interpretation.

    Args:
        query: The bug summary or area being analyzed.
        risk_score: Pre-calculated deterministic risk score (0-100).
        risk_level: Pre-calculated risk level (CRITICAL/HIGH/MEDIUM/LOW).
        module_stats: Per-module statistics from calculate_module_stats().
        similar_bugs: Similar historical bugs from ChromaDB.
        bug_data: Full bug record if analyzing a specific bug.

    Returns:
        Formatted user prompt string.
    """
    sections = []

    # Section 1: Analysis target
    sections.append("## Analysis Target")
    sections.append(f"Query: {query}")
    sections.append(f"Pre-calculated Risk Score: {risk_score}/100")
    sections.append(f"Pre-calculated Risk Level: {risk_level}")

    # Section 2: Bug details (if specific bug)
    if bug_data:
        sections.append("\n## Bug Details")
        sections.append(f"Key: {bug_data.get('key', 'N/A')}")
        sections.append(f"Summary: {bug_data.get('summary', 'N/A')}")
        sections.append(f"Priority: {bug_data.get('priority', 'N/A')}")
        sections.append(f"Status: {bug_data.get('status', 'N/A')}")
        sections.append(f"Module/Component: {bug_data.get('component', 'N/A')}")

        description = bug_data.get("description", "")
        if description:
            # Truncate long descriptions
            if len(description) > 500:
                description = description[:500] + "..."
            sections.append(f"Description: {description}")

    # Section 3: Module statistics
    sections.append("\n## Module Statistics (Pre-calculated)")
    if module_stats:
        for module_name, stats in module_stats.items():
            sections.append(f"\n### {module_name}")
            sections.append(f"  Total bugs: {stats.get('total_bugs', 0)}")
            sections.append(f"  Open bugs: {stats.get('open_bugs', 0)}")
            sections.append(f"  Closed bugs: {stats.get('closed_bugs', 0)}")
            sections.append(f"  Open ratio: {stats.get('open_ratio', 0):.1%}")
            sections.append(f"  Bug density score: {stats.get('bug_density', 0):.2f}")

            priority_dist = stats.get("priority_distribution", {})
            if priority_dist:
                dist_str = ", ".join(
                    f"{p}: {c}" for p, c in priority_dist.items()
                )
                sections.append(f"  Priority distribution: {dist_str}")

            trend = stats.get("trend", "stable")
            sections.append(f"  Trend: {trend}")
    else:
        sections.append("  No module statistics available.")

    # Section 4: Similar historical bugs
    sections.append("\n## Similar Historical Bugs (from vector database)")
    if similar_bugs:
        for i, bug in enumerate(similar_bugs, 1):
            sections.append(
                f"  {i}. [{bug.get('key', '?')}] {bug.get('summary', '?')} "
                f"(Priority: {bug.get('priority', '?')}, Status: {bug.get('status', '?')}, "
                f"Module: {bug.get('component', '?')})"
            )
    else:
        sections.append("  No similar bugs found in history.")

    # Section 5: Instructions
    sections.append("\n## Instructions")
    sections.append(
        "Interpret the above pre-calculated statistics and similar bugs. "
        "Explain WHY this risk level is appropriate. "
        "Suggest SPECIFIC test scenarios and actionable recommendations. "
        "Detect the language of the bug data and respond in the SAME language. "
        "Respond ONLY with a valid JSON object following the schema in your system instructions."
    )

    return "\n".join(sections)


# =============================================================================
# Webhook Prompt (simplified for auto-analysis)
# =============================================================================

def build_webhook_prompt(
    bug_data: dict[str, Any],
    risk_score: int,
    risk_level: str,
    module_stats: dict[str, Any],
) -> str:
    """
    Build a simplified prompt for webhook-triggered auto-analysis.
    Similar to build_user_prompt but without similar bugs (speed optimization).

    Args:
        bug_data: Bug record from Jira webhook.
        risk_score: Pre-calculated risk score.
        risk_level: Pre-calculated risk level.
        module_stats: Current module statistics.

    Returns:
        Formatted user prompt string.
    """
    return build_user_prompt(
        query=bug_data.get("summary", "Unknown bug"),
        risk_score=risk_score,
        risk_level=risk_level,
        module_stats=module_stats,
        similar_bugs=[],
        bug_data=bug_data,
    )
