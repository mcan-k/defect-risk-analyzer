"""
Risk Analyzer — Core RAG engine for the Predictive Defect Analysis Engine.

Responsibilities:
  1. ChromaDB vector store management (load, query, sync)
  2. Deterministic risk scoring (calculate_module_stats, calculate_risk_score)
  3. LLM analysis orchestration (build prompt → call provider → parse response)

Key architectural rule: Risk scores are calculated in Python, NOT by the LLM.
The LLM interprets pre-calculated statistics and generates reasoning/recommendations.
"""

import json
import logging
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import config
from anonymizer import DataAnonymizer
from component_classifier import classify_bugs
from llm_provider import LLMProvider, RateLimitError, LLMError, create_llm_provider
from prompt_templates import SYSTEM_PROMPT, build_user_prompt, build_webhook_prompt

logger = logging.getLogger(__name__)


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
# Risk Analyzer Class
# =============================================================================

class RiskAnalyzer:
    """
    Main analysis engine combining ChromaDB, risk scoring, and LLM interpretation.
    """

    def __init__(self) -> None:
        self._chroma_client = None
        self._collection = None
        self._bugs: list[dict[str, Any]] = []
        self._anonymizer = DataAnonymizer()
        self._llm: LLMProvider | None = None
        self._daily_request_count: int = 0
        self._daily_reset_date: str = datetime.now().strftime("%Y-%m-%d")

    # ------------------------------------------------------------------
    # ChromaDB Management
    # ------------------------------------------------------------------

    def _get_collection(self):
        """Lazy-initialize ChromaDB collection."""
        if self._collection is not None:
            return self._collection

        try:
            import chromadb
            self._chroma_client = chromadb.PersistentClient(path=str(config.CHROMA_DB_DIR))
            self._collection = self._chroma_client.get_or_create_collection(
                name="defect_history",
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(
                "ChromaDB collection ready. Documents: %d",
                self._collection.count(),
            )
        except Exception as e:
            logger.error("Failed to initialize ChromaDB: %s", e)
            raise

        return self._collection

    def _reset_collection(self):
        """Delete and recreate ChromaDB collection to remove stale data."""
        try:
            if self._chroma_client is None:
                import chromadb
                self._chroma_client = chromadb.PersistentClient(path=str(config.CHROMA_DB_DIR))

            self._chroma_client.delete_collection("defect_history")
            self._collection = self._chroma_client.create_collection(
                name="defect_history",
                metadata={"hnsw:space": "cosine"},
            )
            logger.info("ChromaDB collection reset. Clean slate.")
        except Exception as e:
            logger.warning("Could not reset collection, falling back to get_or_create: %s", e)
            self._collection = self._chroma_client.get_or_create_collection(
                name="defect_history",
                metadata={"hnsw:space": "cosine"},
            )

    def load_bugs(self, bugs: list[dict[str, Any]]) -> int:
        """
        Load bugs into memory and sync to ChromaDB.

        Args:
            bugs: List of bug dictionaries from Jira or sample data.

        Returns:
            Number of bugs loaded into ChromaDB.
        """
        self._bugs = bugs

        # Auto-classify bugs with missing components
        classify_bugs(self._bugs)

        # Reset collection to remove stale data (mock + real data mixing)
        self._reset_collection()
        collection = self._collection

        # Prepare documents for ChromaDB
        ids = []
        documents = []
        metadatas = []

        for bug in bugs:
            bug_key = bug.get("key", "")
            if not bug_key:
                continue

            # Build searchable document text
            doc_text = (
                f"{bug.get('summary', '')} "
                f"{bug.get('description', '')} "
                f"{bug.get('component', '')} "
                f"{bug.get('priority', '')} "
                f"{bug.get('status', '')}"
            ).strip()

            if not doc_text:
                continue

            ids.append(bug_key)
            documents.append(doc_text)
            metadatas.append({
                "key": bug_key,
                "summary": bug.get("summary", ""),
                "priority": bug.get("priority", "Medium"),
                "status": bug.get("status", "Open"),
                "component": bug.get("component", "Unknown"),
                "created": bug.get("created", ""),
            })

        if not ids:
            logger.warning("No valid bugs to load into ChromaDB.")
            return 0

        # Upsert to ChromaDB (handles both insert and update)
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

        logger.info("Loaded %d bugs into ChromaDB.", len(ids))
        return len(ids)

    def find_similar_bugs(self, query: str, n_results: int = 5) -> list[dict[str, Any]]:
        """
        Find similar bugs using ChromaDB cosine similarity search.

        Args:
            query: Search query text.
            n_results: Maximum number of similar bugs to return.

        Returns:
            List of similar bug metadata dictionaries.
        """
        collection = self._get_collection()

        if collection.count() == 0:
            logger.info("ChromaDB is empty — no similar bugs to find.")
            return []

        # Limit n_results to collection size
        actual_n = min(n_results, collection.count())

        try:
            results = collection.query(
                query_texts=[query],
                n_results=actual_n,
            )
        except Exception as e:
            logger.error("ChromaDB query failed: %s", e)
            return []

        similar_bugs = []
        if results and results.get("metadatas"):
            for metadata in results["metadatas"][0]:
                similar_bugs.append(metadata)

        return similar_bugs

    # ------------------------------------------------------------------
    # Deterministic Risk Scoring
    # ------------------------------------------------------------------

    def calculate_module_stats(self) -> dict[str, dict[str, Any]]:
        """
        Calculate per-module statistics from loaded bugs.

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
        if not self._bugs:
            return {}

        # Group bugs by module/component
        module_bugs: dict[str, list[dict]] = {}
        for bug in self._bugs:
            module = bug.get("component", "Unknown") or "Unknown"
            module_bugs.setdefault(module, []).append(bug)

        total_all_bugs = len(self._bugs)
        stats: dict[str, dict[str, Any]] = {}

        for module, bugs in module_bugs.items():
            total = len(bugs)
            open_bugs = sum(
                1 for b in bugs
                if b.get("status", "").lower() not in ("done", "closed", "resolved")
            )
            closed_bugs = total - open_bugs
            open_ratio = open_bugs / total if total > 0 else 0

            # Bug density: module's share of total bugs (normalized)
            bug_density = total / total_all_bugs if total_all_bugs > 0 else 0

            # Priority distribution
            priority_dist = Counter(b.get("priority", "Medium") for b in bugs)

            # Weighted priority score
            weighted_score = sum(
                PRIORITY_WEIGHTS.get(p, DEFAULT_PRIORITY_WEIGHT) * count
                for p, count in priority_dist.items()
            )

            # Trend detection: count bugs created in last 30 days vs older
            thirty_days_ago = (datetime.now() - timedelta(days=30)).isoformat()
            recent_count = 0
            old_count = 0
            for b in bugs:
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

    def calculate_risk_score(self, module_name: str, module_stats: dict[str, Any]) -> int:
        """
        Calculate deterministic risk score for a module.

        Formula: base_score = (priority_factor × 60) + (bug_density × 40)
                 adjusted  = base_score × open_ratio_factor × trend_multiplier × volume_factor
                 clamped   = clamp(adjusted, 0, 100)

        Volume factor prevents modules with 1-2 bugs from reaching CRITICAL.
        You need statistical significance (3+ bugs) for a high confidence score.

        Args:
            module_name: Name of the module.
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
        # 1 bug = 0.4, 2 bugs = 0.65, 3 bugs = 0.85, 4+ bugs = 1.0
        volume_threshold = 4
        volume_factor = min(total_bugs / volume_threshold, 1.0)
        volume_factor = 0.4 + (volume_factor * 0.6)  # Range: 0.4 to 1.0

        # Calculate base score
        base_score = (
            (priority_factor * 60)      # Severity contributes up to 60
            + (bug_density * 40)         # Concentration contributes up to 40
        )

        # Apply multipliers
        adjusted = base_score * open_ratio_factor * trend_multiplier * volume_factor

        # Clamp to 0-100
        return max(0, min(100, int(round(adjusted))))

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
            # Simple keyword matching — enhanced by ChromaDB similarity
            if module_name.lower() in query_lower:
                score = self.calculate_risk_score(module_name, stats)
                if score > best_score:
                    best_score = score
                    best_module = module_name

        # If no direct match, use the highest-risk module among similar bugs
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

        risk_level = config.get_risk_level(best_score)
        return (best_score, risk_level, best_module)

    # ------------------------------------------------------------------
    # LLM Analysis
    # ------------------------------------------------------------------

    def _check_daily_limit(self) -> None:
        """Check and enforce daily request limit. Reset at midnight."""
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
        """Lazy-initialize LLM provider."""
        if self._llm is None:
            self._llm = create_llm_provider()
        return self._llm

    def reset_llm(self) -> None:
        """Reset LLM provider so next call creates a fresh one with new config."""
        self._llm = None
        logger.info("LLM provider reset. Will reinitialize on next analysis.")

    def analyze_bug(
        self,
        query: str,
        bug_data: dict[str, Any] | None = None,
        source: str = "live_analysis",
    ) -> dict[str, Any]:
        """
        Full analysis pipeline for a single bug or query.

        Steps:
          1. Check daily limit
          2. Calculate module stats and risk score
          3. Find similar bugs from ChromaDB
          4. Anonymize data
          5. Build prompt and call LLM
          6. De-anonymize response
          7. Save results

        Args:
            query: Bug summary or area to analyze.
            bug_data: Full bug record (optional).
            source: Origin tag — "live_analysis", "bulk_analysis", "webhook".

        Returns:
            BugRiskResult-compatible dict.
        """
        self._check_daily_limit()

        # Step 1: Calculate statistics
        module_stats = self.calculate_module_stats()

        # Step 2: Determine risk score
        if bug_data:
            module = bug_data.get("component", "Unknown") or "Unknown"
            stats_for_module = module_stats.get(module, {})
            risk_score = self.calculate_risk_score(module, stats_for_module)
        else:
            risk_score, _, _ = self.calculate_risk_for_query(query)

        risk_level = config.get_risk_level(risk_score)

        # Step 3: Find similar bugs
        similar_bugs = self.find_similar_bugs(query, n_results=5)

        # Step 4: Anonymize before LLM call (if enabled)
        if config.ANONYMIZE_DATA:
            anon_query = self._anonymizer.anonymize_query(query)
            anon_bug_data = None
            if bug_data:
                anon_bugs = self._anonymizer.anonymize_bugs([bug_data])
                anon_bug_data = anon_bugs[0] if anon_bugs else None
            anon_similar = self._anonymizer.anonymize_bugs(similar_bugs) if similar_bugs else []
        else:
            anon_query = query
            anon_bug_data = bug_data
            anon_similar = similar_bugs

        # Step 5: Build prompt
        user_prompt = build_user_prompt(
            query=anon_query,
            risk_score=risk_score,
            risk_level=risk_level,
            module_stats=module_stats,
            similar_bugs=anon_similar,
            bug_data=anon_bug_data,
        )

        # Step 6: Call LLM
        llm = self._get_llm()

        # Respect rate limiting sleep
        if config.GROQ_SLEEP > 0:
            time.sleep(config.GROQ_SLEEP)

        llm_response = llm.analyze(SYSTEM_PROMPT, user_prompt)
        self._daily_request_count += 1

        # Step 7: De-anonymize LLM output (if anonymization was used)
        reasoning = llm_response.get("reasoning", "")
        if config.ANONYMIZE_DATA:
            reasoning = self._anonymizer.deanonymize_text(reasoning)

        # Step 8: Build result
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

        # Step 9: Save results
        self._save_result(result)
        self._update_defect_density(module_stats)

        return result

    def analyze_bug_for_webhook(self, bug_data: dict[str, Any]) -> dict[str, Any]:
        """
        Simplified analysis for webhook-triggered events (no similar bug search).

        Args:
            bug_data: Bug record from Jira webhook.

        Returns:
            BugRiskResult-compatible dict.
        """
        self._check_daily_limit()

        module_stats = self.calculate_module_stats()
        module = bug_data.get("component", "Unknown") or "Unknown"
        stats_for_module = module_stats.get(module, {})
        risk_score = self.calculate_risk_score(module, stats_for_module)
        risk_level = config.get_risk_level(risk_score)

        # Anonymize (if enabled)
        if config.ANONYMIZE_DATA:
            anon_bugs = self._anonymizer.anonymize_bugs([bug_data])
            anon_bug_data = anon_bugs[0] if anon_bugs else bug_data
        else:
            anon_bug_data = bug_data

        # Build webhook prompt (no similar bugs for speed)
        user_prompt = build_webhook_prompt(
            bug_data=anon_bug_data,
            risk_score=risk_score,
            risk_level=risk_level,
            module_stats=module_stats,
        )

        # Call LLM
        llm = self._get_llm()
        if config.GROQ_SLEEP > 0:
            time.sleep(config.GROQ_SLEEP)

        llm_response = llm.analyze(SYSTEM_PROMPT, user_prompt)
        self._daily_request_count += 1

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

        self._save_result(result)
        self._save_webhook_result(result)
        self._update_defect_density(module_stats)

        return result

    # ------------------------------------------------------------------
    # Results Persistence
    # ------------------------------------------------------------------

    def _save_result(self, result: dict[str, Any]) -> None:
        """Save or update analysis result in analysis_results.json (upsert by bug_key)."""
        results = self._load_results_file(config.ANALYSIS_RESULTS_FILE)

        # Upsert: replace existing entry with same bug_key
        bug_key = result.get("bug_key")
        if bug_key:
            results = [r for r in results if r.get("bug_key") != bug_key]

        results.append(result)
        self._write_json(config.ANALYSIS_RESULTS_FILE, results)

    def _save_webhook_result(self, result: dict[str, Any]) -> None:
        """Append webhook result to webhook_results.json."""
        results = self._load_results_file(config.WEBHOOK_RESULTS_FILE)
        results.append(result)
        self._write_json(config.WEBHOOK_RESULTS_FILE, results)

    def _update_defect_density(self, module_stats: dict[str, dict]) -> None:
        """Recalculate and save defect density map."""
        density = {}
        for module_name, stats in module_stats.items():
            density[module_name] = {
                "bug_density": stats.get("bug_density", 0),
                "total_bugs": stats.get("total_bugs", 0),
                "risk_score": self.calculate_risk_score(module_name, stats),
                "risk_level": config.get_risk_level(
                    self.calculate_risk_score(module_name, stats)
                ),
            }
        self._write_json(config.DEFECT_DENSITY_FILE, density)

    def get_all_results(self) -> list[dict[str, Any]]:
        """Load all analysis results from disk."""
        return self._load_results_file(config.ANALYSIS_RESULTS_FILE)

    def get_webhook_results(self) -> list[dict[str, Any]]:
        """Load webhook results from disk."""
        return self._load_results_file(config.WEBHOOK_RESULTS_FILE)

    def get_defect_density(self) -> dict[str, Any]:
        """Load defect density map from disk."""
        if config.DEFECT_DENSITY_FILE.exists():
            try:
                with open(config.DEFECT_DENSITY_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                pass
        return {}

    def get_bugs(self) -> list[dict[str, Any]]:
        """Return currently loaded bugs."""
        return list(self._bugs)

    def detect_patterns(self, similarity_threshold: float = 0.35) -> list[dict[str, Any]]:
        """
        Detect bug patterns — groups of similar bugs that may share a root cause.

        Args:
            similarity_threshold: Minimum similarity to group bugs (0-1).

        Returns:
            List of pattern dicts with bug clusters and common keywords.
        """
        from pattern_detector import detect_patterns
        collection = self._get_collection()
        return detect_patterns(self._bugs, collection, similarity_threshold)

    def find_duplicate_bugs(self, bug: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Find potential duplicate bugs for a given bug.

        Args:
            bug: Bug dictionary to check.

        Returns:
            List of similar bugs with similarity scores.
        """
        from pattern_detector import find_duplicates
        collection = self._get_collection()
        return find_duplicates(bug, collection)

    def get_daily_request_count(self) -> int:
        """Return current daily LLM request count."""
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._daily_reset_date:
            self._daily_request_count = 0
            self._daily_reset_date = today
        return self._daily_request_count

    # ------------------------------------------------------------------
    # File I/O Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_results_file(path: Path) -> list[dict[str, Any]]:
        """Load a JSON array file, returning empty list on error."""
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        """Write data to a JSON file."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.error("Failed to write %s: %s", path, e)
