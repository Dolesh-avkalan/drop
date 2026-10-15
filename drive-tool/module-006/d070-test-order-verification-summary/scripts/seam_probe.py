"""Independent verification that the OrderedScanAdapter seam really enforces
BOTH the root order and the nested sub/ order, independent of filesystem order.

This does not reuse the test's assertion; it instruments the seam and records
the exact sequence of names yielded at each directory, then compares that
against the raw filesystem order (os.scandir) to prove the seam -- not the
filesystem -- decides the order.
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
from drive_tool.storage import ROOT_ID, FileRef  # noqa: E402


class _RecProxy:
    """Delegating proxy so we can observe yielded names (dunders on the type)."""

    def __init__(self, inner, rec):
        self._inner = inner
        self._rec = rec
        self._seq = None

    def __enter__(self):
        self._inner.__enter__()
        self._seq = []
        self._rec.append(self._seq)
        return self

    def __iter__(self):
        return self

    def __next__(self):
        entry = self._inner.__next__()
        self._seq.append(entry.name)
        return entry

    def __exit__(self, exc_type, exc, tb):
        return self._inner.__exit__(exc_type, exc, tb)


def instrument(adapter):
    rec = []
    orig = adapter._os_scandir

    def _os_scandir(fd):
        return _RecProxy(orig(fd), rec)

    adapter._os_scandir = _os_scandir
    return rec


def run(order):
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "sub").mkdir()
        T._write_files(root / "sub", ["a.txt", "b.txt"])
        raw_root = [e.name for e in os.scandir(root)]
        raw_sub = [e.name for e in os.scandir(root / "sub")]
        adapter = T.OrderedScanAdapter("src", str(root), order=order)
        rec = instrument(adapter)
        try:
            rb = adapter.scan_children(FileRef("src", ROOT_ID), max_entries=100)
            sb = adapter.scan_children(FileRef("src", "p/sub"), max_entries=100)
        finally:
            adapter.close()
    return raw_root, raw_sub, rec, rb, sb


def main():
    print("=== SEAM ENFORCEMENT PROBE (independent of the test assertions) ===")
    ok = True
    for order, expect_root, expect_sub in (
        (["sub", "a.txt", "b.txt"], ["sub"], ["a.txt", "b.txt"]),
        (["sub", "b.txt", "a.txt"], ["sub"], ["b.txt", "a.txt"]),
    ):
        raw_root, raw_sub, rec, rb, sb = run(order)
        yielded_root = rec[0]
        yielded_sub = rec[1]
        root_ok = yielded_root == expect_root
        sub_ok = yielded_sub == expect_sub
        ok = ok and root_ok and sub_ok
        print(f"\norder={order}")
        print(f"  raw fs order (root)       = {raw_root}")
        print(f"  seam-yielded order (root) = {yielded_root}   -> {'OK' if root_ok else 'MISMATCH'}")
        print(f"  raw fs order (sub)        = {raw_sub}")
        print(f"  seam-yielded order (sub)  = {yielded_sub}   -> {'OK' if sub_ok else 'MISMATCH'}")
        print(f"  scan_children(root).inspected = {rb.inspected} complete={rb.complete}")
        print(f"  scan_children(sub).inspected  = {sb.inspected} complete={sb.complete}")
    print(f"\nSEAM ENFORCES BOTH NESTED ORDERS: {ok}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
