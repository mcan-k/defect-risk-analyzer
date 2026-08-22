"""Runtime translation for the presentation layer.

Architectural rule 3 says user-facing text is produced in `ui/`. Phase 5A moved
the blind spot sentences here; 5C moves the wording itself out of Python and
into `locales/{tr,en}.json`, so the same code renders either language.

**This module deliberately does not import streamlit.** The active language is
a module global set by `shell.bootstrap()` once per script run, not a read of
`st.session_state` inside every `t()` call. Two reasons:

  * `tests/test_i18n_locales.py` can import this module plainly and check the
    locale contract — key sets, missing keys, the fallback — without paying for
    an `AppTest` run or a script context.
  * `t()` is called a few hundred times per rerun; a session_state read per
    call would be both slower and impossible to exercise outside Streamlit.

The cost is recorded in docs/KNOWN-DEBT.md: Streamlit runs concurrent browser
sessions as threads in one process, so two sessions choosing different
languages race on this global. Acceptable for a local single-user desktop tool,
and the note says what would have to change if that stops being true.

Keys are flat and dotted (`"overview.metric.total_bugs"`), not nested. A flat
file keeps the loader small, makes existence a plain `in`, and lets the AST
test that collects every literal `t("...")` compare key sets directly instead
of flattening first. Grouping survives in the prefix and in sort order.
"""

import json
import logging
from functools import cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

LOCALES_DIR = Path(__file__).resolve().parent / "locales"

#: The language the product is authored in. Every key exists here; anything
#: missing from another locale falls back to this one.
SOURCE_LANGUAGE = "tr"

#: Shipped locales, in the order the selector offers them. Names are endonyms —
#: a language picker that writes its options in the *current* language is the
#: one thing a lost user cannot read, so these are never translated.
LANGUAGES: dict[str, str] = {
    "tr": "Türkçe",
    "en": "English",
}

_active: str = SOURCE_LANGUAGE


class UnknownMessageKey(KeyError):
    """Raised for a key that no locale defines.

    Loud on purpose, and this is the answer to the question ui/messages.py left
    open in Phase 5A: now that templates come from disk, does a missing one
    still deserve a crash?

    The distinction 5A could not make is between two different failures:

      * A key missing from ONE locale is a translation gap. The page should
        still render, in the source language, with a warning in the log — see
        `translate()`. A user editing their own locale file must not be able to
        break the app.
      * A key missing from EVERY locale is a programming error, exactly like
        5A's unknown finding code: the key set is closed and produced by our own
        source. It raises, and `AppTest` collects the exception, so
        tests/test_dashboard_pages.py fails rather than a caption silently
        rendering empty.

    The first case is unreachable in a shipped build —
    `test_locale_key_sets_match` requires the two files to agree — so the
    fallback is a safety net, not an excuse. That distinction is itself a test.
    """


@cache
def catalog(language: str) -> dict[str, str]:
    """Return the message catalog for `language`, read once per process.

    Raises:
        FileNotFoundError: no locale file. For SOURCE_LANGUAGE this means the
            package was built without its locale data — see the wheel note in
            docs/KNOWN-DEBT.md — and it is fatal rather than papered over.
        ValueError: the file is not a flat object of string values.
    """
    path = LOCALES_DIR / f"{language}.json"
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict):
        raise ValueError(f"{path} must hold a JSON object, got {type(data).__name__}.")
    bad = sorted(key for key, value in data.items() if not isinstance(value, str))
    if bad:
        raise ValueError(f"{path} has non-string values for: {', '.join(bad)}")

    return data


def set_language(language: str) -> str:
    """Make `language` active for this process. Returns what was actually set."""
    global _active

    if language not in LANGUAGES:
        logger.warning("Unknown language %r; staying on %s.", language, SOURCE_LANGUAGE)
        language = SOURCE_LANGUAGE

    _active = language
    return _active


def get_language() -> str:
    """The language `t()` currently renders in."""
    return _active


def translate(key: str, language: str, /, **params: Any) -> str:
    """Render one message in an explicit language.

    Positional-only on purpose: `params` carries whatever a template
    interpolates, and several of them are named `key`.

    Raises:
        UnknownMessageKey: no locale defines this key.
        KeyError: the template interpolates a name `params` does not carry.
            Left unhandled, same reasoning as UnknownMessageKey — a half-written
            sentence is the silent failure, not the loud one.
    """
    try:
        template = catalog(language)[key]
    except KeyError:
        template = _from_source(key, language)

    # No formatting when nothing is interpolated: a literal brace in a message
    # would otherwise have to be escaped for no reason the translator can see.
    return template.format(**params) if params else template


def t(key: str, /, **params: Any) -> str:
    """Render one message in the active language."""
    return translate(key, _active, **params)


def _from_source(key: str, language: str) -> str:
    """The source-language template for `key`, or raise."""
    if language != SOURCE_LANGUAGE:
        source = catalog(SOURCE_LANGUAGE)
        if key in source:
            logger.warning(
                "No %s translation for %r; falling back to %s.", language, key, SOURCE_LANGUAGE
            )
            return source[key]

    raise UnknownMessageKey(key) from None
