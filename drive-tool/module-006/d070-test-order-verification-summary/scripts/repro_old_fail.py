"""Reproduce the ORIGINAL (pre-patch) failure.

The original test pinned only the root order (order=["sub"]), so the nested
sub/ order was whatever the filesystem returned, and it hard-coded
inspected == 2. That assertion is correct only when a.txt is the first charged
entry under sub/.

- test_old_body_filesystem_order : original order pin. On this filesystem
  readdir returns a.txt first, so the old body PASSES (the bug is masked here).
- test_old_body_reversed_nested_order : nested order pinned reversed via the
  same seam, with the ORIGINAL assertion. This FAILS (actual 3 != 2), which is
  the deterministic reproduction of the original order-dependent failure.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = os.environ["D070_REPO"]
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))

import test_partial_scan_review_fixes as T  # noqa: E402
from drive_tool.local import LocalStorageError  # noqa: E402
from drive_tool.search import find  # noqa: E402
from drive_tool.storage import ROOT_ID, FileRef  # noqa: E402


class OldBodyRepro(unittest.TestCase):
    def _run_old_body(self, order):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sub").mkdir()
            T._write_files(root / "sub", ["a.txt", "b.txt"])
            adapter = T.OrderedScanAdapter("src", str(root), order=order)
            boom = LocalStorageError("sub metadata boom")
            adapter.probe.build_error = {"a.txt": boom}
            try:
                result = find(adapter, FileRef("src", ROOT_ID), "zzz", max_entries=100)
                print(f"    [order={order}] actual inspected={result.inspected} "
                      f"skipped={result.skipped} truncated={result.truncated} "
                      f"reason={result.reason}")
                # ORIGINAL, order-dependent assertion (unchanged):
                self.assertEqual(result.inspected, 2)
                self.assertEqual(result.skipped, ("p/sub",))
                self.assertTrue(result.truncated)
                self.assertEqual(result.reason, "skipped")
            finally:
                adapter.close()

    def test_old_body_filesystem_order(self):
        """Original order pin only -> passes here because readdir gave a.txt first."""
        self._run_old_body(["sub"])

    def test_old_body_reversed_nested_order(self):
        """Deterministic reversed nested order -> original assertion fails."""
        self._run_old_body(["sub", "b.txt", "a.txt"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
