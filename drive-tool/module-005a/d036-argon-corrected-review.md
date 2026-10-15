# d036 (gemini)

- status: done
- chat: https://gemini.google.com/app/c58fbc6f391c16af
- model: 4 argon (thinking: high)
- finished: 2026-10-15T15:35:38Z

## Question

Gemini, since file retrieval was unavailable, I am supplying only the changed production code and essential lifetime context as the necessary compact fallback. The task and review material remain versioned in a file; I have omitted the full source/test dump. Review candidate e88c9c79fdc27057622d44ba51e008f2e4ea4f4f using the supplied content. Do not repeat the previous file-link attempt or give a verdict without reviewing this code.

I need independent static review of the complete production delta (MODULE-005A plus d035 corrections), especially strict raw-entry budgets, truthful skipped coverage, failure validation/counts and cleanup priority. The file describes exact scope and limits. Confirm the source pin and quote one actual new branch condition before the verdict. Return ACCEPT/ACCEPT WITH NITS/CHANGES REQUIRED, exact functions and concrete counterexamples for blockers, narrow fixes, TESTS_NOT_RUN, and omitted-source limitations. No implementation/merge/deployment. End STATUS: REVIEWED.

(input files: Dolesh-avkalan/drop:drive-tool/module-005a/d036-d037-input/D036-CODE.txt@80a9e8aff6b97329e42262fa3a8c277ec61f47e1)

## Answer

### Source Pin & Pre-Verdict Verification

- Repository / Branch: Dolesh-avkalan/drop @ 80a9e8aff6b97329e42262fa3a8c277ec61f47e1 (drive-tool/module-005a/d036-d037-input/D036-CODE.txt)

- Candidate Commit: e88c9c79fdc27057622d44ba51e008f2e4ea4f4f

- Base Commit: 356a4d8a71d0e57a57e7c82dbfce50be145a0bdb

- Quoted New Branch Conditions:

- In drive_tool.search._validate_batch_report:

```python
if not complete and inspected != remaining:
```

- In drive_tool.local.LocalAdapter._post_yield_storage_error:

```python
if isinstance(exc, ScanFailure):
```

### Verdict: ACCEPT

No blocking defects were found in the supplied production delta (MODULE-005A plus d035 corrections). All three issues identified in D034 (skipped directories appearing complete, root-only validation of ScanFailure.error, and uncharged StorageError exceptions escaping post-yield seams) are properly resolved.

### Verification by Requirement

- Strict Raw-Entry Budget & Conservative Local EOF (LocalAdapter.scan_children, InMemoryAdapter.scan_children, _validate_scan_max_entries):

- _validate_scan_max_entries rejects bool, None, non-int, values less than 1, and values greater than MAX_SCAN_ENTRIES (100_000).

- LocalAdapter.scan_children loops with while entry_count < max_entries: and increments entry_count += 1 immediately after entry = next(entries), prior to name validation ("", ".", "..", "/", "\\", "\x00", TEMP_PREFIX), entry.stat(follow_symlinks=False), concurrent FileNotFoundError/ENOENT skips, symlink skips, and special-file omission.

- When entry_count reaches max_entries (B), the while condition exits into the else: branch and sets complete = False without ever probing entry B + 1. complete = True is reported only when StopIteration is observed within the budget (0 through B - 1 raw entries).

- InMemoryAdapter.scan_children slices keys with itertools.islice(self._files, max_entries) in insertion order without sorting or materializing the full mapping, sorting only the bounded prefix by (meta.name, meta.ref.file_id) and reporting complete = total <= max_entries.

- Physical-prefix sorting makes no claim of global directory order, eventual complete search coverage across repeated calls, or free sorted offset continuation.

- Full Batch Charging & Useful Prefix Retention (find):

- find passes remaining_budget = max_entries - inspected to scan_fn and charges inspected += batch_inspected immediately after _validate_batch_report, before testing any entry names.

- If max_results is reached mid-batch, inspected still reflects the full raw scan batch, and truncated=True, reason="max_results" is returned whenever more_entries_in_dir or not batch_complete or more_dirs_queued holds.

- If a batch is incomplete (not batch_complete) and max_results was not hit, matches found within the scanned physical prefix are retained in matches and the walk stops immediately after the batch with truncated=True, reason="max_entries".

- Partial-Work Failures, Error Identity & Seam Charging (_scan_work_error, _post_yield_storage_error, scan_children, find):

