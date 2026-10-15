# d030 (sarvam) — MODULE-005 review-nits closure: proof tests, run and mutation check

- role: assembler / verifier (Sarvam)
- repository: `Dolesh-avkalan/drive-tool`
- branch: `feature/module-005-local-write`
- branch tip before this round: `dda193b7a2ee558aa58275e51e843d7d4676dca3`
- inputs read: `Dolesh-avkalan/drop` `main` →
  `drive-tool/module-005/d028-argon-code-review.md` (Gemini: **ACCEPT WITH NITS**, five nits)
  and `drive-tool/module-005/d029-deepseek-proof-tests.md` (DeepSeek: one new test file + two edits)
- interpreters: **Python 3.11.2** and **Python 3.12.13**

## 1. What was done

1. Cloned `Dolesh-avkalan/drive-tool` and checked out `feature/module-005-local-write` at `dda193b` (confirmed tip).
2. Added `tests/test_local_write_proofs.py` exactly as d029's `FILE` block delivers it (209 lines, 5 tests) and applied d029's two `EDIT` blocks to `drive_tool/local_write.py` exactly:
   - `_check_writer_platform_capabilities` now requires `O_NOFOLLOW` and `O_CLOEXEC` in addition to `O_WRONLY`, `O_CREAT`, `O_EXCL` (d028 nit 3, capability half);
   - in `write_bytes`, `tmp_on_disk = False` is set immediately *before* the post-link `unlink` of the temp name (d028 nit 4).
   The `local_write.py` diff is +2 / −2 lines; no other file was changed.
3. Committed as `Close MODULE-005 review nits: proof tests and cleanup order (DeepSeek)`.
4. Ran `python3.11 -m unittest discover -s tests -v` and `python3.12 -m unittest discover -s tests -v` from the repository root.
5. Fixed nothing: the run proved no defect (see §3), so no `Sarvam fixes:` commit was warranted. No test was weakened or skipped.
6. Ran the mutation check in a scratch copy only (§5).
7. Appended a "Review nits" section to `docs/evidence/MODULE-005.md` and pushed the branch.

## 2. Commits pushed to `feature/module-005-local-write`

| # | Commit | Message |
| --- | --- | --- |
| 5 | `bab51174d9dccce3596fb0aa824a47f8f86536d4` | Close MODULE-005 review nits: proof tests and cleanup order (DeepSeek) |
| 6 | `1dcfeefb6787829274a55e0220986c2de5d30d95` | Add MODULE-005 review-nits evidence: proof tests, run and mutation check (Sarvam) |
| 7 | `a65da4e5ba90e362a254698160aa971412b9c18e` | Record the pushed commit ids in MODULE-005 review-nits evidence (Sarvam) |

Parent chain: `dda193b` → `bab5117` → `1dcfeef` → `a65da4e` (branch tip).

Commit 5 changes exactly two paths: `tests/test_local_write_proofs.py` (new) and
`drive_tool/local_write.py` (two hunks). Commits 6 and 7 change only
`docs/evidence/MODULE-005.md`. All three files were verified byte-for-byte
against the pushed tree.

## 3. Final count and result

| Interpreter | Command | Count | Final line | Exit |
| --- | --- | --- | --- | --- |
| Python 3.11.2 | `python3.11 -m unittest discover -s tests -v` | `Ran 204 tests in 1.947s` | `OK` | 0 |
| Python 3.12.13 | `python3.12 -m unittest discover -s tests -v` | `Ran 204 tests in 2.073s` | `OK` | 0 |

204 = the 199 tests of the prior round plus the 5 new proof tests. **Both
interpreters pass, exit 0.** The 5 new proof tests all ran and passed:
`TestNit1IntermediateSymlink.test_intermediate_symlink_in_parts_before_last_refused`,
`TestNit2PublishSeams.test_publish_uses_link_for_no_overwrite_and_rename_for_overwrite`,
`TestNit3TempOpenFlagsAndName.test_temp_open_has_cloexec_and_16_lower_hex_name`,
`TestNit4PostLinkUnlinkFailure.test_post_link_unlink_failure_calls_unlink_once`,
`TestNit5ClosedPrecedenceAndMkdirValidation.test_closed_wrong_source_precedes_closed_and_args_and_mkdir_validation`.

## 4. Fixes

**None.** The run proves no defect, so per the instruction to fix only defects
the run proves, no `Sarvam fixes:` commit was made this round, and no assertion
was weakened or skipped.

## 5. Mutation check (scratch copy only)

Each mutation was applied to a scratch copy of the branch (never committed), the
full suite was run on both interpreters, and the copy was discarded. "Failing"
counts failed/errored tests; results are **identical on Python 3.11.2 and
3.12.13**.

