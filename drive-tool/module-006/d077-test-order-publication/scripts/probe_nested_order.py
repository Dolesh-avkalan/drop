"""D077 probe (not a test): print the strict inspected counts for both nested orders.

Mirrors the corrected test test_metadata_failure_below_root_is_skipped_and_charged:
the ordered subdirectory entry is charged strictly by scan position, so the
expected inspected count differs with physical order (2 vs 3).
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")
import tests.test_partial_scan_review_fixes as T
from drive_tool.search import find
from drive_tool.storage import FileRef, ROOT_ID
from drive_tool.local import LocalStorageError

for order, expected in ((["sub", "a.txt", "b.txt"], 2),
                        (["sub", "b.txt", "a.txt"], 3)):
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "sub").mkdir()
        T._write_files(root / "sub", ["a.txt", "b.txt"])
        adapter = T.OrderedScanAdapter("src", str(root), order=order)
        adapter.probe.build_error = {"a.txt": LocalStorageError("sub metadata boom")}
        try:
            r = find(adapter, FileRef("src", ROOT_ID), "zzz", max_entries=100)
            verdict = "OK" if r.inspected == expected else "MISMATCH"
            print("order=%-26s inspected=%d (expected %d) skipped=%r truncated=%s "
                  "reason=%r -> %s"
                  % (order, r.inspected, expected, r.skipped, r.truncated,
                     r.reason, verdict))
        finally:
            adapter.close()
