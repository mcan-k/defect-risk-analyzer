"""
FastAPI Backend — REST API for the Predictive Defect Analysis Engine.

Endpoints (14 total):

System:
  GET  /health         — Service health check (no auth required)
  POST /reload-config  — Re-read .env and apply settings without a restart
  GET  /rate-limit     — Current rate limit status

Analysis:
  POST /analyze        — Single bug/area risk analysis
  POST /analyze/bulk   — Bulk analysis with circuit breaker
  GET  /patterns       — Bug clusters and common root causes
  GET  /patterns/{bug_key}/duplicates — Similar/duplicate bugs for one bug

Data:
  GET  /risks          — Current risk scores (reads saved data, no new analysis)
  POST /refresh        — Fetch from Jira + sync ChromaDB
  GET  /bugs           — List loaded bugs
  GET  /results        — All analysis results
  GET  /results/webhook — Webhook-triggered analysis results
  GET  /blind-spots    — Risky areas that have not been analyzed yet

Webhook:
  POST /webhook/jira   — Auto-analyze on Jira bug create/update
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from defect_risk_analyzer import __version__, config
from defect_risk_analyzer.api_auth import require_api_key
from defect_risk_analyzer.api_models import (
    AnalyzeRequest,
    BugRiskResult,
    BulkAnalyzeRequest,
    BulkAnalyzeResponse,
    ErrorResponse,
    HealthResponse,
    RateLimitStatus,
    RiskSummary,
    WebhookPayload,
)
from defect_risk_analyzer.core import scoring
from defect_risk_analyzer.jira_client import load_bugs_from_file, refresh_data
from defect_risk_analyzer.llm_provider import LLMError, RateLimitError
from defect_risk_analyzer.services.analysis_service import AnalysisService

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global State
# ---------------------------------------------------------------------------
analyzer = AnalysisService()

# Semaphore: max 1 concurrent LLM request (protects against parallel cost explosion)
llm_semaphore = asyncio.Semaphore(1)


# ---------------------------------------------------------------------------
# Lifespan — startup / shutdown
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load bug data on startup."""
    logger.info("Starting Predictive Defect Analysis Engine...")
    logger.info("Mock mode: %s", config.USE_MOCK_DATA)
    logger.info("LLM provider: %s", config.LLM_PROVIDER)
    logger.info("Daily request limit: %d", config.MAX_DAILY_REQUESTS)

    # Load bugs into analyzer
    bugs = load_bugs_from_file()
    if bugs:
        analyzer.load_bugs(bugs)
        logger.info("Loaded %d bugs into analyzer.", len(bugs))
    else:
        logger.warning("No bugs loaded. Use /refresh or enable mock mode.")

    yield

    logger.info("Shutting down...")


# ---------------------------------------------------------------------------
# App Initialization
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Predictive Defect Analysis Engine",
    description="AI-powered Jira defect risk prediction using RAG and ISTQB principles.",
    version=__version__,
    lifespan=lifespan,
)

# CORS — allow Streamlit frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Health Check (no auth)
# =============================================================================

@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """Service health check — no authentication required."""
    return HealthResponse(
        status="ok",
        jira_configured=config.is_jira_configured(),
        llm_configured=config.is_llm_configured(),
        mock_mode=config.USE_MOCK_DATA,
        bugs_loaded=len(analyzer.get_bugs()),
        daily_requests_used=analyzer.get_daily_request_count(),
        daily_requests_limit=config.MAX_DAILY_REQUESTS,
    )


# =============================================================================
# Reload Configuration (called by Dashboard after settings change)
# =============================================================================

@app.post(
    "/reload-config",
    dependencies=[Depends(require_api_key)],
    tags=["System"],
)
async def reload_config():
    """
    Reload configuration from .env file.

    Called automatically by the Dashboard Settings page after saving changes.
    Reloads config values and reinitializes the LLM provider so the API
    picks up new credentials without a restart.
    """
    config.reload()
    analyzer.reset_llm()
    logger.info(
        "Config reloaded. Jira: %s, LLM: %s (%s), Mock: %s",
        config.is_jira_configured(),
        config.is_llm_configured(),
        config.LLM_PROVIDER,
        config.USE_MOCK_DATA,
    )
    return {
        "status": "ok",
        "jira_configured": config.is_jira_configured(),
        "llm_configured": config.is_llm_configured(),
        "llm_provider": config.LLM_PROVIDER,
        "mock_mode": config.USE_MOCK_DATA,
    }


# =============================================================================
# Single Analysis
# =============================================================================

