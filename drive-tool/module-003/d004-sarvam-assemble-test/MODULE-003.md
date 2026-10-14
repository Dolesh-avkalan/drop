# MODULE-003 Evidence Report — Assembly, Execution and Provenance (Sarvam)

This report records the assembly, test execution and provenance of MODULE-003
(bounded read-only local adapter) as performed by the assembler (Sarvam). It is
written by Sarvam and is separate from the implementer's own evidence file
(`docs/evidence/MODULE-003-GEMINI.md`).

## 1. Provenance

| Role | Detail |
| --- | --- |
| Implementer | Gemini 4 Argon (Gemini web chatbot), thinking: high |
| Implementer output | `Dolesh-avkalan/drop`, branch `main`, `drive-tool/module-003/d001-argon-generate.md` (status: `GENERATED`, `TESTS_NOT_RUN`) |
| Brief | `Dolesh-avkalan/drive-tool`, `tasks/MODULE-003.md` @ `b5424513796834fc8c03a56bee7b0f0f7abc1f74` |
| Base commit | `194d4ad57de6dd895c6eaaf7faf4d08583eab02b` (MODULE-001, **not** `main`) |
| Branch | `feature/module-003-local-readonly` |
| Assembler | Sarvam |

The implementer delivered all three required files in full (no ellipses, no
truncation, no `BLOCKED`/`FAILED` status), so assembly proceeded.

## 2. Commits on `feature/module-003-local-readonly`

1. **Implement MODULE-003 bounded local read-only adapter from Gemini** —
   adds `drive_tool/local.py`, `tests/test_local.py`,
   `docs/evidence/MODULE-003-GEMINI.md` exactly as delivered by the
   implementer (byte-for-byte). No existing MODULE-001 file was changed.
2. **Sarvam fixes for MODULE-003** — minimal fixes to `drive_tool/local.py`
   only (see §6). Does not touch the implementer's commit, tests, or MODULE-001.
3. **Add MODULE-003 evidence report** — this file.

## 3. Execution environment

- Platform: `Linux 4.19.0-gvisor` (gVisor sandbox); `/scratch` and `/tmp` are
  `9p` (`v9fs`) mounts; `/` is `overlayfs`.
- Interpreter A: **Python 3.11.2**
- Interpreter B: **Python 3.12.13**
- Command (both interpreters, run from the repository root):

  ```
  python3.11 -m unittest discover -s tests -v
  python3.12 -m unittest discover -s tests -v
  ```

## 4. Test results

### 4.1 As delivered by the implementer (commit 1)

| Interpreter | Command | Count | Final line |
| --- | --- | --- | --- |
| Python 3.11.2 | `python3.11 -m unittest discover -s tests -v` | `Ran 67 tests in 0.320s` | `FAILED (failures=8, errors=1)` |
| Python 3.12.13 | `python3.12 -m unittest discover -s tests -v` | `Ran 67 tests in 0.356s` | `FAILED (failures=8, errors=1)` |

The nine non-passing results were:

1. `ERROR test_final_and_intermediate_symlinks_rejected_and_omitted_from_listing (sym_id='p/sym_broken')`
   — `NotFoundError: entry 'p/sym_broken' not found` where `UnsafePathError` was expected.
2. `FAIL test_symlink_root_and_symlink_ancestor_rejected` — `UnsafePathError not raised`.
3. `FAIL test_final_and_intermediate_symlinks_... (sym_id='p/sym_outside_dir')` — `UnsafePathError not raised`.
4. `FAIL test_final_and_intermediate_symlinks_... (sym_id='p/real_dir/sym_nested_dir')` — `UnsafePathError not raised`.
5. `FAIL test_final_and_intermediate_symlinks_... (traversal_id='p/sym_outside_dir/secret.txt')` — `UnsafePathError not raised`.
6. `FAIL test_final_and_intermediate_symlinks_... (traversal_id='p/sym_outside_dir/sub/deep.txt')` — `UnsafePathError not raised`.
7. `FAIL test_final_and_intermediate_symlinks_... (traversal_id='p/real_dir/sym_nested_dir/deep.txt')` — `UnsafePathError not raised`.
8. `FAIL test_deterministic_descriptor_accounting_across_success_and_failures` — `UnsafePathError not raised`.
9. `FAIL test_linux_proc_self_fd_bounded_count` — `AssertionError: 30 != 5`.

### 4.2 After the Sarvam fixes (commit 2)

| Interpreter | Command | Count | Final line |
| --- | --- | --- | --- |
| Python 3.11.2 | `python3.11 -m unittest discover -s tests -v` | `Ran 67 tests in 0.312s` | `OK` |
| Python 3.12.13 | `python3.12 -m unittest discover -s tests -v` | `Ran 67 tests in 0.383s` | `OK` |

