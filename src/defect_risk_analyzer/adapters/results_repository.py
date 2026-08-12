"""
JSON persistence for analysis results and the defect density map.

All reads and writes of `data/*.json` go through here so the analysis service
never touches the filesystem directly.

Corrupted files are quarantined rather than ignored: a JSON file that fails to
parse is renamed to `<name>.corrupt-<timestamp>` before an empty result is
returned. Silently returning `[]` would let the next write replace a damaged —
but possibly recoverable — history with a single record.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from defect_risk_analyzer import config

logger = logging.getLogger(__name__)


class ResultsRepository:
    """Reads and writes the JSON files under `data/`."""

    def __init__(
        self,
        results_file: Path | None = None,
        webhook_results_file: Path | None = None,
        defect_density_file: Path | None = None,
    ) -> None:
        self._results_file = results_file or config.ANALYSIS_RESULTS_FILE
        self._webhook_results_file = webhook_results_file or config.WEBHOOK_RESULTS_FILE
        self._defect_density_file = defect_density_file or config.DEFECT_DENSITY_FILE

    # ------------------------------------------------------------------
    # Analysis results
    # ------------------------------------------------------------------

    def load_results(self) -> list[dict[str, Any]]:
        """Load all analysis results."""
        return self._read_json_list(self._results_file)

    def upsert_result(self, result: dict[str, Any]) -> bool:
        """Insert or replace an analysis result, keyed by bug_key."""
        results = self.load_results()

        bug_key = result.get("bug_key")
        if bug_key:
            results = [r for r in results if r.get("bug_key") != bug_key]

        results.append(result)
        return self._write_json(self._results_file, results)

    # ------------------------------------------------------------------
    # Webhook results
    # ------------------------------------------------------------------

    def load_webhook_results(self) -> list[dict[str, Any]]:
        """Load webhook-triggered analysis results."""
        return self._read_json_list(self._webhook_results_file)

    def append_webhook_result(self, result: dict[str, Any]) -> bool:
        """Append a webhook analysis result to the history."""
        results = self.load_webhook_results()
        results.append(result)
        return self._write_json(self._webhook_results_file, results)

    # ------------------------------------------------------------------
    # Defect density
    # ------------------------------------------------------------------

    def load_defect_density(self) -> dict[str, Any]:
        """Load the defect density map."""
        data = self._read_json(self._defect_density_file)
        return data if isinstance(data, dict) else {}

    def save_defect_density(self, density: dict[str, Any]) -> bool:
        """Persist the defect density map."""
        return self._write_json(self._defect_density_file, density)

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    def _read_json_list(self, path: Path) -> list[dict[str, Any]]:
        """Read a JSON array file, returning an empty list when unusable."""
        data = self._read_json(path)
        return data if isinstance(data, list) else []

    def _read_json(self, path: Path) -> Any:
        """Read a JSON file, quarantining it if the contents are corrupt."""
        if not path.exists():
            return None
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.error("Corrupt JSON in %s: %s", path, e)
            self._quarantine(path)
            return None
        except OSError as e:
            logger.error("Could not read %s: %s", path, e)
            return None

    @staticmethod
    def _quarantine(path: Path) -> None:
        """Move an unparseable file aside so it is not silently overwritten."""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = path.with_name(f"{path.name}.corrupt-{stamp}")
        try:
            path.rename(target)
            logger.error("Moved corrupt file to %s — inspect it before discarding.", target)
        except OSError as e:
            logger.error("Could not quarantine %s: %s", path, e)

    @staticmethod
    def _write_json(path: Path, data: Any) -> bool:
        """Write data to a JSON file. Returns False if the write failed."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except OSError as e:
            logger.error("Failed to write %s: %s", path, e)
            return False
