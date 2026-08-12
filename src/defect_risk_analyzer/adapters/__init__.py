"""Adapters — everything that touches the outside world.

Network, disk and the vector database live here. Per docs/ROADMAP-v2.md,
`services/` depends on this package and on `core/`; nothing here depends on
`ui/` or `server/`.

Kept free of submodule imports so that importing the package stays cheap and
side-effect free.
"""
