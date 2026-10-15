# MODULE-005 Evidence Report — Assembly, Execution, Mutation Check and Provenance (Sarvam)

This report records the assembly, test execution, defect fixes and mutation check
of MODULE-005 (safe local writes: atomic, no-overwrite save and mkdir) as
performed by the assembler (Sarvam). It is separate from the implementer's own
output (`Dolesh-avkalan/drop`, `drive-tool/module-005/d026-deepseek-implementation.md`).

## 1. Provenance

| Role | Detail |
| --- | --- |
| Implementer | DeepSeek (deepthink on, search off) |
| Implementer output | `Dolesh-avkalan/drop`, branch `main`, `drive-tool/module-005/d026-deepseek-implementation.md` (status: `GENERATED, TESTS_NOT_RUN`) |
| Brief | `Dolesh-avkalan/drive-tool`, `tasks/MODULE-005.md` @ `main` |
| Base commit | `2d5c280cb012b6b97cd8c759f7d9114768731eec` ("Session: Claude-to-Codex director handoff (MODULE-005 chain in progress)") |
| Branch | `feature/module-005-local-write` (created from `main`) |
| Assembler | Sarvam |

The brief text names the base as "main at `af42edb` (MODULE-004 merged)". `main`
had advanced by two documentation commits before this assembly — the brief's own
dispatch (`1b86059`, "MODULE-005 brief …") and a session handoff (`2d5c280`) —
so, per the instruction to branch "from `main`", the branch was created from the
actual `main` HEAD `2d5c280`, which contains `af42edb`.

The implementer delivered every required block in the brief's format — four
`FILE:` blocks (`drive_tool/storage.py`, `drive_tool/local_write.py`,
`tests/test_local_write.py`) and two `EDIT drive_tool/local.py:` blocks (each
giving the exact old lines and exact new lines) — with no ellipses or
placeholders, so assembly proceeded.

## 2. Commits on `feature/module-005-local-write`

| # | Commit | Message |
| --- | --- | --- |
| 1 | `15da7d4516e9191640aa844589f61a6963337139` | Implement MODULE-005 safe local writes (DeepSeek) |
| 2 | `5b5de3fb8552a365dcbb3c4b67aed45773e8ce2f` | Sarvam fixes: construct the test adapter with a read limit large enough to read back a max-size write |
| 3 | `5fcc2251bffb793744d00665a36235bf2365d74a` | Sarvam fixes: correct the parent-dir fsync seam test expectation (published file persists; only the temp name is cleaned up) |
| 4 | this commit | Add MODULE-005 evidence report (this file) |

Parent of commit 1 is the base `2d5c280`.

Commit 1 applies DeepSeek's output exactly:

- full files written: `drive_tool/storage.py` (adds `AlreadyExistsError` and
  `ReadOnlyError`, both subclassing `StorageError`, and both added to `__all__`;
  the diff against `main` is those eight lines and nothing else),
  `drive_tool/local_write.py` (new), `tests/test_local_write.py` (new);
- two whole-line edits in `drive_tool/local.py`: the `TEMP_PREFIX = ".drive-tool-tmp-"`
  constant after `PATH_PREFIX = "p/"`, and `or name.startswith(TEMP_PREFIX)` added
  to the odd-name filter in `LocalAdapter.list_children`. The `local.py` diff is
  four added lines and nothing else.

No other file was changed. Commits 2 and 3 touch only `tests/test_local_write.py`.

## 3. Execution environment

- Platform: Debian GNU/Linux 12 (bookworm), x86_64, non-root uid 1000.
- Interpreter A: **Python 3.11.2**
- Interpreter B: **Python 3.12.13**
- Command (both interpreters, run from the repository root):

  ```
  python3.11 -m unittest discover -s tests -v
  python3.12 -m unittest discover -s tests -v
  ```

These are the two Python 3.11+ interpreters present in the environment.

## 4. Test results

### 4.1 First run (DeepSeek's output exactly as delivered, commit 1)

Both interpreters failed identically: **199 tests, 1 failure, 1 error**.

| Interpreter | Count | Final line | Exit |
| --- | --- | --- | --- |
| Python 3.11.2 | `Ran 199 tests in 1.562s` | `FAILED (failures=1, errors=1)` | 1 |
| Python 3.12.13 | `Ran 199 tests in 1.848s` | `FAILED (failures=1, errors=1)` | 1 |

- ERROR `test_write_empty_and_exact_max_write_bytes`
  (`TestWriteHappyPaths`): `ReadLimitExceededError: file 'p/max.bin' size
  (10485760 bytes) exceeds max_read_bytes (1048576 bytes)`.
