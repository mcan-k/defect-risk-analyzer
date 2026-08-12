"""Services — orchestration between `core/` and `adapters/`.

The single entry point for `ui/`, `server/` and `ci/`. Per docs/ROADMAP-v2.md,
dependencies flow one way: nothing here imports streamlit or fastapi.

Kept free of submodule imports so that importing the package stays cheap and
side-effect free.
"""
