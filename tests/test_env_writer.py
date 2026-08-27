"""
What `config.set_env_value()` does to the `.env` file it writes.

WRITTEN BEFORE THE FIX (Faz 6A, Adım 1). Several tests here are expected to be
RED on today's implementation; that is the point. The expected colour of every
test is recorded in its docstring, and a test that comes up the wrong colour is
a finding to report, not something to adjust the assertion for.

The rule under test throughout: the value the writer puts in the file must be
the value `python-dotenv` hands back on the next `reload()`. Today it is not.
`set_env_value` updates the FIRST matching line and stops; `load_dotenv` builds
a dict in file order, so the LAST occurrence wins. On a file with a duplicated
key the two halves aim at different lines and the save silently reverts.

SEPARATION OF CONCERNS. Three properties are easy to conflate, so each has its
own test and every other test is written to be blind to the other two:

  * line endings      -> T7 only. Everything else compares line CONTENT
                         (`splitlines()`), never the terminator bytes.
  * text encoding     -> TE1/TE2 only.
  * duplicate handling-> T1/T2/T13c.

Without that split a single test goes red for a reason it does not name. On
Windows today's writer turns an LF file into a CRLF one, which would make a
naive byte-for-byte "nothing else changed" assertion fail for a line-ending
reason while claiming to be about duplicates or encoding.
"""

import ast
import builtins
import os
import stat
from pathlib import Path

import pytest

from defect_risk_analyzer import config

# The marker the deduplicating writer is required to leave on a line it retires.
# Written out literally rather than imported from config: importing it would
# make the assertion circular — it would pass whatever the marker became.
MARKER = "[duplicate removed by set_env_value]"

# Every key any test below writes or reads. Registered with monkeypatch.setenv
# in the fixture so that load_dotenv(override=True), which writes into
# os.environ, cannot leak out of this module.
TOUCHED_KEYS = (
    "API_KEY",
    "USE_MOCK_DATA",
    "USE_MOCK_DATA_EXTRA",
    "DRA_LANGUAGE",
    "JIRA_URL",
    "GROQ_API_KEY",
    "OTHER_KEY",
    "QUOTED_KEY",
    "EQUALS_KEY",
)

# config globals the tests can move via reload(). Restored at teardown for the
# same reason: config module state is process-global and never reset.
TOUCHED_GLOBALS = ("API_KEY", "USE_MOCK_DATA", "LANGUAGE", "JIRA_URL", "GROQ_API_KEY")


@pytest.fixture
def env_file(monkeypatch, tmp_path):
    """Point config.ENV_FILE at a throwaway file and restore all state after."""
    for key in TOUCHED_KEYS:
        monkeypatch.setenv(key, "__pre_test_sentinel__")
    for name in TOUCHED_GLOBALS:
        monkeypatch.setattr(config, name, getattr(config, name))

    path = tmp_path / ".env"
    monkeypatch.setattr(config, "ENV_FILE", path)
    return path


# ---------------------------------------------------------------------------
# Helpers — all content-based, none of them look at line terminators
# ---------------------------------------------------------------------------

def write_env(path: Path, text: str, *, newline: str = "\n") -> None:
    """Write fixture content with an explicit terminator, bypassing Python's
    newline translation so the fixture is exactly what the test says it is."""
    body = newline.join(text.splitlines()) + newline
    path.write_bytes(body.encode("utf-8"))


def content_lines(path: Path) -> list[str]:
    """The file's lines, terminators discarded. Decodes as UTF-8 on purpose:
    a writer that used the locale codec instead raises here (see TE1)."""
    return path.read_bytes().decode("utf-8").splitlines()


def live_lines(path: Path, key: str) -> list[str]:
    """Assignment lines dotenv would read for `key`. Comments cannot match:
    a commented line starts with '#', never with the key."""
    return [ln for ln in content_lines(path) if ln.strip().startswith(f"{key}=")]


def terminators(path: Path) -> set[bytes]:
    """The distinct line terminators present in the file."""
    raw = path.read_bytes()
    found = set()
    if b"\r\n" in raw:
        found.add(b"\r\n")
    if raw.replace(b"\r\n", b"").count(b"\n"):
        found.add(b"\n")
    return found


# ---------------------------------------------------------------------------
# T1-T2 — the defect itself
# ---------------------------------------------------------------------------

