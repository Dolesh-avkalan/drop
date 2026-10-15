# D077 — source publication and verification (report)

**Task:** D077. Retrieve the independently verified D070 candidate test file from
`drop` @ `556ca517`, publish a NEW branch `feature/test-nested-scan-order` from exact
`b7f8d17` with ONLY `tests/test_partial_scan_review_fixes.py` byte-identical to that
candidate, verify blob `c01003e7` and strict nested orders 2/3, then re-download the
published branch and run the targeted test and the full 506 suite on 3.11 and 3.12.

## 1. Retrieval (D070 source)

- evidence repo `Dolesh-avkalan/drop`, commit `556ca51743227275ce101f15b6d15a3e1febba66`
- path `drive-tool/module-006/d070-test-order-verification-summary/candidate/test_partial_scan_review_fixes.py`
- blob `c01003e7015915db3dcac15a168ff7aae3d423db`, 18702 bytes,
  sha256 `4da34a8a5ce25771befa6dc19159992439a79326e1c5450ea3e6533749bfac97`
- the blob and sha256 match the D070 `hashmanifest.txt` entry and the reported
  `c01003e7` prefix. No content was altered.

## 2. Publication

- repo `Dolesh-avkalan/drive-tool`, NEW branch `feature/test-nested-scan-order`
- base `b7f8d17b9dcc4aec68d54b38f994290e05264e67` (tree `4a4e27b9d3f75ffd7c841aa547eacef82734596e`)
- head `8f3a80d91126f98a460316b9008661949a8cb6de` (tree `72c5d144c4f8399d8c71f1a610e3bf439efd0f8d`)
- **single-file scope**: exactly one modification, `M tests/test_partial_scan_review_fixes.py`
  (base blob `f110f83c95b846bc853069194ff7759b690ebfca` → head blob
  `c01003e7015915db3dcac15a168ff7aae3d423db`). The head blob is byte-identical to the
  D070 candidate — the same content-addressed sha — so the published file is exactly the
  corrected candidate with no new fixes.
- no production file changed; no other test touched.

## 3. Verification (from the re-downloaded published branch)

Fetched `origin/feature/test-nested-scan-order`, confirmed head/tree/blob as above and
`cmp` byte-identity against the D070 candidate, then ran from those fetched bytes:

| Run | CPython 3.11.2 | CPython 3.12.13 |
| --- | --- | --- |
| targeted `tests.test_partial_scan_review_fixes` (verbose) | Ran 18, OK, exit 0 | Ran 18, OK, exit 0 |
| full `unittest discover -s tests` | Ran 506, OK — 0 failures, 0 skips, exit 0 | Ran 506, OK — 0 failures, 0 skips, exit 0 |
| compile + import | OK | OK |

The full 506 suite is green on both interpreters (the 506 baseline is preserved; the
modified file keeps the same test count, only the nested-order case is parameterised).

**Strict nested orders 2/3.** A probe (`scripts/probe_nested_order.py`) reproduces the
corrected test's two ordered subcases and prints the observed strict counts — identical
on both interpreters:

```
order=['sub', 'a.txt', 'b.txt']  inspected=2 (expected 2) skipped=('p/sub',) truncated=True reason='skipped' -> OK
order=['sub', 'b.txt', 'a.txt']  inspected=3 (expected 3) skipped=('p/sub',) truncated=True reason='skipped' -> OK
```

## 4. Scope and safety

This was retrieval / publication / verification only. No merge, no deploy, no real roots,
no production changes, and no HTTP branch or HTTP test was altered.