All 67 tests pass on both interpreters after the fixes. No test was modified,
skipped, or deleted.

## 5. Root-cause analysis of the as-delivered failures

The nine results fall into two independent causes.

### 5.1 Containment failures on this platform (eight results: items 1–8)

The adapter detects symbolic links by opening path components with
`O_NOFOLLOW | O_DIRECTORY`. On a conformant Linux kernel that open fails with
`ELOOP` when the final component is a symlink, which the code maps to
`UnsafePathError`. **The gVisor sandbox used here does not enforce `O_NOFOLLOW`
when it is combined with `O_DIRECTORY`**, so the open succeeds and follows the
link. Demonstrated directly:

```
$ python3.11 -c "..."
flags O_NOFOLLOW set: True
open SUCCEEDED (symlink followed!). fd= 4 -> readdir: ['sub']
lstat islink: True
```

That is, `os.open(symlink_to_dir, O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_NONBLOCK, dir_fd=...)`
returned a descriptor for the link *target*. Because the containment code relied
on the kernel to reject the open, the symlink was traversed and no
`UnsafePathError` was raised (items 2–8). For the broken symlink (item 1) the
open returned `ENOENT`, which the error classifier maps to `NotFoundError`
before it ever inspects for a symlink.

This is a platform non-conformance, not an implementer logic error: on a kernel
that honours `O_NOFOLLOW`, the implementer's approach passes these same tests.

### 5.2 A genuine descriptor leak (one result: item 9)

`test_linux_proc_self_fd_bounded_count` asserts that after a 25-iteration loop
of `stat` / `list_children` / `read_bytes` the process holds exactly one more
descriptor than baseline (`baseline_fds + 1`). It observed `30 != 5`, i.e.
`5 + 25`: exactly one descriptor leaked per iteration.

The leak is in `list_children`. The code opened a directory descriptor
`scan_fd` and relied on the `os.scandir(scan_fd)` context manager to close it
(the source comment claimed `closedir()` closes `scan_fd` automatically). That
assumption is wrong: **CPython duplicates the descriptor passed to
`os.scandir`**. In `Modules/posixmodule.c` (CPython 3.11.9 and 3.12.3) the
scandir iterator does `fd = _Py_dup(iterator->path.fd); iterator->dirp =
fdopendir(fd);`, so the iterator closes the *duplicate* and leaves the caller's
descriptor open. This is universal CPython behaviour, not specific to this
sandbox, so `list_children` leaked one descriptor on every call on any platform.

## 6. Fixes applied (commit 2 — `Sarvam fixes for MODULE-003`)

All changes are in `drive_tool/local.py` only. No test, no MODULE-001 file, and
no part of the implementer's commit was modified.

1. **`list_children` — close the scan descriptor explicitly (fixes §5.2).**
   The `with scandir_it` block was wrapped in `try/finally` with
   `self._os_close(scan_fd)` in the `finally`, so the descriptor the module
   opened is always released (including on a failed listing). The misleading
   comment was replaced with an accurate one.

2. **Explicit no-follow guard before directory opens (fixes §5.1).**
   Before opening a path component with `O_DIRECTORY`, the code now also
   `lstat`s it (`_os_stat_nofollow`, i.e. `os.stat(..., follow_symlinks=False)`)
   and raises `UnsafePathError` if it is a symbolic link. Added in three places:
   - `_open_anchored_root` — each component of the configured root;
   - `_traverse_parent_dir` — each intermediate component of an entry ID;
   - `list_children` — the final directory component being listed.

   This keeps the hard containment requirement ("do not follow symlinks for
   intermediate or final paths") enforced even on a platform that does not
   honour `O_NOFOLLOW` together with `O_DIRECTORY`. `O_NOFOLLOW` is retained, so
   on a conformant kernel the check is redundant defence-in-depth and the open
   remains the atomic guard against a symlink swapped in between the `lstat`
   and the open. Nothing was weakened or emulated silently.

## 7. Notes, limitations and residual risk

- The fixes were made because the tests are the module's acceptance gate and
  failed; per the assembly brief this is permitted only as a separate commit,
  which is what commit 2 is. Both the original failure and the fix are recorded
  here rather than hidden.
- On a kernel that enforces `O_NOFOLLOW` with `O_DIRECTORY` (e.g. ext4), only
  fix 1 (§5.2) is strictly required; fix 2 addresses the platform used for this
  run and is additive elsewhere.
- The adversarial symlink-swap test in the suite
  (`test_adversarial_symlink_swap_between_stat_and_read_and_mid_traversal`)
  passes both before and after the fixes.
- No claim of production security completeness is made. As the implementer
  documented, concurrent external writers, hard links, mount policy and
  adversarial root provisioning remain outside this module's protection, and
  the root must be operator-controlled. Security review and VPS integration
  remain director gates.
