# d024 (sarvam) — MODULE-004 proof tests: assembly, execution and mutation check

- status: done
- agent: Sarvam
- repository: `Dolesh-avkalan/drive-tool`
- branch: `feature/module-004-bounded-enumeration`
- branch tip before this work: `380613264657e2b035d8841baa1a3ed5b801580b`
- finished: 2026-10-15

## Question

Claude (drive-tool lead): add DeepSeek's d023 proof tests to the MODULE-004
branch, prove they bite, and push. Specifically: check out the branch at tip
`3806132`; add `tests/test_enumeration_proofs.py` exactly as in d023's `FILE`
block; run `python3 -m unittest discover -s tests -v` on Python 3.11 and 3.12;
apply each mutation d023 lists in a scratch copy only (never commit), record
which proof tests fail, and revert; if a new test fails on the real code, fix
only the test in a separate commit; then commit the tests, append a "Proof
tests" section to `docs/evidence/MODULE-004.md`, commit and push.

## Answer

Done. Three commits were pushed to `feature/module-004-bounded-enumeration`.
The proof file passes 6/6 on Python 3.11.2 and 3.12.13 (175 tests total on both
interpreters), every mutation is caught by at least one proof test, and one
fixture defect in the delivered test was fixed in its own commit.

### Commits pushed (only these were pushed)

| # | Commit | Message |
| --- | --- | --- |
| 1 | `d6f8afb76df6369258f3adbb85261403a6f5c974` | Add MODULE-004 proof tests (DeepSeek) |
| 2 | `2bb2c3a7626f6134381776beb68645399111b614` | Sarvam fixes: correct nested-directory path in the fd-leak proof test |
| 3 | `70a7a00bfd51d4701eaeb6314ec75d42e89b57b0` | Document MODULE-004 proof tests and mutation results |

- Commit 1 is based on `3806132` (the branch tip at checkout).
- Commit 2's parent is commit 1; commit 3's parent is commit 2.
- Commit URLs:
  - https://github.com/Dolesh-avkalan/drive-tool/commit/d6f8afb76df6369258f3adbb85261403a6f5c974
  - https://github.com/Dolesh-avkalan/drive-tool/commit/2bb2c3a7626f6134381776beb68645399111b614
  - https://github.com/Dolesh-avkalan/drive-tool/commit/70a7a00bfd51d4701eaeb6314ec75d42e89b57b0

### Final test count and result

| Interpreter | Command | Result |
| --- | --- | --- |
| Python 3.11.2 | `python3.11 -m unittest discover -s tests -v` | **175 tests, OK** |
| Python 3.12.13 | `python3.12 -m unittest discover -s tests -v` | **175 tests, OK** |

169 tests pre-existed; `tests/test_enumeration_proofs.py` adds 6, for 175 total.
All pass on both interpreters. Re-verified against the pushed tree
(`origin/feature/module-004-bounded-enumeration`), not just the working copy.

### The fix (commit 2)

Commit 1 added the d023 file exactly as delivered. On the real code one test
errored on **both** interpreters:

```
test_no_fd_leak_on_repeated_limit_errors_in_nested_directory
drive_tool.storage.NotFoundError: entry 'p/sub/leaf' not found
```

It expected `EnumerationLimitError`, not `NotFoundError`. Cause: the test built
its fixture at `root/p/sub/leaf` but referenced `FileRef("src", "p/sub/leaf")`.
In `LocalAdapter` the mandatory ID prefix is `p/` (`PATH_PREFIX`), so the
file_id `p/sub/leaf` denotes the on-disk path `root/sub/leaf`, not
`root/p/sub/leaf`. Gemini's nit-3 fix explicitly specifies the reference
`FileRef("src", "p/sub/leaf")`, so the reference is correct and the **fixture**
was wrong.

Commit 2 changes only the fixture path to `root/sub/leaf` (two lines), so the
reference resolves and the test lists a genuinely nested directory (both a
`parent_fd` and a `scan_fd` are acquired — exactly what nit 3 requires). No
assertion was weakened and no production file was touched. This is a test-only
fix; the implementation is unchanged.

### Mutation table

Each mutation was applied to a scratch copy of the branch (never committed), the
proof file was run alone, and the mutation was then reverted. "Failing" means
the named proof test failed (or errored) under that mutation. Identical results
on Python 3.11.2 and 3.12.13.

| Mutation (the forbidden shortcut) | Proof test(s) that fail |
| --- | --- |
| M1 move the limit check to after the scan loop (`local.py` `list_children`) | `test_scan_stops_early_on_limit` |
| M2 move entry counting below the odd-name filter (`local.py` `list_children`) | `test_backslash_name_counts_toward_limit_and_is_omitted` |
| M3 stop adding the traversed `parent_fd` to `owned` (`local.py` `list_children`) | `test_no_fd_leak_on_repeated_limit_errors_in_nested_directory` |
| M4a drop `or more_dirs_queued` (`search.py` `find`) | `test_max_results_on_last_entry_with_child_directory_queued`, `test_max_results_on_last_entry_with_sibling_directory_remaining` |
| M4b drop `more_dirs_at_this_level` (`search.py` `find`) | `test_max_results_on_last_entry_with_sibling_directory_remaining` |
| M5 `list_page` always passes `max_entries` (`listing.py`) | `test_list_page_passes_max_entries_only_when_given` |

**No proof gap.** Every mutation is caught by at least one proof test; no proof
test passed under its own mutation. M4a removes the entire `more_dirs_queued`
term, so it necessarily also trips the sibling-directory test; M4b isolates the
`more_dirs_at_this_level` half.

### Notes

- M1 ("check the limit only after the scan loop") is distinct from deleting the
  check: the check is *moved*, so a directory that is under the limit still
  lists normally and only the early-termination test fails.
- The mutation harness is included as `mutate.py` in the companion folder; it
  copies the branch to a scratch directory, applies each mutation, runs
  `tests.test_enumeration_proofs`, and restores the pristine sources.
- The proof file and its exact d023 provenance are recorded in
  `docs/evidence/MODULE-004.md` §8 on the branch.

STATUS: DONE
