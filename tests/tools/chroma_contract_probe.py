"""Run ChromaDB's four load-bearing contracts against the installed client.

WHY THIS IS A TOOL AND NOT A TEST. `adapters/vector_store.py` records four
chromadb behaviours its logic depends on, transcribed by hand out of the pinned
version's source. Two rounds of source reading missed that one of the four names
the wrong exception type; a behavioural probe caught it on the first run. So
source reading is not sufficient for these four, and the block's own instruction
-- "if the pin in requirements.txt moves, these four are the things to re-read"
-- needs something executable behind it.

It is NOT collected by pytest, deliberately, and the file name keeps it that
way (`tests/tools/`, no `test_` prefix -- same as `chroma_cleanup.py`). Adding
it to the suite would mean running a real client on every CI run, and this repo
has no network tests at all; the default embedding function would also pull an
ONNX model onto the runner, which is a new class of CI dependency and not this
phase's decision.

NO NETWORK, BY CONSTRUCTION. Every collection is created with the counting
embedding function below, so chroma never reaches for its default ONNX model.
That is what lets this run on any machine, offline, in about a second.

Usage:
    python tests/tools/chroma_contract_probe.py

The closing section prints the result as `#`-prefixed lines, ready to paste
into the contract block in `adapters/vector_store.py`. Exit code is 1 if any
contract no longer holds.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any

import chromadb

LINE_LIMIT = 96  # ruff limit is 100; 4 columns of headroom for the paste site
EMBEDDING_DIM = 3
DOC_IDS = ["a", "b", "c"]
DOCUMENTS = ["doc a", "doc b", "doc c"]
METADATAS: list[dict[str, Any]] = [
    {"k": "1", "empty": ""},
    {"k": "2", "empty": "x"},
    {"k": "3", "empty": "y"},
]


class CountingEmbeddingFunction:
    """A stand-in embedding function that counts how many documents it embeds.

    The count is the whole point: contract 4 is about whether `upsert` re-embeds
    documents it was already given, and the only way to observe that is to see
    the embedding function called again.
    """

    def __init__(self) -> None:
        self.documents = 0
        self.batches = 0

    # The parameter must be named `input`: chroma validates the signature of an
    # embedding function and rejects anything else.
    def __call__(self, input: list[str]) -> list[list[float]]:
        self.documents += len(input)
        self.batches += 1
        return [[0.1] * EMBEDDING_DIM for _ in input]

    def name(self) -> str:
        return "counting_probe_ef"


class Finding:
    """One contract or open question, with what was actually observed."""

    def __init__(self, key: str, claim: str) -> None:
        self.key = key
        self.claim = claim
        self.held = False
        self.observed = ""

    def record(self, held: bool, observed: str) -> None:
        self.held = held
        self.observed = observed


def _new_collection(store: Path, ef: CountingEmbeddingFunction) -> Any:
    client = chromadb.PersistentClient(path=str(store))
    return client.create_collection(
        name="contract_probe",
        metadata={"hnsw:space": "cosine"},
        embedding_function=ef,
    )


def _raised(call: Any) -> tuple[str, str]:
    """Return (exception class name, message) for a call expected to raise."""
    try:
        call()
    except Exception as exc:  # the type is the measurement, so catch broadly
        return type(exc).__name__, str(exc).strip()
    return "", ""


def probe(collection: Any, ef: CountingEmbeddingFunction) -> list[Finding]:
    findings = []

    one = Finding("1", "get(include=[...]) always returns ids; limit=None returns everything")
    got = collection.get(include=["documents"])
    keys = sorted(k for k, v in got.items() if v is not None)
    all_ids = collection.get()["ids"]
    named, _ = _raised(lambda: collection.get(include=["ids"]))
    one.record(
        got.get("ids") == DOC_IDS and len(all_ids) == len(DOC_IDS),
        f"include=['documents'] -> keys {keys}, ids {got.get('ids')}; "
        f"limit=None -> {len(all_ids)}/{collection.count()}; "
        f"include=['ids'] rejected with {named or 'nothing'}",
    )
    findings.append(one)

    two = Finding("2", "delete(ids=[]) raises ValueError, and does not empty the collection")
    before = collection.count()
    name, message = _raised(lambda: collection.delete(ids=[]))
    two.record(
        name == "ValueError" and collection.count() == before,
        f"{name or 'no exception'}: {message[:70]} | count {before} -> {collection.count()}",
    )
    findings.append(two)

    # THE EXCEPTION TYPES ARE CHECKED BY NAME, not by "something was raised".
    # The whole reason this tool exists is that the block recorded the wrong type
    # for the duplicate case -- it said ValueError, and DuplicateIDError is not
    # one (`DuplicateIDError <- ChromaError <- Exception`). A loose check would
    # keep passing through exactly the change this tool is here to catch.
    three = Finding(
        "3",
        "upsert() rejects duplicate ids (DuplicateIDError) and empty lists (ValueError)",
    )
    dup_name, dup_message = _raised(
        lambda: collection.upsert(ids=["a", "a"], documents=["x", "y"])
    )
    empty_name, empty_message = _raised(lambda: collection.upsert(ids=[], documents=[]))
    three.record(
        dup_name == "DuplicateIDError" and empty_name == "ValueError",
        f"duplicate ids -> {dup_name or 'no exception'}: {dup_message[:52]} | "
        f"empty lists -> {empty_name or 'no exception'}: {empty_message[:52]}",
    )
    findings.append(three)

    four = Finding("4", "upsert() re-embeds unconditionally when embeddings is None")
    start = ef.documents
    collection.upsert(ids=DOC_IDS, documents=DOCUMENTS, metadatas=METADATAS)
    unchanged_delta = ef.documents - start
    start = ef.documents
    collection.upsert(ids=["a"], documents=["doc a"], embeddings=[[0.9] * EMBEDDING_DIM])
    supplied_delta = ef.documents - start
    four.record(
        unchanged_delta == len(DOC_IDS) and supplied_delta == 0,
        f"re-upserting {len(DOC_IDS)} unchanged docs embedded {unchanged_delta}; "
        f"passing embeddings= embedded {supplied_delta}",
    )
    findings.append(four)

    open_a = Finding("A", "deleting an id that does not exist is a no-op")
    before = collection.count()
    name, message = _raised(lambda: collection.delete(ids=["no-such-id"]))
    open_a.record(
        not name and collection.count() == before,
        f"{name or 'no exception'} | count {before} -> {collection.count()} "
        "(a warning IS logged by the segment layer)",
    )
    findings.append(open_a)

    open_b = Finding("B", "an empty-string metadata value survives the round trip")
    stored = collection.get(ids=["a"], include=["metadatas"])["metadatas"][0]
    open_b.record(
        stored.get("empty") == "",
        f"wrote {{'k': '1', 'empty': ''}}, read {stored}",
    )
    findings.append(open_b)

    return findings


def paste_block(findings: list[Finding]) -> list[str]:
    """The findings as comment lines that fit the repo's 100-column ruff limit.

    Wrapped here rather than left to whoever pastes it: `vector_store.py` is NOT
    in `E501`'s per-file quarantine, so a long line pasted into the contract
    block would turn `ruff check .` red and raise the isolated lint balance.
    Measured -- the unwrapped form ran to 150+ columns.
    """
    lines = [
        f"# Probed against chromadb=={chromadb.__version__} with",
        "# tests/tools/chroma_contract_probe.py. Re-run it when the pin moves.",
    ]
    for finding in findings:
        state = "HOLDS " if finding.held else "BROKEN"
        lines += textwrap.wrap(
            f"{finding.key}. {state} {finding.claim}",
            width=LINE_LIMIT,
            initial_indent="# ",
            subsequent_indent="#    ",
        )
        lines += textwrap.wrap(
            f"observed: {finding.observed}",
            width=LINE_LIMIT,
            initial_indent="#    ",
            subsequent_indent="#      ",
            break_long_words=False,
        )
    return lines


def report(findings: list[Finding]) -> int:
    print(f"chromadb {chromadb.__version__}  (probe: no network, synthetic embeddings)")
    print()
    for finding in findings:
        state = "HOLDS" if finding.held else "BROKEN"
        print(f"[{state:6}] {finding.key}. {finding.claim}")
        print(f"           observed: {finding.observed}")
    broken = [f for f in findings if not f.held]

    print()
    print("--- paste into the contract block in adapters/vector_store.py ---")
    for line in paste_block(findings):
        print(line)
    print("--- end ---")

    if broken:
        print()
        print(f"{len(broken)} contract(s) no longer hold: {', '.join(f.key for f in broken)}")
        return 1
    return 0


def main() -> int:
    store = Path(tempfile.mkdtemp(prefix="chroma_contract_probe_"))
    try:
        ef = CountingEmbeddingFunction()
        collection = _new_collection(store, ef)
        collection.upsert(ids=DOC_IDS, documents=DOCUMENTS, metadatas=METADATAS)
        return report(probe(collection, ef))
    finally:
        shutil.rmtree(store, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
