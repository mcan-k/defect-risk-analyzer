"""
Prove the core code path never imports the webhook dependencies.

Installing without requirements-webhook.txt does NOT produce a fastapi-free
environment: chromadb itself requires fastapi, uvicorn, httpx and pydantic, so
they are present no matter what. The separation that can actually be verified
is the one that matters — that no module the dashboard or the CI analyzer
loads reaches for them.

This blocks the imports at the loader level and then imports the core path.
Anything that touches fastapi raises ImportError with a clear message.

Run by tests/test_core_boundary.py in a SUBPROCESS, which is load-bearing:
`__import__` returns straight from sys.modules for anything already imported,
so running this in the pytest process — where sibling tests have already
imported defect_risk_analyzer.* and chromadb may have pulled in fastapi —
would never consult the blocker and every check would pass vacuously.

Deliberately not named test_*.py so pytest does not collect it directly.

Usage: python tests/tools/core_boundary_check.py
"""

import sys

BLOCKED = {
    "fastapi",
    "uvicorn",
    "defect_risk_analyzer.api",
    "defect_risk_analyzer.api_auth",
    "defect_risk_analyzer.api_models",
}

CORE_MODULES = [
    "defect_risk_analyzer.config",
    "defect_risk_analyzer.cli",
    "defect_risk_analyzer.ci_analyzer",
    "defect_risk_analyzer.core.scoring",
    "defect_risk_analyzer.adapters.vector_store",
    "defect_risk_analyzer.adapters.results_repository",
    "defect_risk_analyzer.services.analysis_service",
    "defect_risk_analyzer.jira_client",
    "defect_risk_analyzer.llm_provider",
    "defect_risk_analyzer.anonymizer",
    "defect_risk_analyzer.component_classifier",
    "defect_risk_analyzer.pattern_detector",
    "defect_risk_analyzer.blind_spot_detector",
    "defect_risk_analyzer.prompt_templates",
    "defect_risk_analyzer.dashboard",
]


class _Blocker:
    """Meta path finder that refuses the webhook-only modules."""

    def find_module(self, fullname, path=None):
        return self.find_spec(fullname, path)

    def find_spec(self, fullname, path=None, target=None):
        root = fullname.split(".")[0]
        if fullname in BLOCKED or root in BLOCKED:
            raise ImportError(
                f"BOUNDARY VIOLATION: core path imported '{fullname}', "
                "which belongs to the optional webhook extra"
            )
        return None


def main() -> int:
    sys.meta_path.insert(0, _Blocker())

    failures = 0
    for name in CORE_MODULES:
        try:
            __import__(name)
            print(f"  OK    {name}")
        except ImportError as e:
            if "BOUNDARY VIOLATION" in str(e):
                print(f"  FAIL  {name}\n        {e}")
                failures += 1
            else:
                print(f"  FAIL  {name}\n        unexpected ImportError: {e}")
                failures += 1

    # Sanity check: the blocker really does bite.
    try:
        __import__("fastapi")
        print("  FAIL  blocker inert — fastapi imported despite the block")
        failures += 1
    except ImportError:
        print("  OK    blocker aktif (fastapi engellendi)")

    print("CORE BOUNDARY CLEAN" if not failures else f"{failures} VIOLATION(S)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
