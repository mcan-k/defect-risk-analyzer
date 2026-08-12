"""
Analysis Service — orchestrates scoring, the vector store, persistence and the LLM.

This is the single entry point for the dashboard, the FastAPI server and the CI
analyzer. It owns no algorithms of its own: risk scoring lives in `core.scoring`,
ChromaDB in `adapters.vector_store`, JSON persistence in
`adapters.results_repository`.

Key architectural rule: risk scores are calculated in Python, NOT by the LLM.
The LLM interprets pre-calculated statistics and generates reasoning.

Concurrency: every path that reaches the LLM is serialized by `_llm_lock`. The
lock spans the daily-limit check, the provider call and the counter increment,
so two callers cannot both pass the limit check before either has incremented.
Streamlit serves browser sessions on separate threads and FastAPI dispatches
through `asyncio.to_thread`, so a `threading.Lock` is the correct primitive for
both consumers — an `asyncio.Semaphore` would not protect the Streamlit path.
"""

import logging
import threading
import time
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from typing import Any

from defect_risk_analyzer import config
from defect_risk_analyzer.adapters.results_repository import ResultsRepository
from defect_risk_analyzer.adapters.vector_store import VectorStore
from defect_risk_analyzer.anonymizer import DataAnonymizer
from defect_risk_analyzer.component_classifier import classify_bugs
from defect_risk_analyzer.core import scoring
from defect_risk_analyzer.llm_provider import (
    LLMError,
    LLMProvider,
    RateLimitError,
    create_llm_provider,
)
from defect_risk_analyzer.prompt_templates import (
    SYSTEM_PROMPT,
    build_user_prompt,
    build_webhook_prompt,
)

logger = logging.getLogger(__name__)