def test_t1_written_value_is_the_one_reload_returns(env_file):
    """T1 — EXPECTED RED.

    Two filled, different lines for one key. After a save, `reload()` must
    return what was just written and the file must hold exactly one live line.
    Today the write lands on line 1 while dotenv keeps reading line 2, so the
    save is silently reverted.
    """
    write_env(env_file, "API_KEY=first-value\nAPI_KEY=second-value")

    config.set_env_value("API_KEY", "third-value")
    config.reload()

    assert config.API_KEY == "third-value"
    assert live_lines(env_file, "API_KEY") == ["API_KEY=third-value"]


def test_t2_the_surviving_line_is_the_last_occurrence(env_file):
    """T2 — EXPECTED RED.

    Which line survives is not cosmetic: the survivor must be the line dotenv
    was already reading, so that a half-finished write still leaves the
    application reading the value we just wrote. The earlier occurrence is
    retired by commenting, never by deletion.
    """
    write_env(env_file, "JIRA_URL=a\nAPI_KEY=first\nGROQ_API_KEY=b\nAPI_KEY=second")

    config.set_env_value("API_KEY", "third")

    lines = content_lines(env_file)
    assert lines[3] == "API_KEY=third", "live line must keep the last occurrence's slot"
    assert lines[1].lstrip().startswith("#"), "earlier occurrence must be commented out"
    assert MARKER in lines[1]
    assert live_lines(env_file, "API_KEY") == ["API_KEY=third"]


# ---------------------------------------------------------------------------
# T3-T4 — what deduplication must NOT do
# ---------------------------------------------------------------------------

def test_t3_writing_one_key_leaves_another_keys_duplicates_alone(env_file):
    """T3 — EXPECTED GREEN.

    Deduplication is scoped to the key being written. A language toggle has no
    business rewriting credential lines: widening the scope would widen the
    data-loss surface for no gain.
    """
    write_env(env_file, "API_KEY=first\nAPI_KEY=second")

    config.set_env_value("DRA_LANGUAGE", "en")
    config.reload()

    assert config.API_KEY == "second", "untouched key must keep its effective value"
    assert live_lines(env_file, "API_KEY") == ["API_KEY=first", "API_KEY=second"]


def test_t4_rewriting_the_effective_value_changes_nothing(env_file):
    """T4 — EXPECTED GREEN.

    The Settings page pre-fills its form from config, so an ordinary save
    rewrites values that are already effective. That must be a no-op for the
    reader, whatever the writer does to the file's shape.
    """
    write_env(env_file, "API_KEY=first\nAPI_KEY=second")
    config.reload()
    before = config.API_KEY

    config.set_env_value("API_KEY", before)
    config.reload()

    assert config.API_KEY == before == "second"


# ---------------------------------------------------------------------------
# T5-T6 — comments are not write targets
# ---------------------------------------------------------------------------

def test_t5_a_commented_key_is_not_a_write_target(env_file):
    """T5 — EXPECTED RED.

    Today `set_env_value` matches `# KEY=` as well as `KEY=` and overwrites the
    comment, turning documentation into a live setting. dotenv never reads a
    comment, so treating one as the write target contradicts the effective-line
    rule the whole fix is built on.
    """
    write_env(env_file, "# API_KEY=documented-placeholder\nAPI_KEY=live-value")

    config.set_env_value("API_KEY", "new-value")

    lines = content_lines(env_file)
    assert lines[0] == "# API_KEY=documented-placeholder", "comment must survive verbatim"
    assert live_lines(env_file, "API_KEY") == ["API_KEY=new-value"]


def test_t6_repeated_writes_do_not_accumulate_markers(env_file):
    """T6 — EXPECTED RED.

    The loop this closes: if a line we retired by commenting could be selected
    again, every save would retire the previous save's comment and the file
    would grow a marker per write forever. One live line, one marker, stable.

    COUNTED PER OCCURRENCE, NOT PER LINE. The first version of this test counted
    lines containing the marker, and the mutation audit showed it did not detect
    the loop it is named after: re-retiring an already-retired line makes that
    one line accumulate markers ("# # KEY=x  # [marker]  # [marker]"), so a
    per-line count stays at 1 and the line count never grows either. Measured
    with the mutation that restores the old `# {key}=` branch — the assertions
    below go red, the earlier ones did not.
    """
    write_env(env_file, "API_KEY=first\nAPI_KEY=second")

    config.set_env_value("API_KEY", "third")
    after_first = content_lines(env_file)
    config.set_env_value("API_KEY", "fourth")
    after_second = content_lines(env_file)

    assert live_lines(env_file, "API_KEY") == ["API_KEY=fourth"]
    assert "\n".join(after_first).count(MARKER) == 1
    assert "\n".join(after_second).count(MARKER) == 1, "a retired line was retired again"
    assert len(after_second) == len(after_first), "the file must not grow per write"
    assert [ln for ln in after_second if MARKER in ln] == [
        ln for ln in after_first if MARKER in ln
    ], "the retired line must be left alone by later writes"


