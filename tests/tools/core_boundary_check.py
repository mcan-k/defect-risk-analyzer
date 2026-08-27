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

import ast
import sys
from pathlib import Path

import defect_risk_analyzer

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
    # Must stay importable with `keyring` absent — it is in the `desktop` extra,
    # not requirements.txt, and CI installs neither. The import lives inside
    # resolve_store() for that reason; listing the module here is what proves
    # the module scope stayed clean.
    "defect_risk_analyzer.adapters.secrets",
    "defect_risk_analyzer.services.analysis_service",
    "defect_risk_analyzer.jira_client",
    "defect_risk_analyzer.llm_provider",
    "defect_risk_analyzer.anonymizer",
    "defect_risk_analyzer.component_classifier",
    "defect_risk_analyzer.pattern_detector",
    "defect_risk_analyzer.blind_spot_detector",
    "defect_risk_analyzer.prompt_templates",
    "defect_risk_analyzer.ui.shell",
    "defect_risk_analyzer.ui.service",
    "defect_risk_analyzer.ui.theme",
    "defect_risk_analyzer.ui.results",
    "defect_risk_analyzer.ui.setup_wizard",
    "defect_risk_analyzer.ui.messages",
]

# The page scripts cannot be imported: they are Streamlit scripts, so importing
# one executes bootstrap(), and st.page_link validates its target against the
# pages manager, which does not exist outside a script run. It raises
# StreamlitPageNotFoundError before any boundary question is reached.
#
# They still have to be checked — this used to be one import of dashboard.py,
# and dropping it would leave the UI entry point unguarded, so a page script
# that grew `from defect_risk_analyzer.api import ...` would go unnoticed.
# Their imports are read statically and imported by name instead, which
# exercises the same blocker without running any Streamlit code.
PAGE_SCRIPTS = [
    "ui/app.py",
    "ui/pages/buglar.py",
    "ui/pages/analiz.py",
    "ui/pages/ayarlar.py",
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


def page_script_imports() -> list[tuple[str, str]]:
    """(script, module) for every top-level import in the page scripts.

    Read with ast rather than executed, for the reason given beside
    PAGE_SCRIPTS. Relative imports are skipped: the blocker matches on absolute
    names, and the page scripts use none.
    """
    package_root = Path(defect_risk_analyzer.__file__).resolve().parent

    found = []
    for script in PAGE_SCRIPTS:
        tree = ast.parse((package_root / script).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found += [(script, alias.name) for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                found.append((script, node.module))
    return found


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

    for script, name in page_script_imports():
        try:
            __import__(name)
            print(f"  OK    {script} -> {name}")
        except ImportError as e:
            reason = e if "BOUNDARY VIOLATION" in str(e) else f"unexpected ImportError: {e}"
            print(f"  FAIL  {script} -> {name}\n        {reason}")
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
