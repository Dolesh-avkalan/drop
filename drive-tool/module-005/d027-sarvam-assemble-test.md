# d027 (Sarvam) — MODULE-005 assembly, tests, mutation check and push

- status: done
- branch pushed: `feature/module-005-local-write` @ `dda193b7a2ee558aa58275e51e843d7d4676dca3`
- repository: https://github.com/Dolesh-avkalan/drive-tool (public)
- implementer output applied: `Dolesh-avkalan/drop`, `drive-tool/module-005/d026-deepseek-implementation.md`
- brief: `Dolesh-avkalan/drive-tool`, `tasks/MODULE-005.md` @ `main`

## Summary

I created the branch from `main`, applied DeepSeek's output exactly (four
`FILE:` blocks as whole files and the two `EDIT drive_tool/local.py:` blocks as
exact line replacements), committed it, ran the full suite on Python 3.11 and
3.12, fixed the two defects the run proved (both in the delivered test file), and
ran the mutation check in a scratch copy. All 199 tests pass on both
interpreters; all five brief mutations are caught.

## Base and commits

- Base: `main` HEAD `2d5c280cb012b6b97cd8c759f7d9114768731eec`. The brief names
  the base as `af42edb` (MODULE-004 merged); `main` had advanced by two
  documentation commits (the brief's own dispatch `1b86059` and a session
  handoff `2d5c280`), so per "create the branch from `main`" the branch was made
  from `2d5c280`, which contains `af42edb`.

| # | Commit | Message |
| --- | --- | --- |
| 1 | `15da7d4516e9191640aa844589f61a6963337139` | Implement MODULE-005 safe local writes (DeepSeek) |
| 2 | `5b5de3fb8552a365dcbb3c4b67aed45773e8ce2f` | Sarvam fixes: construct the test adapter with a read limit large enough to read back a max-size write |
| 3 | `5fcc2251bffb793744d00665a36235bf2365d74a` | Sarvam fixes: correct the parent-dir fsync seam test expectation (published file persists; only the temp name is cleaned up) |
| 4 | `dda193b7a2ee558aa58275e51e843d7d4676dca3` | Add MODULE-005 evidence report |

Commit 1 applies DeepSeek's output exactly:
- `drive_tool/storage.py` — adds `AlreadyExistsError` and `ReadOnlyError`
  (both subclass `StorageError`) and both to `__all__`; the diff against `main`
  is exactly those eight lines.
- `drive_tool/local_write.py` — new, written verbatim.
- `tests/test_local_write.py` — new, written verbatim.
- `drive_tool/local.py` — exactly two edits: the `TEMP_PREFIX = ".drive-tool-tmp-"`
  constant after `PATH_PREFIX = "p/"`, and `or name.startswith(TEMP_PREFIX)` in
  the odd-name filter of `LocalAdapter.list_children` (four added lines total).

No other file was changed. Commits 2 and 3 touch only `tests/test_local_write.py`.

## Interpreters and command

- Python 3.11.2 and Python 3.12.13 (the two Python 3.11+ interpreters present).
- `python3.11 -m unittest discover -s tests -v`
- `python3.12 -m unittest discover -s tests -v`

## Test results

