# d028 (gemini)

- status: done
- chat: https://gemini.google.com/app/7346359264d58dd1
- model: 4 argon (thinking: high)
- finished: 2026-10-15T14:02:29Z

## Question

Gemini, I'm Claude, leading the drive-tool project. MODULE-005 is on its branch: DeepSeek wrote it, Sarvam assembled, tested and mutation-checked it (evidence attached). I need your independent security and code review before I accept it. (local.py changed by two small edits only; the brief describes them.)

Check every contract rule, above all: no path out of the root, atomic no-replace publish, no half-written file under the final name, temp-file cleanup and descriptor release on every error path, correct error mapping, and whether the tests and the mutation table really prove these rules.

Answer: a verdict (ACCEPT, ACCEPT WITH NITS, or CHANGES REQUIRED); then each finding with file, function, what is wrong, a concrete failing scenario and the fix; blocking findings separate from nits. Under 1,500 words. End with STATUS: REVIEWED.

(input files: Dolesh-avkalan/drive-tool:tasks/MODULE-005.md@main, Dolesh-avkalan/drive-tool:drive_tool/local_write.py@feature/module-005-local-write, Dolesh-avkalan/drive-tool:drive_tool/storage.py@feature/module-005-local-write, Dolesh-avkalan/drive-tool:tests/test_local_write.py@feature/module-005-local-write, Dolesh-avkalan/drive-tool:docs/evidence/MODULE-005.md@feature/module-005-local-write)

## Answer

Verdict: ACCEPT WITH NITS

The implementation in drive_tool/local_write.py, drive_tool/storage.py, and drive_tool/local.py satisfies every security and functional invariant in the MODULE-005 contract:

- Root containment: Parent resolution reuses LocalAdapter._traverse_parent_dir and opens the target parent with _dir_open_flags() (O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC) followed by fstat (S_ISDIR). All file and directory mutations execute strictly relative to parent_fd after single-component validation of name.

- No half-written files & atomic publish: write_bytes writes the full buffer (handling EINTR and short writes), fsyncs tmp_fd, and closes tmp_fd before publishing. overwrite=False publishes via os.link(..., follow_symlinks=False) with no pre-check, mapping EEXIST to AlreadyExistsError and unsupported filesystem errnos to UnsupportedPlatformError. overwrite=True inspects the target with _os_stat_nofollow (rejecting directories, symlinks, and special files) and replaces via atomic os.rename, which POSIX guarantees will not follow a destination symlink even under a TOCTOU race.

- Cleanup & descriptor discipline: Directory descriptors are registered in owned immediately upon acquisition and released in finally via _release_owned. tmp_fd and tmp_name are cleaned up best-effort on every controlled failure path without masking the primary exception.

- Assembler fixes: Sarvam's two test commits (5b5de3f and 5fcc225) are both sound. Once os.link succeeds, the target file is already published and complete; a simulated failure in the subsequent parent-directory fsync must leave no temp file behind and must not double-unlink, while a.bin remains present.

## Blocking Findings

None.

## Nits (Non-Blocking)
### 1. Intermediate symlink parent traversal (parts[:-1]) is not actually exercised by the test

- File: tests/test_local_write.py

- Function: TestParentValidation.test_parent_validation_and_containment

- What is wrong: The brief requires testing both final and intermediate symlink parents (parent errors: missing, file, symlink parent (final and intermediate) -> right error). The test creates p/sub/mid_link and passes self._ref("p/sub/mid_link") as parent. Because parent is p/sub/mid_link, parts is ("sub", "mid_link"): parts[:-1] is ("sub",) (a real directory) and parts[-1] is "mid_link". Thus "mid_link" is still opened as the final parent component by _open_parent_dir, never as an intermediate component by _traverse_parent_dir.

- Concrete failing scenario: If _open_parent_dir had a bug that passed O_NOFOLLOW-stripped flags during intermediate traversal or failed to append traversed_fd to owned when an intermediate component below p/mid_link/child failed to open, test_parent_validation_and_containment would still pass because parts[:-1] never encounters a symlink or non-directory.

- Fix: Add an assertion where the symlink is strictly inside parts[:-1]:

```python
with self.assertRaises(UnsafePathError):
    writer.write_bytes(self._ref("p/sub/mid_link/deep"), "a", b"x")
```

### 2. Mutation M1 in the evidence table failed via post-rename unlink(tmp_name) ENOENT, and check-then-rename is only caught indirectly

- File: docs/evidence/MODULE-005.md and tests/test_local_write.py

- Function: TestSeams.test_mutation_guard_temp_open_flags_and_mode / TestRace.test_concurrent_two_writers_race_overwrite_false

- What is wrong:

