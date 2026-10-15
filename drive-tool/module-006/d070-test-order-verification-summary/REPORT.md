# D070 — D066 test-only patch: assembly, seam verification, and evidence (raw report)

Scope: single path — `tests/test_partial_scan_review_fixes.py`, one method
(`PostYieldStorageErrorTests.test_metadata_failure_below_root_is_skipped_and_charged`).
No production edits in the candidate. No merge, no deploy, no real roots.

## 1. Source resolution (exact SHAs)

| item | value |
|---|---|
| repository | `Dolesh-avkalan/drive-tool` |
| source ref (as supplied to this task) | `4140a528383ad5794cafd1c99aea9a41d9acef11` (commit "Prepare short Sarvam test-order patch verification") |
| source tree | `60aa6b03e2cc50234e14175eb9de9974386633ce` |
| accepted base (as named in the task) | `b7f8d17b9dcc4aec68d54b38f994290e05264e67` (merge PR #8 "Add grant-isolated local file-service backend") |
| accepted base tree | `4a4e27b9d3f75ffd7c841aa547eacef82734596e` |
| base test blob | `f110f83c95b846bc853069194ff7759b690ebfca` |
| base `drive_tool/local.py` blob | `74a45c61d3ea9c6e64005b1d92834fed17323d62` |
| candidate branch | `feature/test-nested-scan-order` (local-only; **not pushed**) |
| candidate commit | `8b543f3bf986055c492bc6982341ed5c90beff6d` (local-only) |
| candidate tree | `be4f1f3136a8092b20e1c011fb9d641945a7fe76` |
| candidate test blob | `c01003e7015915db3dcac15a168ff7aae3d423db` |
| DeepSeek drop pin (resolved) | `Dolesh-avkalan/drop` `drive-tool/module-006/d066-test-order-correction.md` @ `fba54dfcb0f660dd12bbbd2faa82cde73459b05a` ("relay: d066 (done)"), tree `3a52df592ffa645b1bb3cbd8f44c5382c91cf352` |

The base `b7f8d17…` is an ancestor of the source ref `4140a52…` (ahead 17,
behind 0); the 17 intervening commits touch only `docs/`, `session/` and
`tasks/` — none touch `tests/` or `drive_tool/`. The test blob and
`drive_tool/local.py` blob are therefore byte-identical at the source ref and
the accepted base, so the patch target is unambiguous.

The local base reconstruction is byte-faithful: its git tree
(`60aa6b03…`) and test blob (`f110f83c…`) equal the GitHub values exactly.

## 2. Patch application

The DeepSeek drop supplies a unified diff (`deepseek-patch-verbatim.diff`).
Its removed block is byte-identical to the file (verified programmatically),
so the change is semantically exact.

Caveat (not a semantic defect): the hand diff's hunk has only one line of
leading context and **no trailing context**. This sandbox's `git apply`
rejects such thin hunks (empirically: 3-lead + 1-trail applies; 3-lead +
0-trail fails; 1-lead + 1-trail fails). A canonical patch regenerated with
`git diff` (full context) — `candidate.diff` — applies cleanly with
`git apply` (`APPLY-CHECK: OK`). The semantic content of both is identical:
one method, 16 lines removed, 22 added.

## 3. Verification results

### 3.1 Seam really enforces BOTH nested orders (independent probe)

`scripts/seam_probe.py` instruments the seam and records the yielded-name
sequence per directory; it does not reuse the test assertion.

| seam order | raw fs sub order | seam-yielded sub order | verdict |
|---|---|---|---|
| `["sub","a.txt","b.txt"]` | `['a.txt','b.txt']` | `['a.txt','b.txt']` | enforced |
| `["sub","b.txt","a.txt"]` | `['a.txt','b.txt']` | `['b.txt','a.txt']` | enforced (overrides fs) |

Root order is `['sub']` in both. Raw filesystem order is unchanged across the
two runs, yet the seam yields a different nested order — so the seam, not the
filesystem, decides the nested order. `SEAM ENFORCES BOTH NESTED ORDERS: True`
on 3.11.2 and 3.12.13.

### 3.2 Original failure reproduced deterministically

`scripts/repro_old_fail.py` runs the **original** body/assertion:

- original pin `order=["sub"]` → inspected `2` → **passes** (bug masked: this
  filesystem's readdir happens to return `a.txt` first).
- reversed nested order `order=["sub","b.txt","a.txt"]` → inspected `3` →
  **`AssertionError: 3 != 2`** (deterministic reproduction of the original
  order-dependent failure).

### 3.3 Patched test — both orders pass

`scripts/newpass_subcases.py` prints each subTest explicitly:

- `(order=['sub','a.txt','b.txt'], expected_inspected=2)` → PASS
- `(order=['sub','b.txt','a.txt'], expected_inspected=3)` → PASS

`subtests=2 failures=0 errors=0`, on 3.11.2 and 3.12.13. Strict equality for
`inspected`, `skipped`, `truncated` and `reason` is preserved; no membership
relaxation, no skip.

### 3.4 Filesystem-order independence (no masking)

`scripts/order_independence.py` crosses both seam orders with both file
creation orders (a-then-b and b-then-a). All four combinations pass on both
interpreters: `PATCHED ASSERTION IS FILESYSTEM-ORDER INDEPENDENT: True`.

### 3.5 Isolated production charging mutation

`scripts/apply_mutation.py` copies the candidate into `mutation/` and changes
`LocalAdapter._post_yield_storage_error` to under-charge by one
(`ScanFailure(entry_count)` → `ScanFailure(entry_count - 1)`) so the entry
that raised from the metadata/stat seam is treated as uncharged. Production
diff: `mutation/local.py.diff`; mutated `local.py` blob
`64380541931308e1750d16743a15dd2b065089d1`.

- Compiles on both interpreters (`py_compile` OK, 3.11 and 3.12).
- Against the patched test, **both** subcases fail on both interpreters:
  - a-first: `AssertionError: 1 != 2`
  - b-first: `AssertionError: 2 != 3`

The mutation was never committed to the candidate.

### 3.6 Target test and full suite

| run | interpreter | result | exit |
|---|---|---|---|
| target `test_metadata_failure_below_root_is_skipped_and_charged` | 3.11.2 | Ran 1, OK | 0 |
| target (same) | 3.12.13 | Ran 1, OK | 0 |
| full suite | 3.11.2 | Ran 506, skipped 0, failures 0, errors 0 | 0 |
| full suite | 3.12.13 | Ran 506, skipped 0, failures 0, errors 0 | 0 |

Full suite run from the candidate tree via
`python -m unittest discover -s tests`.

## 4. Verdict

The DeepSeek D066 patch is **semantically valid and correct**. It pins both
deterministic nested orders through the existing `OrderedScanAdapter` seam,
preserves every strict assertion, and is order-independent. The seam genuinely
enforces both nested orders (verified independently of the test's own
assertion). The original order-dependent failure reproduces deterministically
under a reversed nested order, and the patched test passes both orders. A
meaningful production charging mutation compiles and is caught by both
subcases.

One non-blocking note: the hand diff as pasted is not directly `git apply`-able
in this environment (missing trailing context); a git-regenerated patch with
full context applies cleanly and is byte-for-byte the same change.

## 5. Files

- `candidate/test_partial_scan_review_fixes.py` — the patched test (candidate).
- `candidate.diff` — canonical git-regenerated patch (applies cleanly).
- `deepseek-patch-verbatim.diff` — the D066 hand diff as supplied.
- `mutation/local.py.diff` — isolated production mutation diff.
- `scripts/` — seam probe, old-fail reproduction, newpass subcases,
  order-independence, mutation applier.
- `logs/` — raw logs for every run above.
- `hashmanifest.txt` — sha256 of every file in this folder.
