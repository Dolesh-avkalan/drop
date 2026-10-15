"""Run the patched target test and print each subTest explicitly, so the
'both nested orders pass' claim is backed by per-subcase evidence rather than
the silent verbose output.
"""
from __future__ import annotations

import os
import sys
import unittest

REPO = os.environ["D070_REPO"]
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))

import test_partial_scan_review_fixes as T  # noqa: E402


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.subs = []

    def addSubTest(self, test, subtest, err):
        self.subs.append((str(subtest), err))
        super().addSubTest(test, subtest, err)


def main():
    name = "test_metadata_failure_below_root_is_skipped_and_charged"
    suite = unittest.TestSuite([T.PostYieldStorageErrorTests(name)])
    runner = unittest.TextTestRunner(verbosity=2, resultclass=RecordingResult)
    res = runner.run(suite)
    print("--- subcase results ---")
    for s, err in res.subs:
        print(f"  {'PASS' if err is None else 'FAIL'}  {s}")
    print(f"subtests={len(res.subs)} failures={len(res.failures)} errors={len(res.errors)}")
    sys.exit(0 if res.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
