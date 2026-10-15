"""Order-independence check: the patched assertion must pass regardless of the
underlying filesystem/creation order, because the seam pins both nested orders.

Runs the patched test's assertion logic across BOTH seam orders x BOTH file
creation orders (a-then-b and b-then-a). All four combinations must pass; this
is the 'no filesystem order masking' evidence for the patched test.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO = os.environ["D070_REPO"]
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))

import test_partial_scan_review_fixes as T  # noqa: E402
from drive_tool.local import LocalStorageError  # noqa: E402
from drive_tool.search import find  # noqa: E402
from drive_tool.storage import ROOT_ID, FileRef  # noqa: E402

CASES = [
    (["sub", "a.txt", "b.txt"], 2),
    (["sub", "b.txt", "a.txt"], 3),
]
CREATION = [("a.txt", "b.txt"), ("b.txt", "a.txt")]


def run(order, creation, expected):
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "sub").mkdir()
        T._write_files(root / "sub", list(creation))
        raw = [e.name for e in os.scandir(root / "sub")]
        adapter = T.OrderedScanAdapter("src", str(root), order=order)
        boom = LocalStorageError("sub metadata boom")
        adapter.probe.build_error = {"a.txt": boom}
        try:
            result = find(adapter, FileRef("src", ROOT_ID), "zzz", max_entries=100)
        finally:
            adapter.close()
    ok = (
        result.inspected == expected
        and result.skipped == ("p/sub",)
        and result.truncated is True
        and result.reason == "skipped"
    )
    return ok, raw, result


def main():
    print("=== ORDER-INDEPENDENCE (no filesystem order masking) ===")
    all_ok = True
    for order, expected in CASES:
        for creation in CREATION:
            ok, raw, r = run(order, creation, expected)
            all_ok = all_ok and ok
            print(f"seam_order={order} creation_order={list(creation)} "
                  f"raw_fs={raw} -> inspected={r.inspected} (expected {expected}) "
                  f"skipped={r.skipped} truncated={r.truncated} reason={r.reason} "
                  f"{'OK' if ok else 'MISMATCH'}")
    print(f"\nPATCHED ASSERTION IS FILESYSTEM-ORDER INDEPENDENT: {all_ok}")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
