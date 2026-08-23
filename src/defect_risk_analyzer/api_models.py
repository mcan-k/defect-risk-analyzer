"""
Pydantic request and response models for the Predictive Defect Analysis Engine API.

All API endpoints use these models for request validation and response serialization.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# =============================================================================
# Request Models
# =============================================================================

class AnalyzeRequest(BaseModel):
    """Single bug or area risk analysis request."""
    bug_key: str | None = Field(
        None,
        description="Jira bug key (e.g., 'AP-101'). If provided, fetches bug details from loaded data.",
        examples=["AP-101"],
    )
    query: str | None = Field(
        None,
        description="Free-text query describing an area or concern to analyze.",
        examples=["Authentication module login failures"],
    )


class BulkAnalyzeRequest(BaseModel):
    """Bulk analysis request — analyzes multiple bugs in sequence."""
    bug_keys: list[str] = Field(
        ...,
        description="List of Jira bug keys to analyze.",
        min_length=1,
        examples=[["AP-101", "AP-102", "AP-103"]],
    )


class WebhookPayload(BaseModel):
    """Jira webhook event payload (simplified)."""
    webhookEvent: str = Field(
        ...,
        description="Jira event type (e.g., 'jira:issue_created', 'jira:issue_updated').",
    )
    issue: dict = Field(
        ...,
        description="Jira issue object from the webhook payload.",
    )


class SettingsUpdate(BaseModel):
    """Settings update request from the dashboard Settings page."""
    jira_url: str | None = None
    jira_email: str | None = None
    jira_api_token: str | None = None
    jira_project_key: str | None = None
    llm_provider: str | None = None
    groq_api_key: str | None = None
    openai_api_key: str | None = None
    max_daily_requests: int | None = None
    groq_sleep: float | None = None
    use_mock_data: bool | None = None


# =============================================================================
# Response Models
# =============================================================================

class BugRiskResult(BaseModel):
    """Risk analysis result for a single bug or query."""
    bug_key: str | None = Field(None, description="Jira bug key if applicable.")
    query: str = Field(..., description="The analyzed query or bug summary.")
    risk_score: int = Field(..., ge=0, le=100, description="Deterministic risk score (0-100).")
    risk_level: str = Field(..., description="CRITICAL / HIGH / MEDIUM / LOW.")
    reasoning: str = Field(default="", description="LLM-generated risk reasoning.")
    affected_modules: list[str] = Field(default_factory=list, description="Modules affected by this risk.")
    test_scenarios: list[str] = Field(default_factory=list, description="Recommended test scenarios.")
    recommended_actions: list[str] = Field(default_factory=list, description="Actionable recommendations.")
    analyzed_at: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="ISO timestamp of analysis.",
    )
    source: str = Field(
        default="live_analysis",
        description="Origin: live_analysis, bulk_analysis, webhook.",
    )


class BulkAnalyzeResponse(BaseModel):
    """Response for bulk analysis — includes results and skipped items."""
    total: int = Field(..., description="Total number of bugs requested.")
    analyzed: int = Field(0, description="Number successfully analyzed.")
    skipped: int = Field(0, description="Number skipped (circuit breaker or error).")
    results: list[BugRiskResult] = Field(default_factory=list)
    skipped_keys: list[str] = Field(
        default_factory=list,
        description="Bug keys that were skipped due to circuit breaker or errors.",
    )
    circuit_breaker_triggered: bool = Field(
        False,
        description="True if bulk analysis was halted by circuit breaker.",
    )


class RiskSummary(BaseModel):
    """Current risk overview — module risk scores and defect density."""
    total_bugs: int = Field(0, description="Total number of tracked bugs.")
    analyzed_count: int = Field(0, description="Number of bugs with analysis results.")
    module_risks: dict[str, dict] = Field(
        default_factory=dict,
        description="Per-module risk data: {module: {score, level, bug_count, open_count}}.",
    )
    defect_density: dict[str, float] = Field(
        default_factory=dict,
        description="Per-module defect density values.",
    )
    last_updated: str | None = Field(None, description="ISO timestamp of last analysis run.")


class BlindSpotFinding(BaseModel):
    """One blind spot, as structural data rather than a sentence.

    `code` names the finding; `params` holds everything needed to word it, and
    holds it self-contained so a client can render without reading the
    finding's other fields. Architectural rule 3 (docs/ROADMAP-v2.md:16-18):
    business logic returns this, the UI layer produces the text. The Turkish
    templates live in ui/messages.py.

    params is left as a free dict rather than a discriminated union per code.
    A union would be more precise, but it pins four shapes that Phase 5C is
    about to add to, and the round-trip test in tests/test_blind_spot_contract
    already catches the failure a looser type risks — a dropped field.
    """
    code: str = Field(description="Finding type, e.g. 'stale_bug'.")
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Values the rendered sentence interpolates.",
    )


class UnanalyzedRiskyModule(BlindSpotFinding):
    """A module scoring 35 or above that no analysis result mentions."""
    module: str = Field(description="Module name.")
    risk_score: int = Field(0, description="Deterministic risk score, 0-100.")
    risk_level: str = Field("LOW", description="CRITICAL / HIGH / MEDIUM / LOW.")
    bug_count: int = Field(0, description="Total bugs in the module.")
    open_bugs: int = Field(0, description="Open bugs in the module.")


class BlindSpotBug(BaseModel):
    """A bug flagged as neglected or stale.

    One model for both categories: they are produced by different filters but
    carry identical fields.
    """
    key: str = Field(description="Jira bug key.")
    summary: str = Field("", description="Bug summary, untruncated.")
    priority: str = Field("Medium", description="Jira priority.")
    status: str = Field("", description="Jira status, original casing.")
    component: str = Field("Genel", description="Module the bug belongs to.")
    days_open: int = Field(0, description="Days since created, 0 if unparseable.")
    code: str = Field(description="Finding type.")
    params: dict[str, Any] = Field(default_factory=dict, description="Sentence values.")


class RisingUnattendedModule(BlindSpotFinding):
    """A module whose bug count is climbing with nobody working on it."""
    module: str = Field(description="Module name.")
    total_bugs: int = Field(0, description="Total bugs in the module.")
    open_bugs: int = Field(0, description="Open bugs in the module.")
    recent_bugs: int = Field(0, description="Bugs filed inside the 30-day window.")
    in_progress: int = Field(0, description="Always 0 — the category requires it.")


class BlindSpotSummary(BaseModel):
    """Counts across the four categories."""
    total_blind_spots: int = Field(0, description="Sum of all four categories.")
    critical_spots: int = Field(
        0,
        description="Neglected bugs plus CRITICAL unanalyzed modules. Stale and "
                    "rising findings are not counted.",
    )
    categories: dict[str, int] = Field(
        default_factory=dict,
        description="Per-category counts, keyed by category name.",
    )


class BlindSpotReport(BaseModel):
    """GET /blind-spots.

    Added when the payload changed from carrying "recommendation" sentences to
    carrying code/params. The endpoint previously returned the detector's dict
    raw, so its literal shape was the only contract — which is how that break
    reached a public endpoint unobserved.
    """
    unanalyzed_risky_modules: list[UnanalyzedRiskyModule] = Field(default_factory=list)
    neglected_critical_bugs: list[BlindSpotBug] = Field(default_factory=list)
    stale_bugs: list[BlindSpotBug] = Field(default_factory=list)
    rising_unattended: list[RisingUnattendedModule] = Field(default_factory=list)
    summary: BlindSpotSummary = Field(default_factory=BlindSpotSummary)


class PatternResponse(BaseModel):
    """One item of GET /patterns.

    Added in Faz 5C for the same reason BlindSpotReport was added in 5A: the
    endpoint returned the detector's dict raw, with no response_model and no
    model here, so its literal shape WAS the contract — and 5C changed that
    shape by replacing the ready-made "summary" sentence with code/params.
    Without a model the break would have shipped unobserved a second time.

    No `bugs` field, deliberately. The route calls detect_patterns with
    include_bugs=False and that branch pops the key entirely
    (services/analysis_service.py), so it is never in the HTTP response.
    Declaring it optional would make model_dump() put a null back and break the
    round-trip comparison that makes this model checkable at all.
    """
    pattern_id: int = Field(description="1-based index within this response.")
    bug_keys: list[str] = Field(default_factory=list, description="Jira keys in the cluster.")
    common_keywords: list[str] = Field(
        default_factory=list, description="Up to 8 words shared by two or more bugs."
    )
    common_component: str = Field("Genel", description="Modal component across the cluster.")
    common_priority: str = Field("Medium", description="Modal Jira priority.")
    code: str = Field(description="Finding type. Always 'pattern_theme' today.")
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Values the sentence needs: bug_count and up to 5 keywords.",
    )
    severity: str = Field("low", description="critical / high / medium / low.")
    bug_count: int = Field(0, description="Bugs in the cluster.")


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = Field("ok", description="Service status.")
    jira_configured: bool = Field(False, description="Whether Jira credentials are set.")
    llm_configured: bool = Field(False, description="Whether LLM API key is set.")
    mock_mode: bool = Field(False, description="Whether mock data mode is active.")
    bugs_loaded: int = Field(0, description="Number of bugs currently loaded.")
    daily_requests_used: int = Field(0, description="LLM API calls made today.")
    daily_requests_limit: int = Field(50, description="Max LLM API calls per day.")


class ErrorResponse(BaseModel):
    """Standard error response."""
    detail: str = Field(..., description="Human-readable error message.")
    error_code: str | None = Field(None, description="Machine-readable error code.")


# =============================================================================
# Rate Limit Models
# =============================================================================

class RateLimitStatus(BaseModel):
    """Current rate limit status."""
    daily_used: int = Field(0, description="API calls used today.")
    daily_limit: int = Field(50, description="Daily limit.")
    remaining: int = Field(50, description="Remaining calls today.")
    resets_at: str = Field(..., description="ISO timestamp when the counter resets (midnight).")