- Pre-yield failures (entry_count == 0, including open, traversal, fstat, not-a-directory, and initial scandir setup, or the first next(entries) call) propagate as plain StorageError subclasses without ScanFailure wrapping.

- Once entry_count > 0, OSError failures during next(entries), non-ENOENT entry.stat(), or iterator close (scandir_it.__exit__) are wrapped via _scan_work_error in ScanFailure(entry_count, underlying) where underlying is a LocalStorageError with underlying.__cause__ = exc.

- Any StorageError escaping the scan body after entry_count > 0 (such as from _build_metadata or a stat/metadata extension seam) is caught by except StorageError as exc: and wrapped via _post_yield_storage_error(entry_count, exc) into ScanFailure(entry_count, exc), while preserving an existing ScanFailure without double-wrapping.

- At depth == 0, find validates failure.inspected and failure.error, then executes raise error, preserving exact object identity (failure.error) and its attached __cause__.

- Primary vs. Cleanup Error Priority (_release_owned, scan_children):

- parent_fd (when distinct from root_fd) and scan_fd are appended to owned upon acquisition and closed once in finally via self._release_owned(owned) with no close retries.

- When a primary exception is propagating, _release_owned sees sys.exc_info()[0] is not None and suppresses close OSErrors so the primary failure is never masked.

- On the normal return path (primary is None), a close failure in _release_owned raises LocalStorageError(...) from exc; the finally block in scan_children wraps it in ScanFailure(entry_count, cleanup_exc) if entry_count > 0 or re-raises cleanup_exc if entry_count == 0, preventing a return before cleanup succeeds.

- Malformed Reports, Depth-Independent Failure Validation & Skipped Semantics (_validate_batch_report, _validate_failure_inspected, find):

- _validate_batch_report enforces without clamping that items is a tuple, inspected is a non-bool int in 0..remaining, complete is a bool, len(items) <= inspected, and not complete implies inspected == remaining.

- In find's except ScanFailure as failure: handler, both _validate_failure_inspected(failure, remaining_budget) and if not isinstance(error, StorageError): execute before if depth == 0:, ensuring malformed ScanFailure reports at depth > 0 raise StorageError loudly rather than being recorded in skipped.

- When the walk finishes without hitting max_results, max_entries, or max_depth, if skipped: returns FindResult(items=tuple(matches), truncated=True, reason="skipped", inspected=inspected, skipped=tuple(skipped)), ensuring skipped subdirectories never produce a false exhaustive (truncated=False) result.

- Legacy adapters lacking a callable scan_children are rejected before enumeration with ScanUnsupportedError.

### Non-Blocking Observations

- Cause-chain symmetry on ScanFailure (LocalAdapter._scan_work_error / LocalAdapter.scan_children):

- In scan_children, raise self._scan_work_error(...) from exc sets ScanFailure.__cause__ to the raw OSError (exc) while ScanFailure.error.__cause__ is also exc. By contrast, _post_yield_storage_error (raise wrapped from exc) and the finally cleanup path (raise ScanFailure(entry_count, cleanup_exc) from cleanup_exc) set ScanFailure.__cause__ to the wrapped StorageError (ScanFailure.error). Because find unwraps and raises failure.error at depth == 0 (whose __cause__ is exc in all paths), root error identity and cause chains are unaffected. If strict outer __cause__ symmetry on ScanFailure itself is ever desired, ScanFailure.__init__ could set self.__cause__ = error and _scan_work_error call sites could use bare raise self._scan_work_error(...).

### Review Scope & Execution Status

- Execution Status: TESTS_NOT_RUN (independent static review only; no tests were executed and no assumptions are made regarding the separate D037 execution session).

- Omitted-Source Limitations: This review covers only the supplied compact fallback (D036-CODE.txt): the unified production diff across drive_tool/local.py, drive_tool/search.py, and drive_tool/storage.py for candidate e88c9c79fdc27057622d44ba51e008f2e4ea4f4f against base 356a4d8a71d0e57a57e7c82dbfce50be145a0bdb, plus the two unchanged lifetime helpers (_release_owned and _close_owned_fd). Unchanged surrounding production code (such as _traverse_parent_dir, _classify_component_open_error, _build_metadata, and _os_* seams) and the test suite were omitted from the fallback and were not inspected.

STATUS: REVIEWED
