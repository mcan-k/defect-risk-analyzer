"""Console entry point for the Defect Risk Analyzer.

For now `dra` only launches the Streamlit dashboard. The API server is still
started separately (BASLAT.bat, docker-compose, or `uvicorn
defect_risk_analyzer.api:app`); wiring it into subcommands is future work.
"""

import subprocess
import sys
from pathlib import Path

from defect_risk_analyzer import config


def main() -> int:
    """Launch the Streamlit dashboard and return its exit code."""
    # Needed for STREAMLIT_PORT; the dashboard process runs init() again itself.
    config.init()

    dashboard = Path(__file__).resolve().parent / "dashboard.py"

    return subprocess.call(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(dashboard),
            "--server.port",
            str(config.STREAMLIT_PORT),
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
