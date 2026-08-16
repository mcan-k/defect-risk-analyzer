"""Turkish sentences for the structural findings blind_spot_detector returns.

The detector used to build these sentences itself, inside the loops that
decided which bugs and modules qualified. That put user-facing Turkish in
business logic, which architectural rule 3 forbids, and it blocked Phase 5C:
there is no way to translate a string that was already interpolated three
layers down.

So the detector now emits {"code": ..., "params": {...}} and the wording lives
here. The templates below are the previous sentences character for character —
tests/test_ui_messages.py holds the same expected strings that
tests/test_blind_spots.py asserted before the conversion, which is what makes
"the text moved" checkable rather than claimed.

`params` is self-contained: every value a template needs is in it, so this
module never reads the rest of the finding. That keeps the two shapes free to
change independently, and it is what lets Phase 5C swap this dict for a locale
file without touching the detector.
"""

from typing import Any


class UnknownFindingCode(KeyError):
    """Raised for a finding code with no template.

    Loud on purpose. The tempting alternative — return "" and move on — is
    exactly how a missing locale key disappears in Phase 5C: the page renders,
    the sentence is simply absent, and nobody notices. Raising turns that into
    a failure the dashboard walk in tests/test_dashboard_pages.py catches,
    because AppTest collects exceptions.

    The code set is closed and produced by our own detector, so an unknown one
    is a programming error rather than bad input. Phase 5C should revisit this
    when templates start coming from disk at runtime: a missing translation
    then deserves a fallback to the default locale, not a crash.
    """


TEMPLATES: dict[str, str] = {
    "unanalyzed_risky_module": (
        "{module} modülü {risk_level} risk seviyesinde ancak henüz analiz "
        "edilmemiş. Canlı Analiz sayfasından analiz yapın."
    ),
    "neglected_critical_bug": (
        "{key} — {priority} öncelikli bug {days_open} gündür '{status}' "
        "durumunda. Acil müdahale gerekiyor."
    ),
    "stale_bug": (
        "{key} — {days_open} gündür açık. Çözüm süresi beklentinin üzerinde."
    ),
    "rising_unattended_module": (
        "{module} modülünde bug sayısı artıyor ({recent_bugs} yeni bug) ancak "
        "üzerinde çalışılan bug yok. Bu modüle kaynak ayrılması önerilir."
    ),
}


def format_finding(finding: dict[str, Any]) -> str:
    """Render one structural finding as a sentence.

    Args:
        finding: An item from any detect_blind_spots category, carrying at
            least "code" and "params".

    Returns:
        The rendered Turkish sentence.

    Raises:
        UnknownFindingCode: the code has no template.
        KeyError: params is missing a name the template interpolates. Left
            unhandled deliberately — same reasoning as UnknownFindingCode.
    """
    code = finding.get("code")
    try:
        template = TEMPLATES[code]
    except KeyError:
        raise UnknownFindingCode(code) from None

    return template.format(**finding.get("params", {}))
