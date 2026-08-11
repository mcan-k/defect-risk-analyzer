"""Predictive Defect Analysis Engine — AI-powered Jira defect risk prediction.

Kept deliberately free of submodule imports: `config` runs `reload()` and
creates the data directory at import time, so importing it from here would
make `import defect_risk_analyzer` side-effectful. It would also break the
`[tool.setuptools.dynamic] version = {attr = ...}` lookup in pyproject.toml,
which reads this module without installing the dependencies first.
"""

__version__ = "1.0.0"