@app.post(
    "/analyze",
    response_model=BugRiskResult,
    responses={429: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    dependencies=[Depends(require_api_key)],
    tags=["Analysis"],
)
async def analyze_single(request: AnalyzeRequest):
    """
    Analyze a single bug or area for risk.

    Provide either `bug_key` (to analyze a known bug) or `query` (free-text area).
    """
    if not request.bug_key and not request.query:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide either 'bug_key' or 'query'.",
        )

    # Find bug data if bug_key provided
    bug_data = None
    query = request.query or ""

    if request.bug_key:
        for bug in analyzer.get_bugs():
            if bug.get("key") == request.bug_key:
                bug_data = bug
                query = bug.get("summary", request.bug_key)
                break
        if bug_data is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Bug '{request.bug_key}' not found in loaded data.",
            )

    async with llm_semaphore:
        try:
            result = await asyncio.to_thread(
                analyzer.analyze_bug,
                query=query,
                bug_data=bug_data,
                source="live_analysis",
            )
            return BugRiskResult(**result)

        except RateLimitError as e:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=str(e),
            )
        except LLMError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"LLM analysis failed: {e}",
            )
        except Exception as e:
            logger.error("Unexpected error in /analyze: %s", e, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Analysis failed: {e}",
            )


# =============================================================================
# Bulk Analysis (with Circuit Breaker)
# =============================================================================

@app.post(
    "/analyze/bulk",
    response_model=BulkAnalyzeResponse,
    responses={429: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    dependencies=[Depends(require_api_key)],
    tags=["Analysis"],
)
async def analyze_bulk(request: BulkAnalyzeRequest):
    """
    Bulk analysis with circuit breaker.

    On first 429 rate limit error → stops immediately, marks remaining bugs as skipped.
    """
    results: list[BugRiskResult] = []
    skipped_keys: list[str] = []
    circuit_breaker_triggered = False
    all_bugs = analyzer.get_bugs()

    # Build lookup map
    bug_map = {bug.get("key"): bug for bug in all_bugs}

    for bug_key in request.bug_keys:
        # Circuit breaker: skip all remaining if triggered
        if circuit_breaker_triggered:
            skipped_keys.append(bug_key)
            continue

        bug_data = bug_map.get(bug_key)
        if bug_data is None:
            skipped_keys.append(bug_key)
            continue

        async with llm_semaphore:
            try:
                result = await asyncio.to_thread(
                    analyzer.analyze_bug,
                    query=bug_data.get("summary", bug_key),
                    bug_data=bug_data,
                    source="bulk_analysis",
                )
                results.append(BugRiskResult(**result))

            except RateLimitError:
                # CIRCUIT BREAKER: stop immediately on 429
                circuit_breaker_triggered = True
                skipped_keys.append(bug_key)
                logger.warning(
                    "Circuit breaker triggered at bug '%s'. "
                    "Remaining bugs will be skipped.",
                    bug_key,
                )

            except LLMError as e:
                logger.error("LLM error analyzing bug '%s': %s", bug_key, e)
                skipped_keys.append(bug_key)

            except Exception as e:
                logger.exception("Unexpected error analyzing bug '%s': %s", bug_key, e)
                skipped_keys.append(bug_key)

    return BulkAnalyzeResponse(
        total=len(request.bug_keys),
        analyzed=len(results),
        skipped=len(skipped_keys),
        results=results,
        skipped_keys=skipped_keys,
        circuit_breaker_triggered=circuit_breaker_triggered,
    )


# =============================================================================
# Risk Overview (read-only, no new analysis)
# =============================================================================

@app.get(
    "/risks",
    response_model=RiskSummary,
    dependencies=[Depends(require_api_key)],
    tags=["Data"],
)
async def get_risks():
    """Get current risk scores and defect density map. No new analysis performed."""
    module_stats = analyzer.calculate_module_stats()
    defect_density = analyzer.get_defect_density()
    all_results = analyzer.get_all_results()

    module_risks = {}
    for module_name, stats in module_stats.items():
        score = analyzer.calculate_risk_score(module_name, stats)
        module_risks[module_name] = {
            "score": score,
            "level": scoring.get_risk_level(score),
            "bug_count": stats.get("total_bugs", 0),
            "open_count": stats.get("open_bugs", 0),
        }

    last_updated = None
    if all_results:
        last_updated = max(r.get("analyzed_at", "") for r in all_results)

    return RiskSummary(
        total_bugs=len(analyzer.get_bugs()),
        analyzed_count=len(all_results),
        module_risks=module_risks,
        defect_density={m: d.get("bug_density", 0) for m, d in defect_density.items()},
        last_updated=last_updated,
    )


# =============================================================================
# Refresh Data
# =============================================================================

@app.post(
    "/refresh",
    dependencies=[Depends(require_api_key)],
    tags=["Data"],
)
async def refresh():
    """Fetch fresh data from Jira (or load mock data) and sync ChromaDB."""
    try:
        bugs = await asyncio.to_thread(refresh_data)
        loaded = analyzer.load_bugs(bugs)
        return {
            "status": "ok",
            "bugs_fetched": len(bugs),
            "bugs_loaded": loaded,
            "mock_mode": config.USE_MOCK_DATA,
        }
    except Exception as e:
        logger.error("Refresh failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Refresh failed: {e}",
        )


# =============================================================================
# Jira Webhook
# =============================================================================

@app.post(
    "/webhook/jira",
    response_model=BugRiskResult,
    responses={429: {"model": ErrorResponse}},
    dependencies=[Depends(require_api_key)],
    tags=["Webhook"],
)
async def jira_webhook(payload: WebhookPayload):
    """
    Auto-analyze a bug when Jira sends a webhook event (create/update).
    """
    event = payload.webhookEvent
    if event not in ("jira:issue_created", "jira:issue_updated"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported webhook event: {event}",
        )

    # Normalize the webhook issue data
    issue = payload.issue
    fields = issue.get("fields", {})

    # Check if it's a Bug type
    issue_type = fields.get("issuetype", {}).get("name", "")
    if issue_type.lower() != "bug":
        return BugRiskResult(
            query=f"Skipped non-bug issue type: {issue_type}",
            risk_score=0,
            risk_level="LOW",
            reasoning=f"Issue type '{issue_type}' is not a Bug. Skipped.",
            source="webhook",
        )

    # Build simplified bug data from webhook payload
    components = fields.get("components", [])
    priority_data = fields.get("priority")
    status_data = fields.get("status")

    bug_data = {
        "key": issue.get("key", "UNKNOWN"),
        "summary": fields.get("summary", ""),
        "description": fields.get("description", ""),
        "priority": priority_data.get("name", "Medium") if priority_data else "Medium",
        "status": status_data.get("name", "Open") if status_data else "Open",
        "component": components[0].get("name", "Unknown") if components else "Unknown",
        "created": fields.get("created", datetime.now().isoformat()),
    }

    async with llm_semaphore:
        try:
            result = await asyncio.to_thread(
                analyzer.analyze_bug_for_webhook,
                bug_data=bug_data,
            )
            return BugRiskResult(**result)

        except RateLimitError as e:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=str(e),
            )
        except Exception as e:
            logger.error("Webhook analysis failed: %s", e, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Webhook analysis failed: {e}",
            )


