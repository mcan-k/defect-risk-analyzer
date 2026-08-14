"""
Measure module-map.json against the files this repository actually tracks.

Answers, with the working shown rather than a single total: how much of the
repository the map covers, which patterns are doing the work, and which are
carrying nothing. A summary line like "20 of 56 files map" is a number you have
to trust; the breakdown below is one you can check.

Read-only. It calls git ls-files and the inference functions directly — no
AnalysisService, no bug data, no ChromaDB, and nothing is written. Running the
real ci_analyzer against this repository would reset data/chroma_db
(adapters/vector_store.py, every upsert_bugs call), which is why this exists.

Deliberately not named test_*.py so pytest does not collect it: the numbers it
prints are a property of the working tree, and a file added to the repo should
not turn the suite red.

Usage: python tests/tools/module_map_report.py [path/to/module-map.json]
"""

import subprocess
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from defect_risk_analyzer.ci_analyzer import (  # noqa: E402  (needs the path above)
    ModuleMap,
    ModuleMapError,
    _matches,
    load_module_map,
)

# The two loops below duplicate select_analyzable_files and
# infer_module_provenance, which still take the keyword table rather than a
# map. They collapse into calls to those functions in the commit that swaps the
# rule; until then the shared part — _matches — is the production matcher, so
# the numbers are measured against the real rule and not a second copy of it.


def analyzable(files: list[str], module_map: ModuleMap) -> list[str]:
    return [f for f in files if not any(_matches(p, f) for p in module_map.exclude)]


def mapped_modules(files: list[str], module_map: ModuleMap) -> dict[str, list[str]]:
    per_module: dict[str, list[str]] = defaultdict(list)
    for file_path in files:
        for pattern, module in module_map.modules.items():
            if _matches(pattern, file_path):
                per_module[module].append(file_path)

    return {module: sorted(set(paths)) for module, paths in per_module.items()}


def tracked_files() -> list[str]:
    """Every file git tracks, in the POSIX form the diff parser also sees."""
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    return out.stdout.split()


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "module-map.json"

    try:
        module_map = load_module_map(path)
    except ModuleMapError as exc:
        print(exc)
        return 1

    files = tracked_files()
    in_scope = analyzable(files, module_map)
    excluded = [f for f in files if f not in set(in_scope)]

    print(
        f"{path.name}: {len(module_map.modules)} module patterns, "
        f"{len(module_map.exclude)} exclude patterns\n"
    )

    print("SCOPE")
    print(f"  tracked files            {len(files):>4}")
    print(f"  excluded                 {len(excluded):>4}")
    print(f"  analyzable               {len(in_scope):>4}\n")

    print("EXCLUDED BY PATTERN   (a file may match more than one)")
    hits = {p: sum(1 for f in files if _matches(p, f)) for p in module_map.exclude}
    for pattern, count in sorted(hits.items(), key=lambda kv: (-kv[1], kv[0])):
        if count:
            print(f"  {pattern:<24} {count:>4}")
    dead = [p for p, count in hits.items() if not count]
    if dead:
        # Not a failure: a map is written for a project, and asset extensions
        # this repository happens not to have are still right for the user's.
        # Printed so the claim "these lines are doing work" is never implied.
        print(f"  0 hits ({len(dead)} patterns)     {' '.join(dead)}")
    print()

    per_module = mapped_modules(in_scope, module_map)
    mapped = {f for paths in per_module.values() for f in paths}
    py_files = [f for f in files if f.endswith(".py")]
    py_mapped = [f for f in mapped if f.endswith(".py")]

    print(
        f"MAPPED   {len(mapped)} of {len(in_scope)} analyzable  "
        f"({len(py_mapped)} of {len(py_files)} tracked .py)"
    )
    for module, paths in sorted(per_module.items()):
        head = ", ".join(Path(p).name for p in paths[:3])
        more = f", +{len(paths) - 3} more" if len(paths) > 3 else ""
        print(f"  {module:<20} {len(paths):>3}   {head}{more}")
    print()

    unmapped = [f for f in in_scope if f not in mapped]
    print(f"UNMAPPED BUT ANALYZABLE   {len(unmapped)}")
    for file_path in unmapped:
        print(f"  {file_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