- FAIL `test_seam_dir_fsync_failure_does_not_double_unlink` (`TestSeams`):
  `AssertionError: Lists differ: ['a.bin'] != []`.

Raw output tail (Python 3.12.13, first run):

```
First list contains 1 additional elements.
First extra element 0:
'a.bin'

- ['a.bin']
+ []

----------------------------------------------------------------------
Ran 199 tests in 1.848s

FAILED (failures=1, errors=1)
```

### 4.2 Final run (after commits 2 and 3)

Both interpreters pass: **199 tests, OK, exit 0**.

| Interpreter | Command | Count | Final line | Exit |
| --- | --- | --- | --- | --- |
| Python 3.11.2 | `python3.11 -m unittest discover -s tests -v` | `Ran 199 tests in 1.952s` | `OK` | 0 |
| Python 3.12.13 | `python3.12 -m unittest discover -s tests -v` | `Ran 199 tests in 2.362s` | `OK` | 0 |

The 199 tests comprise 24 new tests for this module (`tests/test_local_write.py`)
plus the 175 pre-existing tests, which pass unchanged:

| Test module | Tests |
| --- | --- |
| `test_local_write.py` (new) | 24 |
| `test_enumeration.py` | 15 |
| `test_enumeration_proofs.py` | 6 |
| `test_listing.py` | 35 |
| `test_local.py` | 53 |
| `test_readonly_core.py` | 16 |
| `test_search.py` | 14 |
| `test_storage.py` | 36 |
| **Total** | **199** |

Raw output tail (Python 3.12.13, final run):

```
test_empty_file_size (test_storage.TestStat.test_empty_file_size) ... ok
test_file_stat_values (test_storage.TestStat.test_file_stat_values) ... ok
test_root_stat_values (test_storage.TestStat.test_root_stat_values) ... ok

----------------------------------------------------------------------
Ran 199 tests in 2.362s

OK
```

Raw output tail (Python 3.11.2, final run):

```
test_empty_file_size (test_storage.TestStat.test_empty_file_size) ... ok
test_file_stat_values (test_storage.TestStat.test_file_stat_values) ... ok
test_root_stat_values (test_storage.TestStat.test_root_stat_values) ... ok

----------------------------------------------------------------------
Ran 199 tests in 1.952s

OK
```

## 5. Fixes

Both failures were defects in the delivered **test file**, not in the
implementation. In each case the brief is the arbiter and the implementation
follows it; no implementation file was changed and no assertion was weakened or
skipped.

### Fix 1 — commit `5b5de3f`

`BaseLocalWriteTest.setUp` built the adapter with the default
`max_read_bytes` (1,048,576), but `test_write_empty_and_exact_max_write_bytes`
writes a file of exactly `DEFAULT_MAX_WRITE_BYTES` (10,485,760 bytes) and reads
it back **through the adapter**. The read-back therefore tripped the adapter's
own 1 MiB read limit — a mismatch between the fixture's read limit and the write
size, unrelated to the write path under test.

The fix constructs the test adapter with `max_read_bytes=DEFAULT_MAX_WRITE_BYTES`
so a max-size write can be read back. This changes no assertion and no other
test in the file depends on the default read limit (the only `read_bytes` calls
in `tests/test_local_write.py` read back files written by the same test).

### Fix 2 — commit `5fcc225`

`test_seam_dir_fsync_failure_does_not_double_unlink` asserted, for the
`overwrite=False` case, that after a simulated parent-directory `fsync` failure
`os.listdir(self.root) == []`. But the brief's contract for this path is: publish
atomically with `link`, then `unlink` the temp name, then `fsync` the parent;
and on any failure the error path must "unlink the **temp file** … never leave a
temp file behind". Once `link` has returned, the created file is already
published and visible; a later parent-`fsync` failure does not retract it. The
implementation therefore (correctly, per the brief) leaves `a.bin` in place and
leaves no temp file — exactly one `unlink` call. The test's `== []` expectation
contradicted this and was inconsistent with its own `len(w1.unlink_calls) == 1`
assertion (a rollback of the published file would have made it a second
unlink).

The fix changes only that one expectation to `["a.bin"]` and adds a comment
explaining why. The test still fully exercises its purpose: it still requires the
`LocalStorageError` (so a skipped parent `fsync` — mutation M5 — still fails it),
still requires exactly one `unlink` (so an unconditional/double unlink still
fails it), and still requires no temp file to remain. The companion
`overwrite=True` half of the same test is unchanged and still passes.

