"""X-API-Key authentication: what it accepts, what it refuses, and how it compares.

WRITTEN BEFORE THE FIX (Faz 6B, D9). The behavioural tests below are GREEN on
today's code — `!=` accepts and refuses exactly the same keys `compare_digest`
does. That is the whole difficulty: the defect this step fixes is invisible to
behaviour, because the two agree on every input and differ only in how long they
take to disagree.

SO THE RULE LIVES IN A SOURCE GUARD, and the behavioural tests are there to stop
the fix from breaking the thing that does work. This is the same split as
`test_no_ui_module_writes_to_the_process_environment`: when a behavioural test
cannot carry the claim, a source-level one carries it and says why.

NOT A TIMING TEST. Measuring the difference would mean timing two comparisons
and asserting one is not reliably faster — noisy on a developer machine, worse
on a shared CI runner, and a test that fails on an unlucky Tuesday teaches
people to re-run the suite rather than read it.
"""

import ast
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from defect_risk_analyzer import api_auth, config

VALID_KEY = "synthetic-api-key-0000"


@pytest.fixture
def client(monkeypatch):
    """A minimal app carrying the real dependency."""
    app = FastAPI()

    @app.get("/guarded", dependencies=[Depends(api_auth.require_api_key)])
    async def guarded():
        return {"ok": True}

    def _with_key(key: str):
        monkeypatch.setattr(config, "API_KEY", key)
        return TestClient(app, raise_server_exceptions=False)

    return _with_key


# ---------------------------------------------------------------------------
# Behaviour — green before and after, and that is the point
# ---------------------------------------------------------------------------

def test_the_configured_key_is_accepted(client):
    response = client(VALID_KEY).get("/guarded", headers={"X-API-Key": VALID_KEY})

    assert response.status_code == 200


def test_a_wrong_key_is_refused(client):
    response = client(VALID_KEY).get("/guarded", headers={"X-API-Key": "wrong-key"})

    assert response.status_code == 403


def test_a_key_that_is_a_prefix_of_the_real_one_is_refused(client):
    """The shape a timing attack walks toward, refused on content alone."""
    response = client(VALID_KEY).get("/guarded", headers={"X-API-Key": VALID_KEY[:-1]})

    assert response.status_code == 403


def test_a_missing_header_is_unauthorized(client):
    response = client(VALID_KEY).get("/guarded")

    assert response.status_code == 401


def test_a_server_with_no_key_refuses_everything(client):
    """503, not 401. A server without a key is misconfigured, not unauthenticated.

    And an empty `config.API_KEY` compared against an empty header would
    otherwise MATCH, which is authentication bypass rather than a missing
    credential — this is checked before anything else for that reason.
    """
    unconfigured = client("")

    assert unconfigured.get("/guarded", headers={"X-API-Key": ""}).status_code == 503
    assert unconfigured.get("/guarded", headers={"X-API-Key": "anything"}).status_code == 503
    assert unconfigured.get("/guarded").status_code == 503


# ---------------------------------------------------------------------------
# The source guard — this is where the D9 rule actually lives
# ---------------------------------------------------------------------------

def _auth_tree() -> ast.AST:
    return ast.parse(Path(api_auth.__file__).read_text(encoding="utf-8"))


def test_the_key_comparison_is_constant_time():
    """`secrets.compare_digest` is called, and it is called on the two keys.

    Asserting the call exists is not enough on its own — it could sit next to an
    unchanged `!=` and satisfy a naive check — so the operands are checked too.
    """
    calls = [
        node
        for node in ast.walk(_auth_tree())
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Attribute) and node.func.attr == "compare_digest")
            or (isinstance(node.func, ast.Name) and node.func.id == "compare_digest")
        )
    ]

    assert calls, "api_auth does not call secrets.compare_digest"

    operands = {
        arg.id for call in calls for arg in call.args if isinstance(arg, ast.Name)
    }
    assert {"api_key", "expected_key"} <= operands, (
        f"compare_digest is called, but not on the two keys: {sorted(operands)}"
    )


def test_the_keys_are_never_compared_with_an_operator():
    """No `==` or `!=` between the supplied key and the configured one.

    The mutation this exists for is the smallest possible edit — swapping the
    call back for the operator — and every behavioural test above stays green
    through it.
    """
    key_names = {"api_key", "expected_key"}

    offenders = []
    for node in ast.walk(_auth_tree()):
        if not isinstance(node, ast.Compare):
            continue
        if not any(isinstance(op, ast.Eq | ast.NotEq) for op in node.ops):
            continue
        names = {
            operand.id
            for operand in [node.left, *node.comparators]
            if isinstance(operand, ast.Name)
        }
        if names & key_names:
            offenders.append(f"line {node.lineno}: {sorted(names)}")

    assert not offenders, (
        f"the API key is compared with an operator rather than compare_digest: {offenders}"
    )


# ---------------------------------------------------------------------------
# The stdlib `secrets` module, next to a package module of the same name
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "module_name",
    ["defect_risk_analyzer.api_auth", "defect_risk_analyzer.config"],
)
def test_import_secrets_resolves_to_the_standard_library(module_name):
    """`adapters/secrets.py` must not shadow the stdlib module of that name.

    Python 3 uses absolute imports, so a bare `import secrets` inside the
    package reaches the standard library and only an explicit relative import
    (`from . import secrets`) would reach the local one. Both modules here need
    the stdlib: `api_auth` for `compare_digest` and `config` for `token_urlsafe`.

    Measured rather than reasoned about, because the failure would be silent in
    the worst possible place — `config.ensure_api_key()` would raise
    AttributeError on `token_urlsafe` at the moment it tried to generate a key.
    """
    import importlib
    import secrets as stdlib_secrets

    module = importlib.import_module(module_name)

    assert module.secrets is stdlib_secrets, (
        f"{module_name}.secrets is {module.secrets!r}, not the standard library"
    )
    assert hasattr(module.secrets, "compare_digest")
    assert hasattr(module.secrets, "token_urlsafe")
