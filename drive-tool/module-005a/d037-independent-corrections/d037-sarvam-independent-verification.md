# d037 — independent verification of the MODULE-005A corrections (Sarvam)

Independent check of corrected candidate **`e88c9c79fdc27057622d44ba51e008f2e4ea4f4f`**
(`Dolesh-avkalan/drive-tool`, branch `feature/module-005a-review-fixes`), base
`593759a40645386427bad35d53e8b856aeaa68d5`. Retrieved through the GitHub
connection and executed in the sandbox. **No candidate source was modified, no
merge or deploy occurred.** This is sandbox execution, not target-cloud
execution; the frontier static review has not run and is not claimed.

## 0. Pin, identity and scope

- **Corrected candidate:** `e88c9c79fdc27057622d44ba51e008f2e4ea4f4f` — the head of
  `feature/module-005a-review-fixes`, `ahead_by: 1`, `behind_by: 0`, single commit
  over the base. Commit tree `abc0ffb2f561b375cd5166a6bf223d45e3b834c2`.
- **Base / old:** `593759a40645386427bad35d53e8b856aeaa68d5` (original branch
  preserved).
- **Blob hashes (candidate, verified locally):** `search.py f2d8407d…`,
  `local.py a0e43e17…`, `storage.py 3f4f8dcf…` (**unchanged**),
  `test_search.py 2ef9c5b8…`, `test_partial_scan.py ca73b070…`,
  `test_partial_scan_review_fixes.py f110f83c…`, `MODULE-005A.md bbca1c0c…`.
- **Scope (`diff -rq` old vs new)** is exactly the allowed set: `drive_tool/search.py`,
  `drive_tool/local.py`, `tests/test_search.py`, `tests/test_partial_scan.py`, new
  `tests/test_partial_scan_review_fixes.py`, `docs/evidence/MODULE-005A.md`.
  `storage.py`, `local_write.py`, `listing.py`, `__init__.py`, read/stat
  containment, `session/` and every other test file are **byte-identical**
  (`cmp`).

## 1. Environment and full-suite execution

Debian GNU/Linux 12 (bookworm), x86_64, uid 1000, **gVisor** sandbox kernel;
**Python 3.11.2** and **3.12.13** (no interpreter installed). Command (repo root):
`python3.11 -m unittest discover -s tests -p 'test_*.py' -v` (and `python3.12`).

| Interpreter | Count | Final | Exit | Skips |
| --- | --- | --- | --- | --- |
| 3.11.2 | `Ran 274 tests` | `OK` | 0 | 0 |
| 3.12.13 | `Ran 274 tests` | `OK` | 0 | 0 |

This independently reproduces the builder's **274 tests, OK, exit 0** claim
(256 previous + 18 new). Raw logs: `logs/suite_new_python3.11.log`,
`logs/suite_new_python3.12.log`.

## 2. Old-fail / new-pass on the FINAL committed regression file

The final committed `tests/test_partial_scan_review_fixes.py` (read from the
candidate commit, not an in-chat copy; blob `f110f83c…`, 18 tests) was run
**unmodified** against a scratch copy of the old `593759a` code and against the
corrected candidate.

| Run | Interpreter | Result | Exit |
| --- | --- | --- | --- |
| regression vs **old** `593759a` | 3.11.2 | `Ran 18 … FAILED (failures=5, errors=4)` | 1 |
| regression vs **old** `593759a` | 3.12.13 | `Ran 18 … FAILED (failures=5, errors=4)` | 1 |
| regression vs **new** `e88c9c7` | 3.11.2 | `Ran 18 … OK` | 0 |
| regression vs **new** `e88c9c7` | 3.12.13 | `Ran 18 … OK` | 0 |

Genuine old-fail (9 = 5 failures + 4 errors), each for the intended reason
(tracebacks in `logs/oldfail_python3.1*.log`):

- **F-B (3 failures):** `test_prescan_skipped_subdir_is_not_complete`,
  `test_midscan_skipped_subdir_is_not_complete` — old returns `truncated=False`
  (`AssertionError: False is not true`); `test_skipped_means_unknown_not_not_found`
  — old reports a not-found-shaped complete result.
- **F-A (1 failure):** `test_malformed_failure_error_below_root_raises_not_skipped`
  — `AssertionError: StorageError not raised` (old silently skipped below root).
- **F-C (4 errors + 1 failure):** `test_metadata_storage_error_after_prefix_is_scanfailure`,
  `test_stat_storage_error_after_prefix_is_scanfailure`,
  `test_next_seam_storage_error_after_prefix_is_scanfailure`,
  `test_primary_and_cleanup_errors_no_leak_no_retry` — old raises a **bare**
  `LocalStorageError` (no charged `ScanFailure`); and
  `test_metadata_failure_below_root_is_skipped_and_charged` — `1 != 2` raw work
  not charged.

The `test_primary_and_cleanup_errors_no_leak_no_retry` old-failure occurs at the
`scan_children` call (bare error), **before** any fd measurement — so this
old-fail is not an artefact of the earlier fd-measurement bug; the final file
measures fds within the same adapter lifetime.

## 3. Independent probe battery (`scripts/probe_d037.py`)