## 6. Mutation check

Each mutation was applied to a scratch copy of the branch (never committed), the
full suite was run on both interpreters, and the mutation was then discarded.
"Failing" means the named test failed or errored under that mutation. The brief
lists five mutations; DeepSeek's output lists no further mutations of its own (it
ships two dedicated guards, `test_mutation_guard_temp_open_flags_and_mode` and
`test_mutation_guard_fsync_called_on_file_and_dir_fds`, which cover brief
mutations 3 and 5). All five were run.

| # | Mutation (applied to a scratch copy) | Failing tests | Caught? |
| --- | --- | --- | --- |
| M1 | publish with `rename` instead of `link` when `overwrite=False` (`local_write.py` `write_bytes`) | `test_concurrent_two_writers_race_overwrite_false`, `test_mutation_guard_fsync_called_on_file_and_dir_fds`, `test_mutation_guard_temp_open_flags_and_mode`, `test_name_validation_all_invalid_classes`, `test_seam_dir_fsync_failure_does_not_double_unlink`, `test_seam_link_failures_eexist_and_eperm_clean_up`, `test_seam_write_handles_short_writes_and_eintr`, `test_write_and_read_back_root_and_nested`, `test_write_empty_and_exact_max_write_bytes`, `test_write_overwrite_false_existing_file`, `test_write_overwrite_false_existing_symlink` (11) | yes |
| M2 | skip the temp-file cleanup on error (`local_write.py` `write_bytes` error path) | `test_concurrent_two_writers_race_overwrite_false`, `test_seam_file_fsync_failure_cleans_up`, `test_seam_link_failures_eexist_and_eperm_clean_up`, `test_seam_rename_failure_cleans_up`, `test_seam_temp_close_failure_before_publish_cleans_up`, `test_seam_write_zero_return_or_midway_oserror_cleans_up`, `test_write_overwrite_false_existing_file`, `test_write_overwrite_false_existing_symlink`, `test_write_overwrite_true_rejects_directory_symlink_fifo` (9) | yes |
| M3 | drop `O_NOFOLLOW` from the temp-file open (`local_write.py` `_create_temp_file`) | `test_mutation_guard_temp_open_flags_and_mode` (1) | yes |
| M4 | drop the `TEMP_PREFIX` filter in `list_children` (`local.py`) | `test_list_children_hides_temp_prefix_but_counts_toward_limit` (1) | yes |
| M5 | skip the parent-directory `fsync` (`local_write.py` `write_bytes` and `mkdir`) | `test_mkdir_create_and_exist_ok_matrix`, `test_mutation_guard_fsync_called_on_file_and_dir_fds`, `test_seam_dir_fsync_failure_does_not_double_unlink` (3) | yes |

Every mutation is caught by at least one test; **no mutation survives**, so there
is no mutation gap to report. Results are identical on Python 3.11.2 and 3.12.13.

Notes on the caught failures:

- M1 breaks the whole `overwrite=False` publish path (after `rename`, the temp
  name no longer exists, so the following `unlink` raises), which is why it trips
  many tests in addition to the three that target the create-only semantics
  directly.
- M2 leaves the temp file behind on error paths, tripping every test that asserts
  the directory is empty after a simulated failure, plus the create-only tests.
- M5 is caught by the fsync guard, by the `mkdir` guard, and by the dir-fsync
  seam test (with the parent `fsync` skipped, no `LocalStorageError` is raised,
  so `assertRaises` fails — the fix in commit 3 does not blunt this).

## 7. Verification of what was pushed

The four source files committed on this branch were read from the same working
tree the suite ran against, and their git blob hashes are:

| Path | Blob SHA |
| --- | --- |
| `drive_tool/local_write.py` | `c8db41cba625c541af4d860b812f57b28e96656e` |
| `tests/test_local_write.py` | `85e7bf06357c16ebf499294de9b116fb909e07db` |
| `drive_tool/storage.py` | `b9053148af203f1af2d1f7acd558acb56dd48bec` |
| `drive_tool/local.py` | `d66ce2d38bf4d2dd35d2c307db90a8578f2c28a3` |

No `__pycache__`/`.pyc` file is tracked on the branch.

## 8. Notes and limits

- The brief names the base as `af42edb`; `main` had advanced to `2d5c280` before
  assembly, so the branch was created from the actual `main` HEAD `2d5c280`
  (which contains `af42edb`), per the instruction to branch "from `main`".
