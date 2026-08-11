"""
Pydantic request and response models for the Predictive Defect Analysis Engine API.

All API endpoints use these models for request validation and response serialization.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# =============================================================================
# Request Models
# =============================================================================

class AnalyzeRequest(BaseModel):
    """Single bug or area risk analysis request."""
    bug_key: Optional[str] = Field(
        None,
        description="Jira bug key (e.g., 'AP-101'). If provided, fetches bug details from loaded data.",
        examples=["AP-101"],
    )
    query: Optional[str] = Field(
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
    jira_url: Optional[str] = None
    jira_email: Optional[str] = None
    jira_api_token: Optional[str] = None
    jira_project_key: Optional[str] = None
    llm_provider: Optional[str] = None
    groq_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    max_daily_requests: Optional[int] = None
    groq_sleep: Optional[float] = None
    use_mock_data: Optional[bool] = None


# =============================================================================
# Response Models
# =============================================================================

class BugRiskResult(BaseModel):
    """Risk analysis result for a single bug or query."""
    bug_key: Optional[str] = Field(None, description="Jira bug key if applicable.")
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
    last_updated: Optional[str] = Field(None, description="ISO timestamp of last analysis run.")


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
    error_code: Optional[str] = Field(None, description="Machine-readable error code.")


# =============================================================================
# Rate Limit Models
# =============================================================================

class RateLimitStatus(BaseModel):
    """Current rate limit status."""
    daily_used: int = Field(0, description="API calls used today.")
    daily_limit: int = Field(50, description="Daily limit.")
    remaining: int = Field(50, description="Remaining calls today.")
    resets_at: str = Field(..., description="ISO timestamp when the counter resets (midnight).")
