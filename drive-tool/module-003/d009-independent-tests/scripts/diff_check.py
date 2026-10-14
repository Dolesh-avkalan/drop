#!/usr/bin/env python3
"""d009 independent revision-diff check (asserting).

Provenance: written independently for d009.

Compares the OLD revision tree (110b27e8) with the NEW revision tree (c2b324da)
and asserts:
  * the set of changed/added/removed paths is exactly the four d007-reported
    files;
  * every MODULE-001 blob (and the frozen README / MODULE-003-GEMINI evidence)
    is byte-identical.

Uses git blob hashing (sha1 of "blob <len>\\0<content>") so hashes are
comparable to `git hash-object`.

Usage:
  python3.11 diff_check.py <old_tree> <new_tree>
"""
from __future__ import annotations

import hashlib
import os
import sys

EXPECTED_CHANGED = {
    "drive_tool/local.py",
    "tests/test_local.py",
    "docs/evidence/MODULE-003.md",
}
EXPECTED_ADDED = {
    "docs/evidence/MODULE-003-REVIEW-FIXES.md",
}
MODULE001_AND_FROZEN = {
    "drive_tool/__init__.py",
    "drive_tool/storage.py",
    "tests/test_storage.py",
    "docs/evidence/MODULE-001.md",
    "tasks/MODULE-001.md",
    "README.md",
    "docs/evidence/MODULE-003-GEMINI.md",
}


def blob_sha1(path: str) -> str:
    data = open(path, "rb").read()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def snapshot(root: str) -> dict[str, str]:
    out = {}
    for dirpath, _, files in os.walk(root):
        for f in files:
            if "__pycache__" in dirpath or f.endswith(".pyc"):
                continue  # untracked build artifact from running the suite
            p = os.path.join(dirpath, f)
            out[os.path.relpath(p, root)] = blob_sha1(p)
    return out


def main() -> int:
    old_root, new_root = sys.argv[1], sys.argv[2]
    old = snapshot(old_root)
    new = snapshot(new_root)

    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(p for p in set(old) & set(new) if old[p] != new[p])

    print(f"old tree: {old_root}")
    print(f"new tree: {new_root}")
    print(f"added   ({len(added)}): {added}")
    print(f"removed ({len(removed)}): {removed}")
    print(f"changed ({len(changed)}): {changed}")

    failures = []
    if set(changed) != EXPECTED_CHANGED:
        failures.append(f"changed set {set(changed)} != expected {EXPECTED_CHANGED}")
    if set(added) != EXPECTED_ADDED:
        failures.append(f"added set {set(added)} != expected {EXPECTED_ADDED}")
    if removed:
        failures.append(f"unexpected removals: {removed}")

    print("\n-- MODULE-001 / frozen blobs --")
    for p in sorted(MODULE001_AND_FROZEN):
        same = (p in old and p in new and old[p] == new[p])
        print(f"  {'SAME' if same else 'DIFF'}  {old.get(p,'<missing>')}  {p}")
        if not same:
            failures.append(f"MODULE-001/frozen blob changed or missing: {p}")

    print()
    if failures:
        print("RESULT: FAIL")
        for f in failures:
            print("  -", f)
        return 1
    print("RESULT: PASS - only the four d007 files differ; MODULE-001 blobs unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
