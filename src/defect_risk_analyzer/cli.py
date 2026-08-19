"""Console entry point for the Defect Risk Analyzer.

`dra` launches the Streamlit dashboard, which is the whole application: the
analysis engine runs inside that process and needs no server.

The FastAPI service is optional and only needed for the Jira webhook and
external integrations. It ships as a separate extra and is started on its own:

    pip install -e ".[webhook]"
    uvicorn defect_risk_analyzer.api:app --port 8000
"""

import subprocess
import sys
from pathlib import Path

from defect_risk_analyzer import config


def main() -> int:
    """Launch the Streamlit dashboard and return its exit code."""
    # Needed for STREAMLIT_PORT; the dashboard process runs init() again itself.
    config.init()

    dashboard = Path(__file__).resolve().parent / "ui" / "app.py"

    return subprocess.call(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(dashboard),
            "--server.port",
            str(config.STREAMLIT_PORT),
            # Streamlit looks for .streamlit/config.toml under the process
            # working directory, not next to the script. `dra` is installable
            # with pipx and runs from wherever the user happens to be, so the
            # repo's config.toml is usually not found — and a missed config
            # file is silent. Without this flag the built-in pages/ navigation
            # appears above the one render_nav() draws, and the user gets two.
            "--client.showSidebarNavigation=false",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
