# d066 (deepseek)

- status: done
- chat: https://chat.deepseek.com/a/chat/s/c6643795-de93-4820-87d6-4f0438833f57
- model: deepseek (deepthink on, search off)
- finished: 2026-10-15T21:32:16Z

## Question

DeepSeek, routine minimal deterministic regression-test correction per D066. Preserve exact assertions and charging sensitivity, both nested orders, test-only patch. No production edits, no fake tests claim. Return unified diff and reproduction/mutation plan for Sarvam assembly/execution. Source supplied in pinned brief; no installs/merge/deploy.

(input files: Dolesh-avkalan/drive-tool:tasks/d066-deepseek-test-order.txt@b1bdc0a75ac59feb9f8493a8809454c796ce5c23)

## Answer

PATCH

```diff
--- a/tests/test_partial_scan_review_fixes.py
+++ b/tests/test_partial_scan_review_fixes.py
@@ -395,17 +395,23 @@
     def test_metadata_failure_below_root_is_skipped_and_charged(self):
-        with tempfile.TemporaryDirectory() as td:
-            root = Path(td)
-            (root / "sub").mkdir()
-            _write_files(root / "sub", ["a.txt", "b.txt"])
-            adapter = self._adapter(root, order=["sub"])
-            boom = LocalStorageError("sub metadata boom")
-            adapter.probe.build_error = {"a.txt": boom}
-            try:
-                result = find(adapter, FileRef("src", ROOT_ID), "zzz", max_entries=100)
-                # root (1) + sub's first raw entry (1) = 2.
-                self.assertEqual(result.inspected, 2)
-                self.assertEqual(result.skipped, ("p/sub",))
-                self.assertTrue(result.truncated)
-                self.assertEqual(result.reason, "skipped")
-            finally:
-                adapter.close()
+        cases = (
+            (["sub", "a.txt", "b.txt"], 2),
+            (["sub", "b.txt", "a.txt"], 3),
+        )
+        for order, expected_inspected in cases:
+            with self.subTest(order=order, expected_inspected=expected_inspected):
+                with tempfile.TemporaryDirectory() as td:
+                    root = Path(td)
+                    (root / "sub").mkdir()
+                    _write_files(root / "sub", ["a.txt", "b.txt"])
+                    adapter = self._adapter(root, order=order)
+                    boom = LocalStorageError("sub metadata boom")
+                    adapter.probe.build_error = {"a.txt": boom}
+                    try:
+                        result = find(adapter, FileRef("src", ROOT_ID), "zzz", max_entries=100)
+                        # root (1) + charged sub entries at/after the failure.
+                        self.assertEqual(result.inspected, expected_inspected)
+                        self.assertEqual(result.skipped, ("p/sub",))
+                        self.assertTrue(result.truncated)
+                        self.assertEqual(result.reason, "skipped")
+                    finally:
+                        adapter.close()
```

RATIONALE

The old test pinned only the root order with order=["sub"], so the nested sub/ readdir order was whatever the filesystem returned. The test then hard-coded inspected == 2, which is valid only when a.txt is the first charged entry under sub/. If b.txt is first, b.txt is charged successfully, then a.txt raises LocalStorageError, so the sub-scan ScanFailure carries inspected == 2; with the root sub charge, the final result is inspected == 3.

This patch keeps strict equality for inspected, skipped, truncated, and reason, but pins both deterministic nested orders via the existing OrderedScanAdapter seam. It does not relax to membership, does not skip the test, and does not touch production code.

REPRODUCTION / MUTATION PLAN

Sarvam assembly/execution plan:

1. Apply only the unified diff above to tests/test_partial_scan_review_fixes.py.

2. Run the targeted test, for example:
python -m unittest tests.test_partial_scan_review_fixes.PostYieldStorageErrorTests.test_metadata_failure_below_root_is_skipped_and_charged -v

3. Expected result: both subcases pass:

- order=["sub", "a.txt", "b.txt"] -> inspected == 2

- order=["sub", "b.txt", "a.txt"] -> inspected == 3

Old-test failure reproduction:

- Revert only the nested-order pin, or run the original body with order=["sub", "b.txt", "a.txt"] and the old assertion self.assertEqual(result.inspected, 2).

- It should fail with actual 3 != 2, demonstrating the original dependency on accidental nested readdir order.

Mutation plan for charging sensitivity:

- Temporarily mutate production LocalAdapter.scan_children so the entry that raises LocalStorageError from the metadata/stat seam is not charged, e.g. wrap into ScanFailure(inspected=inspected - 1, ...) or omit the +1 for the failing entry.

- Run the patched test again. Both subcases should fail:

- a-first expected 2 -> actual 1

- b-first expected 3 -> actual 2

- Alternatively, mutate find so it does not add a child ScanFailure.inspected into the final result; the same two failures confirm the regression is detected.

- Do not commit the mutation; it is only for Sarvam’s local verification.

TESTS_NOT_RUN: I did not execute the suite or collect raw logs in this response. No installs, merge, deploy, or production edits were performed.