First run (DeepSeek's output exactly as delivered, commit 1): **199 tests,
1 failure, 1 error**, identically on both interpreters (exit 1).

- ERROR `test_write_empty_and_exact_max_write_bytes` — `ReadLimitExceededError:
  file 'p/max.bin' size (10485760 bytes) exceeds max_read_bytes (1048576 bytes)`.
- FAIL `test_seam_dir_fsync_failure_does_not_double_unlink` —
  `AssertionError: Lists differ: ['a.bin'] != []`.

Final run (after commits 2 and 3): **199 tests, OK, exit 0**, on both
interpreters.

| Interpreter | First run | Final run |
| --- | --- | --- |
| Python 3.11.2 | `Ran 199 tests in 1.562s` / `FAILED (failures=1, errors=1)` | `Ran 199 tests in 1.952s` / `OK` |
| Python 3.12.13 | `Ran 199 tests in 1.848s` / `FAILED (failures=1, errors=1)` | `Ran 199 tests in 2.362s` / `OK` |

The 199 tests are 24 new (`tests/test_local_write.py`) plus the 175 pre-existing
tests, which pass unchanged.

Final raw output tail (Python 3.12.13):

```
test_empty_file_size (test_storage.TestStat.test_empty_file_size) ... ok
test_file_stat_values (test_storage.TestStat.test_file_stat_values) ... ok
test_root_stat_values (test_storage.TestStat.test_root_stat_values) ... ok

----------------------------------------------------------------------
Ran 199 tests in 2.362s

OK
```

## Fixes

Both failures were defects in the delivered **test file**, not in the
implementation; the brief's contract is the arbiter and the implementation
follows it. No implementation file was changed, and no test was weakened or
skipped.

1. **`5b5de3f` — adapter read limit.** `setUp` built the adapter with the default
   `max_read_bytes` (1 MiB), but `test_write_empty_and_exact_max_write_bytes`
   writes a file of exactly `DEFAULT_MAX_WRITE_BYTES` (10 MiB) and reads it back
   *through the adapter*, so the read-back tripped the adapter's own read limit.
   The fix constructs the test adapter with
   `max_read_bytes=DEFAULT_MAX_WRITE_BYTES`. No assertion changed; no other test
   in the file depends on the default read limit.

2. **`5fcc225` — parent-dir fsync seam expectation.** The test asserted that
   after a simulated parent-directory `fsync` failure on the `overwrite=False`
   path, `os.listdir(self.root) == []`. Per the brief, that path publishes
   atomically with `link` (the file is already visible), unlinks the temp name,
   then fsyncs the parent; the error-path contract only requires the **temp**
   file to be cleaned up. So the created file correctly persists and there is
   exactly one `unlink`. The `== []` expectation contradicted the brief and the
   test's own `len(w1.unlink_calls) == 1`. The fix changes only that expectation
   to `["a.bin"]` (with a comment); the test still requires the
   `LocalStorageError` (so a skipped parent `fsync` still fails it), still
   requires exactly one `unlink` (so a double/unconditional unlink still fails
   it), and still requires no temp file to remain.

## Mutation check

Each mutation was applied to a scratch copy of the branch (never committed), the
full suite was run on both interpreters, then the mutation was discarded. The
brief lists five mutations; DeepSeek lists no further mutations of its own (it
ships two guards covering brief mutations 3 and 5). All five are caught — no
mutation survives.

| # | Mutation | Failing tests (count) |
| --- | --- | --- |
| M1 | publish with `rename` instead of `link` when `overwrite=False` | `test_concurrent_two_writers_race_overwrite_false`, `test_mutation_guard_fsync_called_on_file_and_dir_fds`, `test_mutation_guard_temp_open_flags_and_mode`, `test_name_validation_all_invalid_classes`, `test_seam_dir_fsync_failure_does_not_double_unlink`, `test_seam_link_failures_eexist_and_eperm_clean_up`, `test_seam_write_handles_short_writes_and_eintr`, `test_write_and_read_back_root_and_nested`, `test_write_empty_and_exact_max_write_bytes`, `test_write_overwrite_false_existing_file`, `test_write_overwrite_false_existing_symlink` (11) |
| M2 | skip the temp-file cleanup on error | `test_concurrent_two_writers_race_overwrite_false`, `test_seam_file_fsync_failure_cleans_up`, `test_seam_link_failures_eexist_and_eperm_clean_up`, `test_seam_rename_failure_cleans_up`, `test_seam_temp_close_failure_before_publish_cleans_up`, `test_seam_write_zero_return_or_midway_oserror_cleans_up`, `test_write_overwrite_false_existing_file`, `test_write_overwrite_false_existing_symlink`, `test_write_overwrite_true_rejects_directory_symlink_fifo` (9) |
| M3 | drop `O_NOFOLLOW` from the temp-file open | `test_mutation_guard_temp_open_flags_and_mode` (1) |
| M4 | drop the `TEMP_PREFIX` filter in `list_children` | `test_list_children_hides_temp_prefix_but_counts_toward_limit` (1) |
| M5 | skip the parent-directory `fsync` (write_bytes and mkdir) | `test_mkdir_create_and_exist_ok_matrix`, `test_mutation_guard_fsync_called_on_file_and_dir_fds`, `test_seam_dir_fsync_failure_does_not_double_unlink` (3) |

Results are identical on Python 3.11.2 and 3.12.13.

## Pushed content verification

The four source files on the branch, by git blob SHA:

| Path | Blob SHA |
| --- | --- |
| `drive_tool/local_write.py` | `c8db41cba625c541af4d860b812f57b28e96656e` |
| `tests/test_local_write.py` | `85e7bf06357c16ebf499294de9b116fb909e07db` |
| `drive_tool/storage.py` | `b9053148af203f1af2d1f7acd558acb56dd48bec` |
| `drive_tool/local.py` | `d66ce2d38bf4d2dd35d2c307db90a8578f2c28a3` |

Evidence report committed on the branch: `docs/evidence/MODULE-005.md`. No
`__pycache__`/`.pyc` file is tracked on the branch.

## Notes and limits

- The brief names the base as `af42edb`; the branch was created from the actual
  `main` HEAD `2d5c280` (which contains `af42edb`), per the instruction to branch
  from `main`.
- DeepSeek's files use a single blank line between top-level definitions; this is
  the implementer's formatting and was applied exactly as delivered.
- I pushed only the branch `feature/module-005-local-write` in
  `Dolesh-avkalan/drive-tool`. No other branch, tag or repository was pushed.
  Independent review (Gemini, d028) and director acceptance remain the gates.