| # | Mutation (applied to a scratch copy) | d029 ref | Failing tests | # failing | Caught? |
| --- | --- | --- | --- | --- | --- |
| M1 | drop `O_NOFOLLOW` from the intermediate-traversal dir open (`local.py`, `_traverse_parent_dir` `dir_flags`) | nit 1 | `test_intermediate_symlink_in_parts_before_last_refused` (new), `test_final_and_intermediate_symlinks_rejected_and_omitted_from_listing`, `test_dir_swap_before_component_open_read_traversal_rejected`, `test_dir_swap_before_component_open_stat_traversal_rejected`, `test_deterministic_descriptor_accounting_across_success_and_failures`, `test_closed_wrong_source_precedes_closed_and_args_and_mkdir_validation` | 8 | yes |
| M2 | accept a symlink strictly inside `parts[:-1]` (drop `O_NOFOLLOW` **and** the explicit `S_ISLNK` rejection) | nit 1 | same six tests as M1 | 8 | yes |
| M3 | check-then-rename instead of atomic `link` for `overwrite=False` (`local_write.py`, `write_bytes`) | nit 2 / extra | `test_publish_uses_link_for_no_overwrite_and_rename_for_overwrite` (new), `test_temp_open_has_cloexec_and_16_lower_hex_name` (new), `test_mutation_guard_temp_open_flags_and_mode`, `test_mutation_guard_fsync_called_on_file_and_dir_fds`, `test_seam_link_failures_eexist_and_eperm_clean_up`, `test_seam_write_handles_short_writes_and_eintr`, `test_write_and_read_back_root_and_nested`, `test_write_empty_and_exact_max_write_bytes`, `test_name_validation_all_invalid_classes`, `test_concurrent_two_writers_race_overwrite_false` | 10 | yes |
| M4 | drop `O_CLOEXEC` from the temp-file open (`local_write.py`, `_create_temp_file`) | nit 3 / extra | `test_temp_open_has_cloexec_and_16_lower_hex_name` (new) | 1 | yes |
| M5 | use 8 hex characters in the temp name (`secrets.token_hex(4)`) | nit 3 / extra | `test_temp_open_has_cloexec_and_16_lower_hex_name` (new) | 1 | yes |
| M6 | move `tmp_on_disk = False` back after the post-link `unlink` | nit 4 / extra | `test_post_link_unlink_failure_calls_unlink_once` (new) | 1 | yes |
| M7 | check closed state before source mismatch (`local.py`, `_check_source_and_state`) | nit 5 | `test_closed_wrong_source_precedes_closed_and_args_and_mkdir_validation` (new), `test_source_mismatch_precedence_across_all_methods_and_states`, `test_check_order_source_closed_validation` | 10 | yes |
| M8 | let `mkdir` validate the name before checking the source (`local_write.py`, `mkdir`) | nit 5 / extra | `test_closed_wrong_source_precedes_closed_and_args_and_mkdir_validation` (new) | 1 | yes |

Coverage of the required mutations:

- **d029's mutations** — nit 1 → M1, M2; nit 2 → M3; nit 3 → M4, M5; nit 4 → M6; nit 5 → M7, M8.
- **the five additional mutations required by the task** — check-then-rename for
  `overwrite=False` → M3; drop `O_CLOEXEC` from the temp open → M4; 8 hex
  characters in the temp name → M5; move `tmp_on_disk = False` back after the
  unlink → M6; let `mkdir` validate the name before checking the source → M8.

**Every mutation is caught by at least one test; no mutation survives, so there
is no mutation gap to report.**

Notes:

- M1 and M2 are the two forms of d029's nit-1 mutation ("drop `O_NOFOLLOW`
  during intermediate traversal **or** accept a symlink strictly inside
  `parts[:-1]`"). Both are caught by the new proof test and by the pre-existing
  containment tests. M2 is behaviourally equivalent to M1 for this scenario
  because, once `O_NOFOLLOW` is gone, the intermediate `open` follows the
  symlink and `fstat` already reports the target directory.
- M3 is now caught **deterministically** by the new `TestNit2` proof test, which
  records the publish seams and requires exactly one `_os_link` call with
  `follow_symlinks=False` and zero `_os_rename` calls when `overwrite=False` —
  closing d028 nit 2's concern that check-then-rename was only caught indirectly
  through the race test (the race test fails as well).
- M4 and M5 are caught **only** by the new `TestNit3` proof test — closing d028
  nit 3's observation that neither `O_CLOEXEC` nor the 16-hex suffix length was
  asserted anywhere.
- M6 is caught by the new `TestNit4` proof test (exactly one post-link unlink).
- M7 and M8 are caught by the new `TestNit5` proof test; M7 also fails the
  pre-existing precedence tests, while M8 shows the new `mkdir`-precedence
  assertion is the only test that binds that ordering.

## 6. Push method (why the pushed SHAs differ from the local ones)

The sandbox holds no GitHub push credentials (`git push` fails with *could not
read Username*; `gh` is not logged in), so the three commits were pushed through
the GitHub Git Data API. The API stores the commit message **without a trailing
newline**, so each pushed commit's SHA differs from the byte-identical local
commit. The SHAs reported in §2 are the ones that are actually on
`feature/module-005-local-write`; all pushed file contents were verified
byte-for-byte against the local working tree.

## 7. Pushes made

- `Dolesh-avkalan/drive-tool`, branch `feature/module-005-local-write`: commits
  `bab51174d9dccce3596fb0aa824a47f8f86536d4`,
  `1dcfeefb6787829274a55e0220986c2de5d30d95`,
  `a65da4e5ba90e362a254698160aa971412b9c18e`.
- `Dolesh-avkalan/drop`, branch `main`: this relay commit (`relay: d030`).

No other pushes were made.

## 8. Files in this drop folder

- `test_local_write_proofs.py` — the new proof-test file added to the branch (exact bytes).
- `MODULE-005.md` — the updated evidence report, including the new "Review nits" section.
- `mutate.py` — the mutation harness used for the scratch-copy check.
- `mutation_results.json` — per-mutation results on Python 3.12.13.
- `mutation_results_py311.json` — per-mutation results on Python 3.11.2.
- `py311.log` — full `python3.11 -m unittest discover -s tests -v` output.
- `py312.log` — full `python3.12 -m unittest discover -s tests -v` output.
