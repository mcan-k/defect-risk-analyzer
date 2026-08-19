"""Presentation layer — everything the user actually reads is produced here.

Architectural rule 3 (docs/ROADMAP-v2.md:16-18): business logic returns
structural data, and user-facing text is built in this package. Phase 5C
replaces the literal templates in messages.py with locales/{tr,en}.json.

Phase 5B moved the dashboard in, so the whole presentation layer is now under
one roof:

  app.py         the entry script, and the Genel Bakış page
  pages/         the other three pages, discovered by Streamlit's MPA-v1 glob
  shell.py       bootstrap(): page config, styling, first-run gate, navigation
  service.py     the shared AnalysisService handle and the error boundary
  theme.py       colours, chart styling, the stylesheet
  results.py     one analysis result, rendered
  setup_wizard.py  the first-run flow — a flow, not a page
  messages.py    finding sentences; Phase 5C swaps these for locales/{tr,en}.json

Nothing outside this package imports from it except cli.py, which only needs
the path of app.py to hand to `streamlit run`.
"""