# ---------------------------------------------------------------------------
# T7 — line endings (the ONLY test that looks at terminator bytes)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "newline, label",
    [(b"\r\n".decode(), "crlf"), (b"\n".decode(), "lf")],
    ids=["crlf", "lf"],
)
def test_t7_line_endings_are_preserved(env_file, newline, label):
    """T7 — EXPECTED: crlf GREEN on Windows / RED on POSIX, lf RED on Windows.

    Today the file is read with universal newlines and written with the
    platform default, so the writer rewrites every terminator in the file to
    os.linesep. On Windows that silently converts an LF file to CRLF; on Linux
    it converts a CRLF file to LF. Both are a whole-file rewrite nobody asked
    for, and both are invisible until a diff or a cross-platform checkout.
    """
    write_env(env_file, "API_KEY=first\nJIRA_URL=https://example", newline=newline)
    expected = newline.encode()

    config.set_env_value("API_KEY", "second")

    assert terminators(env_file) == {expected}, f"{label}: terminators were rewritten"


# ---------------------------------------------------------------------------
# T8-T10 — file integrity around the write
# ---------------------------------------------------------------------------

def test_t8_appending_to_a_file_without_a_trailing_newline(env_file):
    """T8 — EXPECTED RED.

    `lines.append(...)` on a file whose last line has no terminator glues the
    new assignment onto the old one, producing a single corrupt line. dotenv's
    own `set_key()` guards this with a `missing_newline` check; ours does not.
    """
    env_file.write_bytes(b"JIRA_URL=https://example")

    config.set_env_value("API_KEY", "appended")

    assert content_lines(env_file) == ["JIRA_URL=https://example", "API_KEY=appended"]


def test_t9_a_longer_key_with_the_same_prefix_is_not_matched(env_file):
    """T9 — EXPECTED GREEN.

    `USE_MOCK_DATA` must not match `USE_MOCK_DATA_EXTRA`. The trailing '=' in
    the comparison is what makes that true today; this pins it so a future
    rewrite cannot drop it unnoticed.
    """
    write_env(env_file, "USE_MOCK_DATA_EXTRA=keep-me\nUSE_MOCK_DATA=False")

    config.set_env_value("USE_MOCK_DATA", "True")

    assert live_lines(env_file, "USE_MOCK_DATA_EXTRA") == ["USE_MOCK_DATA_EXTRA=keep-me"]
    assert live_lines(env_file, "USE_MOCK_DATA") == ["USE_MOCK_DATA=True"]


def test_t10_everything_but_the_target_line_is_preserved(env_file):
    """T10 — EXPECTED GREEN.

    Comments, blank lines, key order, quoted values and values containing '='
    all survive untouched, because the writer edits lines in place instead of
    parsing the file into a dict and re-emitting it.
    """
    original = (
        "# a section header\n"
        "\n"
        'QUOTED_KEY="value with spaces"\n'
        "EQUALS_KEY=a=b=c\n"
        "\n"
        "API_KEY=old\n"
        "# trailing note\n"
    )
    write_env(env_file, original)

    config.set_env_value("API_KEY", "new")

    lines = content_lines(env_file)
    assert lines[0] == "# a section header"
    assert lines[1] == ""
    assert lines[2] == 'QUOTED_KEY="value with spaces"'
    assert lines[3] == "EQUALS_KEY=a=b=c"
    assert lines[4] == ""
    assert lines[5] == "API_KEY=new"
    assert lines[6] == "# trailing note"


# ---------------------------------------------------------------------------
# T11-T12 — how the bytes reach the disk
# ---------------------------------------------------------------------------