- DeepSeek's delivered files use a single blank line between top-level
  definitions (the repository's older files use two). This is cosmetic, part of
  the implementer's output, and was applied exactly as delivered rather than
  reformatted.
- The brief documents that a crash between the publish steps can leave a stale
  temp file, and that cleanup of stale temp files is out of scope; hard links,
  bind mounts and adversarial root provisioning remain operator responsibilities.
- Independent code review (Gemini, d028) and independent director execution,
  mutation check and adversarial probes at the pushed commit remain the
  acceptance gates, per the brief. This report claims only what was actually
  executed here.

## 9. Review nits (d028 closure) — proof tests and cleanup order

Gemini's independent review (d028) accepted MODULE-005 with five non-blocking
nits. DeepSeek's follow-up (d029) delivered one new test file and two whole-line
edits to `drive_tool/local_write.py`. This section records the assembler's
execution of that round: the commit, the run on both interpreters, and the
mutation check of the mutations d029 lists plus the five additional mutations
named in the task.

### 9.1 Commits

| # | Commit | Message |
| --- | --- | --- |
| 5 | `bab51174d9dccce3596fb0aa824a47f8f86536d4` | Close MODULE-005 review nits: proof tests and cleanup order (DeepSeek) |
| 6 | `1dcfeefb6787829274a55e0220986c2de5d30d95` | Add MODULE-005 review-nits evidence: proof tests, run and mutation check (Sarvam) |
| 7 | this commit | Record the pushed commit ids in MODULE-005 review-nits evidence (Sarvam) |

Parent of commit 5 is commit 4 (`dda193b`, the previous tip of this branch);
commit 6's parent is commit 5, and commit 7's parent is commit 6.

Commit 5 and commit 6 were pushed through the GitHub Git Data API (the sandbox
holds no push credentials). The API stores the commit message without a trailing
newline, so the pushed SHAs differ from the byte-identical local commits; the
SHAs above are the ones that are actually on the branch. All three files were
verified byte-for-byte against the pushed tree.

Commit 5 changes exactly two paths:

- `tests/test_local_write_proofs.py` (new, 209 lines, 5 tests) — added exactly
  as DeepSeek delivered it in d029's `FILE` block.
- `drive_tool/local_write.py` — the two `EDIT` blocks from d029, applied exactly:
  1. `_check_writer_platform_capabilities` now requires `O_NOFOLLOW` and
     `O_CLOEXEC` in addition to `O_WRONLY`, `O_CREAT`, `O_EXCL` (d028 nit 3,
     capability half);
  2. in `write_bytes`, `tmp_on_disk = False` is set immediately *before* the
     post-link `unlink` of the temp name (d028 nit 4).

No other file was changed. The two `local_write.py` hunks are +2/-2 lines.

The new file's five tests, one per d028 nit:

| Test | d028 nit |
| --- | --- |
| `TestNit1IntermediateSymlink.test_intermediate_symlink_in_parts_before_last_refused` | 1 |
| `TestNit2PublishSeams.test_publish_uses_link_for_no_overwrite_and_rename_for_overwrite` | 2 |
| `TestNit3TempOpenFlagsAndName.test_temp_open_has_cloexec_and_16_lower_hex_name` | 3 |
| `TestNit4PostLinkUnlinkFailure.test_post_link_unlink_failure_calls_unlink_once` | 4 |
| `TestNit5ClosedPrecedenceAndMkdirValidation.test_closed_wrong_source_precedes_closed_and_args_and_mkdir_validation` | 5 |

### 9.2 Interpreters and result

- Interpreter A: **Python 3.11.2**
- Interpreter B: **Python 3.12.13**
- Command (both, from the repository root):

  ```
  python3.11 -m unittest discover -s tests -v
  python3.12 -m unittest discover -s tests -v
  ```

| Interpreter | Count | Final line | Exit |
| --- | --- | --- | --- |
| Python 3.11.2 | `Ran 204 tests in 1.947s` | `OK` | 0 |
| Python 3.12.13 | `Ran 204 tests in 2.073s` | `OK` | 0 |

204 = the 199 tests of the prior round plus the 5 new proof tests. Both
interpreters pass, so **the run proves no defect**. Per the instruction to fix
only defects the run proves, no `Sarvam fixes:` commit was made this round, and
no test was weakened or skipped.

### 9.3 Mutation check

Each mutation was applied to a scratch copy of the branch (never committed), the
full suite was run on both interpreters, and the copy was discarded. "Failing"
means the named test failed or errored. Results are identical on Python 3.11.2
and 3.12.13.

| # | Mutation (applied to a scratch copy) | d029 ref | Failing tests | Caught? |
| --- | --- | --- | --- | --- |
| M1 | drop `O_NOFOLLOW` from the intermediate-traversal dir open (`local.py`, `_traverse_parent_dir` `dir_flags`) | nit 1 | `test_intermediate_symlink_in_parts_before_last_refused` (new), `test_final_and_intermediate_symlinks_rejected_and_omitted_from_listing`, `test_dir_swap_before_component_open_read_traversal_rejected`, `test_dir_swap_before_component_open_stat_traversal_rejected`, `test_deterministic_descriptor_accounting_across_success_and_failures`, `test_closed_wrong_source_precedes_closed_and_args_and_mkdir_validation` (8) | yes |
| M2 | accept a symlink strictly inside `parts[:-1]` (drop `O_NOFOLLOW` **and** the explicit `S_ISLNK` rejection) | nit 1 | same six tests as M1 (8) | yes |
| M3 | check-then-rename instead of atomic `link` for `overwrite=False` (`local_write.py`, `write_bytes`) | nit 2 / extra | `test_publish_uses_link_for_no_overwrite_and_rename_for_overwrite` (new), `test_temp_open_has_cloexec_and_16_lower_hex_name` (new), `test_mutation_guard_temp_open_flags_and_mode`, `test_mutation_guard_fsync_called_on_file_and_dir_fds`, `test_seam_link_failures_eexist_and_eperm_clean_up`, `test_seam_write_handles_short_writes_and_eintr`, `test_write_and_read_back_root_and_nested`, `test_write_empty_and_exact_max_write_bytes`, `test_name_validation_all_invalid_classes`, `test_concurrent_two_writers_race_overwrite_false` (10) | yes |
| M4 | drop `O_CLOEXEC` from the temp-file open (`local_write.py`, `_create_temp_file`) | nit 3 / extra | `test_temp_open_has_cloexec_and_16_lower_hex_name` (new) (1) | yes |
| M5 | use 8 hex characters in the temp name (`secrets.token_hex(4)`) | nit 3 / extra | `test_temp_open_has_cloexec_and_16_lower_hex_name` (new) (1) | yes |
| M6 | move `tmp_on_disk = False` back after the post-link `unlink` | nit 4 / extra | `test_post_link_unlink_failure_calls_unlink_once` (new) (1) | yes |
| M7 | check closed state before source mismatch (`local.py`, `_check_source_and_state`) | nit 5 | `test_closed_wrong_source_precedes_closed_and_args_and_mkdir_validation` (new), `test_source_mismatch_precedence_across_all_methods_and_states`, `test_check_order_source_closed_validation` (10) | yes |
| M8 | let `mkdir` validate the name before checking the source (`local_write.py`, `mkdir`) | nit 5 / extra | `test_closed_wrong_source_precedes_closed_and_args_and_mkdir_validation` (new) (1) | yes |

Every mutation is caught by at least one test; **no mutation survives**, so there
is no mutation gap to report.

Notes on the caught failures:

- M1 and M2 are the two forms of d029's nit-1 mutation ("drop `O_NOFOLLOW` during
  intermediate traversal **or** accept a symlink strictly inside `parts[:-1]`").
  Both are caught by the new proof test and by the pre-existing containment
  tests. M2 is behaviourally equivalent to M1 for this scenario because, once
  `O_NOFOLLOW` is gone, the intermediate `open` follows the symlink and `fstat`
  already reports the target directory.
- M3 (check-then-rename) is now caught **deterministically** by the new
  `TestNit2` proof test, which records the publish seams and requires exactly one
  `_os_link` call with `follow_symlinks=False` and zero `_os_rename` calls when
  `overwrite=False`. This closes d028 nit 2's concern that check-then-rename was
  only caught indirectly through the race test (the race test fails as well).
- M4 and M5 are caught **only** by the new `TestNit3` proof test, which closes
  d028 nit 3's observation that neither `O_CLOEXEC` nor the 16-hex suffix length
  was asserted anywhere.
- M6 is caught by the new `TestNit4` proof test, which requires exactly one
  post-link `unlink` call.
- M7 and M8 are caught by the new `TestNit5` proof test; M7 also fails the
  pre-existing precedence tests, while M8 shows that the new `mkdir`-precedence
  assertion is the only test that binds that ordering.

### 9.4 Blob hashes of the changed files

| Path | Blob SHA |
| --- | --- |
| `tests/test_local_write_proofs.py` | `6abf5f1b4bceae58877cb29182f685f71cd4343c` |
| `drive_tool/local_write.py` | `9824052f349e94f87ee65215ab96e979b4d2a021` |