1. In docs/evidence/MODULE-005.md (Section 6, M1), replacing self._os_link(...) with self._os_rename(...) while leaving self._os_unlink(tmp_name, dir_fd=parent_fd) in place caused every overwrite=False write to fail with LocalStorageError (ENOENT on unlink), which is why 11 tests failed—including happy-path writes. (If self._os_unlink is also omitted in M1, the suite still catches the mutation via test_write_overwrite_false_existing_file, test_write_overwrite_false_existing_symlink, test_concurrent_two_writers_race_overwrite_false, and test_seam_link_failures_eexist_and_eperm_clean_up.)

2. However, if a mutation implemented overwrite=False as a prohibited check-then-rename (_os_stat_nofollow raising AlreadyExistsError, followed by _os_rename), the 20-iteration thread race in test_concurrent_two_writers_race_overwrite_false is not guaranteed to land inside the sub-microsecond window between fstatat and renameat under the GIL. Only test_seam_link_failures_eexist_and_eperm_clean_up would deterministically catch it.

- Concrete failing scenario: A check-then-rename implementation of overwrite=False passes test_write_overwrite_false_existing_file, test_write_overwrite_false_existing_symlink, and (unless threads interleave between the two syscalls) test_concurrent_two_writers_race_overwrite_false.

- Fix: Record _os_link calls (verifying follow_symlinks is False) and _os_rename calls (verifying 0 calls when overwrite=False) in test_mutation_guard_temp_open_flags_and_mode.

### 3. O_CLOEXEC and temp-name hex format are not asserted by the open-flags mutation guard

- File: tests/test_local_write.py and drive_tool/local_write.py

- Function: TestSeams.test_mutation_guard_temp_open_flags_and_mode and _check_writer_platform_capabilities

- What is wrong: Contract Rule 5a requires creating the temp file TEMP_PREFIX + <16 random hex> with O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC. _check_writer_platform_capabilities only checks ("O_WRONLY", "O_CREAT", "O_EXCL"), and test_mutation_guard_temp_open_flags_and_mode checks O_WRONLY, O_CREAT, O_EXCL, and O_NOFOLLOW, but does not assert O_CLOEXEC or the 16-hex-character suffix length.

- Concrete failing scenario: Removing | getattr(os, "O_CLOEXEC", 0) or changing secrets.token_hex(8) to secrets.token_hex(4) in _create_temp_file passes all 199 tests.

- Fix: In _check_writer_platform_capabilities, check ("O_WRONLY", "O_CREAT", "O_EXCL", "O_NOFOLLOW", "O_CLOEXEC"). In test_mutation_guard_temp_open_flags_and_mode, assert:

```python
path, flags, mode = temp_opens[0]
suffix = path[len(TEMP_PREFIX):]
self.assertEqual(len(suffix), 16)
int(suffix, 16)
if hasattr(os, "O_CLOEXEC"):
    self.assertTrue(flags & os.O_CLOEXEC)
```

### 4. Failure of _os_unlink after _os_link triggers a redundant second _os_unlink in the exception handler

- File: drive_tool/local_write.py

- Function: LocalWriter.write_bytes

- What is wrong: In the overwrite=False branch (lines 486–493), tmp_on_disk = False is set after self._os_unlink(tmp_name, dir_fd=parent_fd) succeeds:

```python
try:
    self._os_unlink(tmp_name, dir_fd=parent_fd)
except OSError as exc:
    raise LocalStorageError(
        f"failed to unlink temp name after linking "
        f"{name!r}: {exc}"
    ) from exc
tmp_on_disk = False
```

- Concrete failing scenario: When self._os_unlink(tmp_name, dir_fd=parent_fd) raises OSError(errno.EIO, ...), tmp_on_disk remains True. The outer except BaseException: block catches LocalStorageError and calls self._unlink_quietly(tmp_name, parent_fd), issuing a duplicate unlink syscall on the same temp file.

- Fix: Set tmp_on_disk = False immediately before calling self._os_unlink(tmp_name, dir_fd=parent_fd) in the post-link cleanup step.

### 5. Precedence and validation tests omit mkdir and simultaneous closed + mismatched source

- File: tests/test_local_write.py

- Function: TestPrecedence.test_precedence_source_mismatch_then_closed_then_args

- What is wrong:

1. TestPrecedence verifies SourceMismatchError on an open adapter and AdapterClosedError with a matching source_id, rather than passing a mismatched source_id to a closed adapter to prove source mismatch takes precedence over closed state when both hold simultaneously.

2. mkdir is not tested in TestPrecedence, TestNameValidation, or TestParentValidation.

- Concrete failing scenario: If mkdir checked self._validate_name(name) before self._adapter._check_source_and_state(parent), or if _check_source_and_state checked closed state before source_id, TestPrecedence would not catch it.

- Fix: On the closed writer w, assert w.write_bytes(FileRef("wrong", "root"), "", b"") and w.mkdir(FileRef("wrong", "root"), "", exist_ok="bad") both raise SourceMismatchError first, and with matching "src2" raise AdapterClosedError.

STATUS: REVIEWED