@pytest.mark.skipif(os.name == "nt", reason="Windows does not model POSIX permission bits")
def test_t11_file_permissions_are_preserved(env_file):
    """T11 — EXPECTED SKIPPED locally, first real run in CI (ubuntu-latest).

    Measured on the Windows dev machine: a plain open(), a NamedTemporaryFile
    and a chmod'ed file all report 0o666, so the rule is unobservable there.
    On POSIX the hazard is real and runs in both directions: NamedTemporaryFile
    creates 0600 and a plain open() creates umask-default 0644, so a .env the
    user locked down to 0640 silently changes either way.
    """
    write_env(env_file, "API_KEY=old")
    os.chmod(env_file, 0o640)

    config.set_env_value("API_KEY", "new")

    assert stat.S_IMODE(env_file.stat().st_mode) == 0o640


class _WriteFailure(RuntimeError):
    """A crash in the middle of writing the file."""


class _HalfWriter:
    """A file handle that writes part of the payload and then fails."""

    def __init__(self, handle):
        self._handle = handle

    def writelines(self, lines):
        lines = list(lines)
        if lines:
            self._handle.write(lines[0])
        raise _WriteFailure("simulated crash mid-write")

    def write(self, data):
        self._handle.write(data[: max(1, len(data) // 2)])
        raise _WriteFailure("simulated crash mid-write")

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self._handle.close()
        return False

    def __getattr__(self, name):
        return getattr(self._handle, name)


def test_t12_a_failed_write_leaves_the_original_intact(env_file, monkeypatch):
    """T12 — EXPECTED RED.

    Written against the RULE, not against either implementation's shape: the
    failure is injected into whatever call writes a file in the .env directory,
    so the same test measures today's direct write and tomorrow's temp-file +
    os.replace. If the write dies halfway, the original .env must be untouched
    and no partial file may be left behind.

    Today the write goes straight into .env, so the crash truncates the user's
    configuration. (An earlier draft of this test injected the failure into
    os.replace, which today's code never calls — the injection would have been
    a no-op and the test would have passed while measuring nothing.)
    """
    original = "API_KEY=first\nJIRA_URL=https://example\nGROQ_API_KEY=key\n"
    write_env(env_file, original)
    before = env_file.read_bytes()

    real_open = builtins.open

    def failing_open(file, mode="r", *args, **kwargs):
        handle = real_open(file, mode, *args, **kwargs)
        writing = "w" in mode or "a" in mode or "x" in mode
        try:
            in_scope = Path(file).parent == env_file.parent
        except TypeError:
            in_scope = False
        return _HalfWriter(handle) if writing and in_scope else handle

    monkeypatch.setattr(builtins, "open", failing_open)
    with pytest.raises(_WriteFailure):
        config.set_env_value("API_KEY", "second")
    monkeypatch.undo()

    assert env_file.read_bytes() == before, ".env was damaged by a failed write"
    leftovers = [p.name for p in env_file.parent.iterdir() if p.name != ".env"]
    assert leftovers == [], f"partial files left behind: {leftovers}"


# ---------------------------------------------------------------------------
# T13 — boundary cases, one test each
# ---------------------------------------------------------------------------

def test_t13a_key_absent_is_appended(env_file):
    """T13a — EXPECTED GREEN. Absent key: appended, everything else verbatim."""
    write_env(env_file, "# header\nJIRA_URL=https://example")

    config.set_env_value("API_KEY", "brand-new")

    assert content_lines(env_file) == [
        "# header",
        "JIRA_URL=https://example",
        "API_KEY=brand-new",
    ]


def test_t13b_single_line_is_replaced_in_place(env_file):
    """T13b — EXPECTED GREEN. One occurrence: replaced in its slot, no marker."""
    write_env(env_file, "JIRA_URL=https://example\nAPI_KEY=old\n# tail")

    config.set_env_value("API_KEY", "new")

    lines = content_lines(env_file)
    assert lines == ["JIRA_URL=https://example", "API_KEY=new", "# tail"]
    assert not any(MARKER in ln for ln in lines), "a single line must not be marked"


def test_t13c_two_lines_one_empty_collapse_to_the_written_value(env_file):
    """T13c — EXPECTED RED.

    The exact shape of the live .env in this repo: an empty placeholder from
    .env.example plus a filled line appended later. Today the write lands on
    the empty placeholder and the stale filled line keeps winning.
    """
    write_env(env_file, "API_KEY=\nAPI_KEY=stale-but-effective")

    config.set_env_value("API_KEY", "fresh")
    config.reload()

    assert config.API_KEY == "fresh"
    assert live_lines(env_file, "API_KEY") == ["API_KEY=fresh"]


def test_t13d_missing_file_is_created(env_file):
    """T13d — EXPECTED GREEN. No .env at all: the file is created."""
    assert not env_file.exists()

    config.set_env_value("API_KEY", "created")

    assert content_lines(env_file) == ["API_KEY=created"]


# ---------------------------------------------------------------------------
# TE1-TE2 — encoding
# ---------------------------------------------------------------------------

def test_te1_non_ascii_content_stays_utf8(env_file):
    """TE1 — EXPECTED GREEN today; its weight is carried by the mutation.

    Measured (Adım 0): today's writer already passes encoding="utf-8" on both
    the read and the write, and dotenv reads UTF-8 (load_dotenv's default is
    forwarded to DotEnv). So nothing is broken here yet — this test exists to
    keep it that way through the rewrite, where a NamedTemporaryFile or a bare
    open() would silently fall back to the locale codec.

    On this machine that codec is cp1254. Measured: 'Ünlü Proje / şirket adı'
    encodes to b'\\xdcnl\\xfc...' in cp1254, which raises UnicodeDecodeError
    when read back as UTF-8 — so dropping the encoding argument turns this test
    red here. On CI (ubuntu, UTF-8 default) the same mutation stays green; TE2
    is what covers that case.

    Deliberately blind to line endings: it compares line CONTENT, because a
    byte-for-byte comparison would fail for T7's reason and mislabel itself.
    """
    write_env(
        env_file,
        "# Türkçe yorum satırı: şğıöçü\n"
        'QUOTED_KEY="Ünlü Proje / şirket adı"\n'
        "API_KEY=eski",
    )

    config.set_env_value("API_KEY", "yeni-değer-şğıöçü")
    config.reload()

    lines = content_lines(env_file)
    assert lines[0] == "# Türkçe yorum satırı: şğıöçü"
    assert lines[1] == 'QUOTED_KEY="Ünlü Proje / şirket adı"'
    assert lines[2] == "API_KEY=yeni-değer-şğıöçü"
    assert config.API_KEY == "yeni-değer-şğıöçü"
    assert b"yeni-de\xc4\x9fer" in env_file.read_bytes(), "value must be stored as UTF-8"


def test_te2_every_open_in_config_declares_an_encoding():
    """TE2 — EXPECTED GREEN.

    The structural half of the encoding rule, and the half that works in CI:
    TE1 can only go red where the locale codec is not UTF-8, so on ubuntu it
    would pass with the argument removed. This one reads config.py's AST and
    fails anywhere.

    Matched on the call node, never on a source substring: the project has been
    burned three times by comparisons against rendered text.
    """
    source = Path(config.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_open = (isinstance(func, ast.Name) and func.id == "open") or (
            isinstance(func, ast.Attribute) and func.attr in ("open", "write_text", "read_text")
        )
        if is_open and not any(kw.arg == "encoding" for kw in node.keywords):
            offenders.append(f"line {node.lineno}")

    assert offenders == [], f"open() without an explicit encoding in config.py: {offenders}"


# ---------------------------------------------------------------------------
# Faz 6B — emptying a key, and the retired lines the 6A writer leaves behind
# ---------------------------------------------------------------------------
# WRITTEN BEFORE THE FIX. The migration to keyring has to leave `.env` with no
# secret in it, and "no secret" has to include the comments — 6A retires a
# duplicate by commenting it out, which moves the value but does not remove it.
#
# Measured on today's writer: set_env_value does not branch on the value, so
# writing "" still comments earlier duplicates and the old value survives on a
# `# API_KEY=...  # [marker]` line. And _is_assignment_line deliberately never
# matches a comment (T5), so nothing in the codebase can ever touch that line
# again. It is not a transient state; it is permanent.

def test_t14_emptying_a_key_empties_its_duplicates_too(env_file):
    """T14 — EXPECTED RED.

    The live line is emptied and the earlier occurrence is emptied with it,
    rather than being commented out with its value intact. Commenting is right
    when a real value is being written — the retired line documents what was
    replaced. It is wrong when the point of the write is that the value must
    stop existing.
    """
    write_env(env_file, "JIRA_URL=a\nAPI_KEY=first-secret\nOTHER_KEY=b\nAPI_KEY=second-secret")

    config.set_env_value("API_KEY", "")

    text = "\n".join(content_lines(env_file))
    assert "first-secret" not in text, "the duplicate kept its value"
    assert "second-secret" not in text
    assert live_lines(env_file, "API_KEY") == ["API_KEY="]


def test_t15_a_retired_line_keeps_its_marker_and_loses_its_value(env_file):
    """T15 — EXPECTED RED.

    Emptying blanks the value; it does not delete the line and does not drop the
    marker. One rule for both halves of the file — "empty it, never delete it" —
    rather than one rule for live lines and another for retired ones.

    The marker earns its place here: it is the record that a duplicate existed
    at all. A user whose key changed under them can see that this file once had
    two, which is the question they will actually be asking.
    """
    write_env(env_file, "API_KEY=first-secret\nAPI_KEY=second-secret")

    config.set_env_value("API_KEY", "")

    lines = content_lines(env_file)
    text = "\n".join(lines)
    assert "first-secret" not in text
    assert MARKER in text, "the retired line lost its marker"
    assert lines[0].lstrip().startswith("#")
    assert "API_KEY=" in lines[0]
    assert len(lines) == 2, "emptying must not delete or add lines"


def test_t16_writing_a_real_value_still_comments_the_duplicate(env_file):
    """EXPECTED GREEN — the 6A behaviour, pinned against the T14 change.

    T14 adds a branch. This is the guard that the branch is a branch and not a
    replacement: a normal save must keep retiring duplicates by commenting,
    which is what T2 and T6 are built on.
    """
    write_env(env_file, "API_KEY=first\nAPI_KEY=second")

    config.set_env_value("API_KEY", "third")

    lines = content_lines(env_file)
    assert lines[0].lstrip().startswith("#")
    assert MARKER in lines[0]
    assert live_lines(env_file, "API_KEY") == ["API_KEY=third"]


def test_t17_emptying_clears_a_previously_retired_secret(env_file):
    """T17 — EXPECTED RED. The D6 rule, and the reason the others are not enough.

    This is the file a user ends up with if they save from the Settings page
    once between 6A shipping and 6B shipping: the live line moved, and the old
    key sits in a comment. The migration must leave nothing of it.

    THE SCAN INCLUDES COMMENTS. A check that only looked at the lines dotenv
    reads would pass on this file while the secret is still sitting in it, which
    is exactly the failure being closed.

    THE RETIRED LINE IS PRODUCED BY THE WRITER, not hand-written. The first
    version of this test spelled the format out and got it wrong — the `MARKER`
    constant here omits the leading `#` that `config._DUPLICATE_MARKER` carries,
    so the fixture was a line the writer would never emit and the test measured
    nothing. Driving `set_env_value` twice reproduces the real sequence: a user
    saves once after 6A shipped, then the 6B migration runs.
    """
    write_env(env_file, "JIRA_URL=a\nAPI_KEY=retired-secret\nAPI_KEY=live-secret")

    config.set_env_value("API_KEY", "rotated-secret")  # 6A retires line 2

    retired = [ln for ln in content_lines(env_file) if MARKER in ln]
    assert retired and "retired-secret" in retired[0], "fixture did not retire a line"

    config.set_env_value("API_KEY", "")  # the migration

    text = "\n".join(content_lines(env_file))
    assert "retired-secret" not in text, "a commented-out secret survived the migration"
    assert "rotated-secret" not in text
    assert "live-secret" not in text
    assert "JIRA_URL=a" in text, "unrelated lines must be left alone"


def test_t18_emptying_leaves_another_keys_retired_line_alone(env_file):
    """EXPECTED GREEN once T17 lands. Scope: only the key being emptied.

    A retired line for some other key is not this migration's business. The
    marker narrows the target, but a user can paste anything into their own
    file, so the blast radius is held to exactly the key being moved.

    The retired line is produced by the writer, for the reason given in T17.
    """
    write_env(env_file, "GROQ_API_KEY=other-secret\nGROQ_API_KEY=other-live\nAPI_KEY=mine")

    config.set_env_value("GROQ_API_KEY", "other-rotated")  # retires other-secret

    config.set_env_value("API_KEY", "")

    text = "\n".join(content_lines(env_file))
    assert "other-secret" in text, "another key's retired line was touched"
    assert "other-rotated" in text