class AnalysisService:
    """Main analysis engine: statistics, similarity search and LLM interpretation."""

    def __init__(
        self,
        vector_store: VectorStore | None = None,
        repository: ResultsRepository | None = None,
        anonymizer: DataAnonymizer | None = None,
        llm: LLMProvider | None = None,
    ) -> None:
        self._vector_store = vector_store or VectorStore()
        self._repository = repository or ResultsRepository()
        self._anonymizer = anonymizer or DataAnonymizer()
        self._bugs: list[dict[str, Any]] = []

        # An injected provider is used as-is; otherwise one is created lazily on
        # first use so that constructing the service never needs credentials.
        self._llm: LLMProvider | None = llm

        self._llm_lock = threading.Lock()
        self._daily_request_count: int = 0
        self._daily_reset_date: str = datetime.now().strftime("%Y-%m-%d")

    # ------------------------------------------------------------------
    # Bug data
    # ------------------------------------------------------------------

    def load_bugs(self, bugs: list[dict[str, Any]]) -> int:
        """
        Load bugs into memory and sync them to the vector store.

        Returns:
            Number of bugs indexed.
        """
        self._bugs = bugs

        # Auto-classify bugs with missing components
        classify_bugs(self._bugs)

        return self._vector_store.upsert_bugs(bugs)

    def get_bugs(self) -> list[dict[str, Any]]:
        """Return currently loaded bugs."""
        return list(self._bugs)

    def find_similar_bugs(self, query: str, n_results: int = 5) -> list[dict[str, Any]]:
        """Find similar bugs via the vector store."""
        return self._vector_store.query_similar(query, n_results)

    # ------------------------------------------------------------------
    # Deterministic risk scoring
    # ------------------------------------------------------------------

    def calculate_module_stats(self) -> dict[str, dict[str, Any]]:
        """Per-module statistics for the currently loaded bugs."""
        return scoring.calculate_module_stats(self._bugs)

    def calculate_risk_score(self, module_name: str, module_stats: dict[str, Any]) -> int:
        """Deterministic risk score for one module."""
        return scoring.calculate_risk_score(module_name, module_stats)

    def calculate_risk_for_query(self, query: str) -> tuple[int, str, str]:
        """
        Calculate risk score for a free-text query by finding the best matching module.

        Returns:
            Tuple of (risk_score, risk_level, matched_module).
        """
        module_stats = self.calculate_module_stats()

        if not module_stats:
            return (0, "LOW", "Unknown")

        # Find the module most relevant to the query
        query_lower = query.lower()
        best_module = None
        best_score = 0

        for module_name, stats in module_stats.items():
            # Simple keyword matching — enhanced by vector similarity below
            if module_name.lower() in query_lower:
                score = self.calculate_risk_score(module_name, stats)
                if score > best_score:
                    best_score = score
                    best_module = module_name

        # If no direct match, use the most common module among similar bugs
        if best_module is None:
            similar = self.find_similar_bugs(query, n_results=3)
            if similar:
                module_counter = Counter(
                    b.get("component", "Unknown") for b in similar
                )
                best_module = module_counter.most_common(1)[0][0]
                if best_module in module_stats:
                    best_score = self.calculate_risk_score(
                        best_module, module_stats[best_module]
                    )

        if best_module is None:
            best_module = "Unknown"

        return (best_score, scoring.get_risk_level(best_score), best_module)

    # ------------------------------------------------------------------
    # LLM plumbing
    # ------------------------------------------------------------------

    def _check_daily_limit(self) -> None:
        """Check and enforce the daily request limit. Resets at midnight.

        Caller must hold `_llm_lock`.
        """
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._daily_reset_date:
            self._daily_request_count = 0
            self._daily_reset_date = today

        if self._daily_request_count >= config.MAX_DAILY_REQUESTS:
            raise RateLimitError(
                f"Daily LLM request limit reached ({config.MAX_DAILY_REQUESTS}). "
                f"Resets at midnight.",
                retry_after_seconds=0,
            )

    def _get_llm(self) -> LLMProvider:
        """Lazy-initialize the LLM provider."""
        if self._llm is None:
            self._llm = create_llm_provider()
        return self._llm

    def reset_llm(self) -> None:
        """Drop the provider so the next call picks up new configuration.

        Deliberately does NOT take `_llm_lock`: that lock is held for the whole
        duration of an analysis, so waiting for it would make /reload-config
        hang behind an in-flight LLM call. The assignment is atomic, and an
        analysis already holding a provider reference finishes with it.
        """
        self._llm = None
        logger.info("LLM provider reset. Will reinitialize on next analysis.")

    def get_daily_request_count(self) -> int:
        """Current daily LLM request count.

        Lock-free for the same reason as reset_llm: /health must stay responsive
        while an analysis is running. A concurrent increment only means the
        caller sees a count one request stale.
        """
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._daily_reset_date:
            self._daily_request_count = 0
            self._daily_reset_date = today
        return self._daily_request_count

    def _call_llm(self, user_prompt: str) -> dict[str, Any]:
        """Sleep for rate limiting, call the provider, count the request.

        Caller must hold `_llm_lock`, and must have called `_check_daily_limit`
        first: the check happens before the call, the increment after it, so a
        failed call does not consume quota.
        """
        llm = self._get_llm()

        # Respect rate limiting sleep
        if config.GROQ_SLEEP > 0:
            time.sleep(config.GROQ_SLEEP)

        response = llm.analyze(SYSTEM_PROMPT, user_prompt)
        self._daily_request_count += 1
        return response

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def analyze_bug(
        self,
        query: str,
        bug_data: dict[str, Any] | None = None,
        source: str = "live_analysis",
    ) -> dict[str, Any]:
        """
        Full analysis pipeline for a single bug or query.

        Args:
            query: Bug summary or area to analyze.
            bug_data: Full bug record (optional).
            source: Origin tag — "live_analysis", "bulk_analysis", "webhook".

        Returns:
            BugRiskResult-compatible dict.
        """
        with self._llm_lock:
            self._check_daily_limit()

            module_stats = self.calculate_module_stats()

            # Determine risk score
            if bug_data:
                module = bug_data.get("component", "Unknown") or "Unknown"
                stats_for_module = module_stats.get(module, {})
                risk_score = self.calculate_risk_score(module, stats_for_module)
            else:
                risk_score, _, _ = self.calculate_risk_for_query(query)

            risk_level = scoring.get_risk_level(risk_score)

            similar_bugs = self.find_similar_bugs(query, n_results=5)

            # Anonymize before the LLM call (if enabled)
            if config.ANONYMIZE_DATA:
                anon_query = self._anonymizer.anonymize_query(query)
                anon_bug_data = None
                if bug_data:
                    anon_bugs = self._anonymizer.anonymize_bugs([bug_data])
                    anon_bug_data = anon_bugs[0] if anon_bugs else None
                anon_similar = (
                    self._anonymizer.anonymize_bugs(similar_bugs) if similar_bugs else []
                )
            else:
                anon_query = query
                anon_bug_data = bug_data
                anon_similar = similar_bugs

            user_prompt = build_user_prompt(
                query=anon_query,
                risk_score=risk_score,
                risk_level=risk_level,
                module_stats=module_stats,
                similar_bugs=anon_similar,
                bug_data=anon_bug_data,
            )

            llm_response = self._call_llm(user_prompt)

            # De-anonymize LLM output (if anonymization was used)
            reasoning = llm_response.get("reasoning", "")
            if config.ANONYMIZE_DATA:
                reasoning = self._anonymizer.deanonymize_text(reasoning)

            result = {
                "bug_key": bug_data.get("key") if bug_data else None,
                "query": query,
                "risk_score": risk_score,
                "risk_level": risk_level,
                "reasoning": reasoning,
                "affected_modules": llm_response.get("affected_modules", []),
                "test_scenarios": llm_response.get("test_scenarios", []),
                "recommended_actions": llm_response.get("recommended_actions", []),
                "analyzed_at": datetime.now().isoformat(),
                "source": source,
            }

            self._persist(result, module_stats)

        return result

    def analyze_bug_for_webhook(self, bug_data: dict[str, Any]) -> dict[str, Any]:
        """
        Simplified analysis for webhook-triggered events (no similar bug search).

        Args:
            bug_data: Bug record from a Jira webhook.

        Returns:
            BugRiskResult-compatible dict.
        """
        with self._llm_lock:
            self._check_daily_limit()

            module_stats = self.calculate_module_stats()
            module = bug_data.get("component", "Unknown") or "Unknown"
            stats_for_module = module_stats.get(module, {})
            risk_score = self.calculate_risk_score(module, stats_for_module)
            risk_level = scoring.get_risk_level(risk_score)

            # Anonymize (if enabled)
            if config.ANONYMIZE_DATA:
                anon_bugs = self._anonymizer.anonymize_bugs([bug_data])
                anon_bug_data = anon_bugs[0] if anon_bugs else bug_data
            else:
                anon_bug_data = bug_data

            # Webhook prompt skips similar bugs for speed
            user_prompt = build_webhook_prompt(
                bug_data=anon_bug_data,
                risk_score=risk_score,
                risk_level=risk_level,
                module_stats=module_stats,
            )

            llm_response = self._call_llm(user_prompt)

            reasoning = llm_response.get("reasoning", "")
            if config.ANONYMIZE_DATA:
                reasoning = self._anonymizer.deanonymize_text(reasoning)

            result = {
                "bug_key": bug_data.get("key"),
                "query": bug_data.get("summary", ""),
                "risk_score": risk_score,
                "risk_level": risk_level,
                "reasoning": reasoning,
                "affected_modules": llm_response.get("affected_modules", []),
                "test_scenarios": llm_response.get("test_scenarios", []),
                "recommended_actions": llm_response.get("recommended_actions", []),
                "analyzed_at": datetime.now().isoformat(),
                "source": "webhook",
            }

            self._persist(result, module_stats)
            if not self._repository.append_webhook_result(result):
                logger.warning("Webhook result for %s was not persisted.", result["bug_key"])

        return result

    def analyze_bulk(
        self,
        bug_keys: list[str],
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> dict[str, Any]:
        """
        Analyze several bugs in sequence, with a circuit breaker.

        On the first RateLimitError the run stops immediately and every
        remaining key is reported as skipped — one 429 means the quota is gone,
        so continuing would only burn time and produce more 429s.

        Unknown keys and per-bug failures are skipped without tripping the
        breaker.

        Args:
            bug_keys: Keys to analyze, in order.
            on_progress: Optional callback invoked after each key with
                (index, total, bug_key). Index is 1-based. Exceptions raised by
                the callback are not caught.

        Returns:
            BulkAnalyzeResponse-compatible dict. `results` holds plain result
            dicts; the API layer wraps them in its response model.
        """
        results: list[dict[str, Any]] = []
        skipped_keys: list[str] = []
        circuit_breaker_triggered = False

        # Build lookup map
        bug_map = {bug.get("key"): bug for bug in self.get_bugs()}
        total = len(bug_keys)

        for index, bug_key in enumerate(bug_keys, start=1):
            # Circuit breaker: skip all remaining if triggered
            if circuit_breaker_triggered:
                skipped_keys.append(bug_key)
                if on_progress:
                    on_progress(index, total, bug_key)
                continue

            bug_data = bug_map.get(bug_key)
            if bug_data is None:
                skipped_keys.append(bug_key)
                if on_progress:
                    on_progress(index, total, bug_key)
                continue

            try:
                results.append(
                    self.analyze_bug(
                        query=bug_data.get("summary", bug_key),
                        bug_data=bug_data,
                        source="bulk_analysis",
                    )
                )

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

            if on_progress:
                on_progress(index, total, bug_key)

        return {
            "total": total,
            "analyzed": len(results),
            "skipped": len(skipped_keys),
            "results": results,
            "skipped_keys": skipped_keys,
            "circuit_breaker_triggered": circuit_breaker_triggered,
        }

    # ------------------------------------------------------------------
    # Detection helpers (no LLM)
    # ------------------------------------------------------------------

    def detect_patterns(
        self,
        similarity_threshold: float = 0.35,
        include_bugs: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Detect bug patterns — groups of similar bugs that may share a root cause.

        Args:
            similarity_threshold: Minimum similarity to group bugs (0-1).
            include_bugs: Keep the full bug objects in each pattern. Callers
                that only render keys pass False to avoid large payloads.

        Returns:
            List of pattern dicts with bug clusters and common keywords.
        """
        from defect_risk_analyzer.pattern_detector import detect_patterns

        patterns = detect_patterns(
            self._bugs, self._vector_store.collection, similarity_threshold
        )
        if not include_bugs:
            for pattern in patterns:
                pattern.pop("bugs", None)
        return patterns

    def find_duplicate_bugs(self, bug: dict[str, Any]) -> list[dict[str, Any]]:
        """Find potential duplicate bugs for a given bug."""
        from defect_risk_analyzer.pattern_detector import find_duplicates

        return find_duplicates(bug, self._vector_store.collection)

    def detect_blind_spots(self) -> dict[str, Any]:
        """Detect blind spots — untested risky areas and neglected bugs."""
        from defect_risk_analyzer.blind_spot_detector import detect_blind_spots

        module_stats = self.calculate_module_stats()
        risk_scores = {
            module_name: self.calculate_risk_score(module_name, stats)
            for module_name, stats in module_stats.items()
        }

        return detect_blind_spots(
            bugs=self._bugs,
            module_stats=module_stats,
            analysis_results=self.get_all_results(),
            risk_scores=risk_scores,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self, result: dict[str, Any], module_stats: dict[str, dict]) -> None:
        """Save an analysis result and refresh the defect density map."""
        if not self._repository.upsert_result(result):
            logger.warning(
                "Analysis result for %s was not persisted.", result.get("bug_key") or "query"
            )
        self._update_defect_density(module_stats)

    def _update_defect_density(self, module_stats: dict[str, dict]) -> None:
        """Recalculate and save the defect density map."""
        density = {}
        for module_name, stats in module_stats.items():
            score = self.calculate_risk_score(module_name, stats)
            density[module_name] = {
                "bug_density": stats.get("bug_density", 0),
                "total_bugs": stats.get("total_bugs", 0),
                "risk_score": score,
                "risk_level": scoring.get_risk_level(score),
            }
        self._repository.save_defect_density(density)

    def get_all_results(self) -> list[dict[str, Any]]:
        """All analysis results from disk."""
        return self._repository.load_results()

    def get_webhook_results(self) -> list[dict[str, Any]]:
        """Webhook analysis results from disk."""
        return self._repository.load_webhook_results()

    def get_defect_density(self) -> dict[str, Any]:
        """Defect density map from disk."""
        return self._repository.load_defect_density()
