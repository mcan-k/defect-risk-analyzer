"""Sentences for the structural findings blind_spot_detector returns.

The detector used to build these sentences itself, inside the loops that
decided which bugs and modules qualified. That put user-facing Turkish in
business logic, which architectural rule 3 forbids, and it blocked Phase 5C:
there is no way to translate a string that was already interpolated three
layers down.

Phase 5A made the detector emit {"code": ..., "params": {...}} and moved the
wording here as a literal dict. Phase 5C moved the wording one step further,
out of Python and into locales/{tr,en}.json under the `finding.` prefix, so
this module is now an adapter: it maps a finding's code onto a message key and
hands the params straight to i18n.

The wording did not change in either move. tests/test_ui_messages.py still
holds the four expected strings that tests/test_blind_spots.py asserted before
5A, and tests/test_i18n_locales.py asserts the tr locale carries those same
four strings character for character. That is what keeps "the text moved" a
checkable claim across two migrations rather than an asserted one.

The one exception is declared rather than silent: the unanalyzed-module
sentence named the "Canlı Analiz" page, which Faz 5B merged away, so 5C fixed
the page name in a commit of its own before any migration. See the note in
tests/test_ui_messages.py.

`params` is self-contained: every value a template needs is in it, so this
module never reads the rest of the finding. That is what let 5C swap the dict
for a locale file without the detector knowing.
"""

from typing import Any

from defect_risk_analyzer.ui import i18n

#: Message-key prefix for the codes blind_spot_detector emits. Pattern findings
#: live under `pattern.` instead of sharing this namespace, deliberately: this
#: prefix defines TEMPLATES below, and tests/test_ui_messages.py asserts
#: TEMPLATES equals exactly the set of codes the *blind spot* detector emits.
FINDING_PREFIX = "finding."

#: Pattern findings live OUTSIDE the `finding.` namespace on purpose. TEMPLATES
#: below is derived from that prefix, and tests/test_ui_messages.py asserts it
#: equals exactly the set of codes the BLIND SPOT detector emits. Sharing the
#: namespace would widen that assertion silently — an equality test that has to
#: be relaxed is worth less than the separation.
#:
#: The keys themselves are written as literals at the call site rather than
#: through constants: tests/test_i18n_locales.py collects t() keys by reading
#: the source, and a name it cannot resolve counts as a dynamic call that
#: excuses a whole namespace from the "is this message used?" check. The
#: indirection reads slightly better and is worth less than the guard.
PATTERN_CODE = "pattern_theme"


class UnknownFindingCode(i18n.UnknownMessageKey):
    """Raised for a finding code with no template.

    Loud on purpose. The tempting alternative — return "" and move on — is
    exactly how a missing locale key disappears: the page renders, the sentence
    is simply absent, and nobody notices. Raising turns that into a failure the
    dashboard walk in tests/test_dashboard_pages.py catches, because AppTest
    collects exceptions.

    Phase 5A left one question open here: whether a template read from disk at
    runtime deserves a fallback rather than a crash. i18n.UnknownMessageKey
    answers it, and this class is now a subclass of that answer — a code
    missing from the *active* locale but present in the source one renders in
    the source language with a logged warning, while a code missing from every
    locale still raises, because the code set is closed and produced by our own
    detector.
    """


def _templates() -> dict[str, str]:
    """The source-language finding templates, keyed by code rather than by key.

    Read from SOURCE_LANGUAGE, not the active one: the caller of this name is a
    test asserting which codes have wording at all, which is a property of the
    catalog rather than of whatever language a session happens to be in.
    """
    source = i18n.catalog(i18n.SOURCE_LANGUAGE)
    return {
        key[len(FINDING_PREFIX):]: value
        for key, value in source.items()
        if key.startswith(FINDING_PREFIX)
    }


#: Finding code → source-language sentence. Kept as a module-level name because
#: tests/test_ui_messages.py has read it since 5A and the value of that file is
#: that it did not have to change.
TEMPLATES: dict[str, str] = _templates()


def format_finding(finding: dict[str, Any]) -> str:
    """Render one structural finding as a sentence.

    Args:
        finding: An item from any detect_blind_spots category, carrying at
            least "code" and "params".

    Returns:
        The rendered sentence, in the active language.

    Raises:
        UnknownFindingCode: the code has no template in any locale.
        KeyError: params is missing a name the template interpolates. Left
            unhandled deliberately — same reasoning as UnknownFindingCode.
    """
    code = finding.get("code")
    try:
        return i18n.t(f"{FINDING_PREFIX}{code}", **finding.get("params", {}))
    except i18n.UnknownMessageKey:
        raise UnknownFindingCode(code) from None


def format_pattern_summary(pattern: dict[str, Any]) -> str:
    """Render one pattern's theme as a sentence.

    pattern_detector used to build this string itself. It now emits
    {"code": "pattern_theme", "params": {"bug_count": …, "keywords": [...]}},
    and the two wordings — the sentence and the "nothing in common" stand-in —
    live in the locale files.

    The keyword list is joined HERE rather than in the detector. Deciding that
    five keywords read as "a, b, c" and an empty list reads as a phrase is a
    presentation decision, and leaving it in the detector is what put a Turkish
    sentence in business logic in the first place.

    Args:
        pattern: One item from detect_patterns.

    Returns:
        The rendered sentence, in the active language.

    Raises:
        UnknownFindingCode: the pattern carries a code this does not know.
    """
    code = pattern.get("code")
    if code != PATTERN_CODE:
        raise UnknownFindingCode(code)

    params = dict(pattern.get("params", {}))
    keywords = params.pop("keywords", None) or []
    params["keywords"] = (
        ", ".join(keywords) if keywords else i18n.t("pattern.theme.no_keywords")
    )

    return i18n.t("pattern.theme", **params)


#: Message-key prefix for the layer codes `adapters/secrets.py` emits. A second
#: producer in this module, and the reason it is here rather than in a file of
#: its own: this is the only module under `ui/` whose job is turning a
#: NON-UI producer's {code, params} into a sentence. `app.py`, `buglar.py` and
#: `theme.py` each map a value they computed themselves, next to where they
#: computed it. Two surfaces need this one — the Settings page and the startup
#: banner — so it needs a shared home, and a new file for a single function
#: would scatter the pattern rather than collect it.
#:
#: It also has to be ONE call site. tests/test_i18n_locales.py asserts exactly
#: one dynamic t() per declared prefix, so a second computed call under
#: `secret_layer.` would fail that guard.
SECRET_LAYER_PREFIX = "secret_layer."


def format_secret_layer(code: str, params: dict[str, Any] | None = None) -> str:
    """Render which credential layer is in use, in the active language.

    THE FOURTH TIME THIS LESSON HAS BEEN APPLIED. 5A moved blind-spot wording
    out of the detector because a sentence built in business logic cannot be
    translated; 5C moved pattern wording after it; Faz 6B then built English
    sentences inside `adapters/secrets.py` and shipped them into a Turkish
    page. The adapter now emits a code and this renders it.

    `params` carries `backend` (an identifier — never translated) or `error`
    (an exception TYPE name, never a message: these params reach the screen,
    and a backend that quoted a credential back would put it in front of the
    user).

    Raises:
        i18n.UnknownMessageKey: a code with no template in any locale. Loud for
            the same reason UnknownFindingCode is.
    """
    return i18n.t(f"{SECRET_LAYER_PREFIX}{code}", **(params or {}))