# =============================================================================
# Rate Limit Status
# =============================================================================

@app.get(
    "/rate-limit",
    response_model=RateLimitStatus,
    dependencies=[Depends(require_api_key)],
    tags=["System"],
)
async def rate_limit_status():
    """Get current rate limit usage."""
    used = analyzer.get_daily_request_count()
    limit = config.MAX_DAILY_REQUESTS

    # Next midnight
    now = datetime.now()
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    return RateLimitStatus(
        daily_used=used,
        daily_limit=limit,
        remaining=max(0, limit - used),
        resets_at=tomorrow.isoformat(),
    )


# =============================================================================
# Results Endpoints (for dashboard)
# =============================================================================

@app.get(
    "/results",
    dependencies=[Depends(require_api_key)],
    tags=["Data"],
)
async def get_results():
    """Get all analysis results."""
    return analyzer.get_all_results()


@app.get(
    "/results/webhook",
    dependencies=[Depends(require_api_key)],
    tags=["Data"],
)
async def get_webhook_results():
    """Get webhook analysis results."""
    return analyzer.get_webhook_results()


@app.get(
    "/bugs",
    dependencies=[Depends(require_api_key)],
    tags=["Data"],
)
async def get_bugs():
    """Get all loaded bugs."""
    return analyzer.get_bugs()


# =============================================================================
# Pattern Detection
# =============================================================================

@app.get(
    "/patterns",
    dependencies=[Depends(require_api_key)],
    tags=["Analysis"],
)
async def get_patterns():
    """Detect bug patterns — groups of similar bugs that may share a root cause."""
    try:
        patterns = await asyncio.to_thread(analyzer.detect_patterns)
        # Remove full bug objects from response (too large), keep keys
        for p in patterns:
            p.pop("bugs", None)
        return patterns
    except Exception as e:
        logger.error("Pattern detection failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pattern detection failed: {e}",
        )


@app.get(
    "/patterns/{bug_key}/duplicates",
    dependencies=[Depends(require_api_key)],
    tags=["Analysis"],
)
async def get_duplicates(bug_key: str):
    """Find potential duplicate bugs for a given bug key."""
    bug_data = None
    for bug in analyzer.get_bugs():
        if bug.get("key") == bug_key:
            bug_data = bug
            break

    if bug_data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bug '{bug_key}' not found.",
        )

    try:
        duplicates = await asyncio.to_thread(analyzer.find_duplicate_bugs, bug_data)
        return {"bug_key": bug_key, "potential_duplicates": duplicates}
    except Exception as e:
        logger.error("Duplicate search failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Duplicate search failed: {e}",
        )


# =============================================================================
# Blind Spot Detection
# =============================================================================

@app.get(
    "/blind-spots",
    dependencies=[Depends(require_api_key)],
    tags=["Analysis"],
)
async def get_blind_spots():
    """Detect untested risky areas, neglected bugs, and coverage gaps."""
    try:
        spots = await asyncio.to_thread(analyzer.detect_blind_spots)
        return spots
    except Exception as e:
        logger.error("Blind spot detection failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Blind spot detection failed: {e}",
        )


# =============================================================================
# Entry point (for direct run: python api.py)
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "defect_risk_analyzer.api:app",
        host=config.API_HOST,
        port=config.API_PORT,
        reload=True,
    )
