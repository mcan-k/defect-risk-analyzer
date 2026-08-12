"""Pure domain logic — takes dicts, returns dicts, performs no I/O.

Per the architecture rule in docs/ROADMAP-v2.md, nothing under `core/` may
import streamlit, fastapi, chromadb or requests. Dependencies flow one way:
`ui/`, `server/`, `ci/` → `services/` → `core/` + `adapters/`.

Kept free of submodule imports so that importing the package stays cheap and
side-effect free.
"""
