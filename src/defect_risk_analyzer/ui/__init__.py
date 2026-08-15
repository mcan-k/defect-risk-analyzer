"""Presentation layer — everything the user actually reads is produced here.

Architectural rule 3 (docs/ROADMAP-v2.md:16-18): business logic returns
structural data, and user-facing text is built in this package. Phase 5C
replaces the literal templates in messages.py with locales/{tr,en}.json.

Only messages.py lives here so far. dashboard.py is still at the package root
and imports into this package from outside it, which is backwards; Phase 5B
moves it to ui/app.py and adds ui/pages/, and the asymmetry goes away.
"""