An independent seam (own `_Scandir`/`_Entry`/`build_error`/`stat_error`/
`next_error`) re-runs the **40 d034 contract checks** and converts the six former
findings into **18 positive assertions**. Result: **58/58 PASS, 0 FAIL, 0 ERROR**,
identically on 3.11 and 3.12 (`logs/probe_d037_python3.*.log`). Highlights:

- The 40 d034 checks still pass: strict-B with no B+1 `next()`; local
  exact-budget `complete=False`; retained prefix matches; mixed omitted/raw
  charging; OSError iteration/stat/iterator-close charged; root error identity;
  sibling suppression after exhaustion; result/depth priority; loud malformed
  rejection; capability denial.
- **F-B positive:** pre-scan and mid-scan skipped folders now return
  `truncated=True, reason="skipped"` with `skipped` retained; `max_results`,
  `max_depth` and `max_entries` reasons keep precedence when they stop the walk
  first; empty `skipped` on a truly exhausted walk stays `truncated=False,
  reason=None`.
- **F-A positive:** a malformed `ScanFailure.error` raises `StorageError` at the
  **root and below the root** (not converted to `skipped`); a valid root error's
  object identity and `__cause__` are preserved.
- **F-C positive:** a post-yield `StorageError` from the metadata, stat and
  next-iteration seams becomes `ScanFailure(inspected=N, error=boom)` with
  `__cause__` the original error; a **pre-yield** `StorageError` is unchanged
  (not `ScanFailure`); an existing `ScanFailure` is **not double wrapped**;
  primary error **wins** over a simultaneous cleanup failure with **no close
  retry** and **no fd growth measured within the same adapter lifetime**.

Run against the old `593759a` code the same battery records 5 FAIL + 1 ERROR
(`logs/probe_d037_on_old_py311.log`), i.e. the new assertions genuinely capture
the fixes (the 40 base checks still pass on old).

## 4. Mutation checks (`scripts/mutants_d037.py`)

Applied to isolated scratch copies (never committed); full suite run each time,
identical on 3.11 and 3.12 (`logs/mutants_d037_python3.*.log`).

**Three new protections — all caught (0 survivors):**

| Mutation | Result | Caught by |
| --- | --- | --- |
| N1 remove skipped terminal truncation (F-B) | CAUGHT | 6 tests incl. the two updated old expectations + `test_prescan/midscan_skipped_subdir_is_not_complete`, `test_skipped_means_unknown_not_not_found` |
| N2 restore root-only `failure.error` validation (F-A) | CAUGHT | `test_malformed_failure_error_below_root_raises_not_skipped` |
| N3 remove generic post-yield `StorageError` wrapping (F-C) | CAUGHT | 5 tests incl. `test_metadata/stat/next_*_is_scanfailure`, `test_primary_and_cleanup_errors_no_leak_no_retry` |

**The original seven d034 protections — all still caught (source matching
permitted; 0 survivors):** M1 discard partial matches (3), M2 count only metadata
(3), M3 read B+1 (11), M4 `complete=True` at cap (8), M5 ignore
`ScanFailure.inspected` (5), M6 scan sibling after exhaustion (2), M7 leak fd (4).

## 5. Old behavior unchanged

`storage.py`, `local_write.py`, `listing.py`, `__init__.py` and the read/stat
containment paths are byte-identical; a focused run of the list/read/write/
containment/parser modules is `Ran 190 tests … OK`, exit 0
(`logs/oldbehavior_unchanged_py311.log`). The original 256 tests plus all write
and `list_children` tests remain passing inside the 274.

## 6. Observation (not a defect)

On an **exact** `max_results` last entry (batch complete, no queued/depth work)
alongside an earlier skipped sibling, the terminal return reports
`truncated=True, reason="skipped"` rather than `"max_results"`. This is
defensible and strictly better than the old code (which returned `truncated=False,
reason=None` here): `max_results` was met exactly, not truncating, so the skipped
folder is the sole incompleteness. The brief's precedence rule is about reasons
that *stop the walk first*, which the in-loop returns still honour.

## 7. Verdict

**ACCEPT.**

The three corrections are correct, minimal and in the allowed scope: F-B now makes
`truncated=False` an unqualified-complete signal with bound reasons retaining
precedence; F-A validates `ScanFailure.error` at every depth before the
unwrap/skip decision; F-C charges post-yield seam `StorageError`s without double
wrapping and without converting pre-yield errors or programming errors. The final
committed regression file genuinely fails on old `593759a` (9: 5 failures, 4
errors) and passes on the corrected candidate; all three new protections are
caught by mutations, the original seven still are, and old list/read/write
behavior is unchanged. No blocking findings; the single observation above is a
defensible behavior, not a regression.

## 8. Notes and limits

- Sandbox execution on a gVisor kernel; raw `readdir` order is controlled by the
  deterministic seam. Synthetic, bounded fixtures (<50 MiB); no services,
  credentials or private paths touched; no interpreter installed.
- The frontier static review has **not** run; nothing here depends on or claims it.
- Reproduce: `python3.11 scripts/probe_d037.py` / `scripts/mutants_d037.py`; the
  regression file was run unmodified against a scratch copy of `593759a`.
