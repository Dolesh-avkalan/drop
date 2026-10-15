# d029 (deepseek)

- status: done
- chat: https://chat.deepseek.com/a/chat/s/c7238457-6f57-411c-83d7-ee46e185ee27
- model: deepseek (deepthink on, search off)
- finished: 2026-10-15T14:05:21Z

## Question

DeepSeek, I'm Claude, leading the drive-tool project. Your MODULE-005 code passed 199 tests, every mutation was caught, and Gemini's security review accepted it with five nits (attached). I need the nits closed.

1. ONE new test file, tests/test_local_write_proofs.py, proving Gemini's nits 1, 2, 3 and 5 exactly as its "Fix" lines describe: (1) a symlink strictly inside the parent's intermediate components (p/sub/mid_link/deep) is refused and nothing is written outside; (2) with overwrite=False the writer calls _os_link exactly once with follow_symlinks=False and _os_rename zero times, and with overwrite=True _os_rename once and _os_link zero times (record calls through the seams); (3) the temp-file open includes O_CLOEXEC (when the platform has it) and the temp name is TEMP_PREFIX plus exactly 16 lowercase hex characters; (5) on a closed writer with a wrong source_id, write_bytes and mkdir raise SourceMismatchError before AdapterClosedError and before argument errors, and mkdir validates names and parents like write_bytes.
2. Gemini's nit 4 and the capability part of nit 3 as exactly two EDIT drive_tool/local_write.py blocks (<<<< old ==== new >>>> with exact lines): set tmp_on_disk = False immediately BEFORE the post-link unlink of the temp name; and include O_NOFOLLOW and O_CLOEXEC in the writer's required-flag capability check. Add one test in the new file proving nit 4: when the post-link unlink fails, the temp name is unlinked exactly once.

Do not change any other file. unittest, tempfile, synthetic data only. Deliver: FILE: tests/test_local_write_proofs.py with the complete file in one fenced block, then the two EDIT blocks, then one line per test naming the mutation it catches. End with STATUS: GENERATED, TESTS_NOT_RUN.

(input files: Dolesh-avkalan/drive-tool:tasks/MODULE-005.md@main, Dolesh-avkalan/drop:drive-tool/module-005/d028-argon-code-review.md, Dolesh-avkalan/drive-tool:drive_tool/local_write.py@feature/module-005-local-write, Dolesh-avkalan/drive-tool:tests/test_local_write.py@feature/module-005-local-write)

## Answer

FILE: tests/test_local_write_proofs.py

```python
"""MODULE-005 proof tests for Gemini d028 nits 1, 2, 3, 4, 5.

These tests are additive evidence only. They use synthetic temp directories
and the existing public seams of LocalWriter.
"""

from __future__ import annotations

import errno
import os
import shutil
import tempfile
import unittest

from drive_tool.local import (
    AdapterClosedError,
    LocalAdapter,
    LocalStorageError,
    NotDirectoryError,
    TEMP_PREFIX,
    UnsafePathError,
)
from drive_tool.local_write import (
    DEFAULT_MAX_WRITE_BYTES,
    LocalWriter,
)
from drive_tool.storage import (
    FileRef,
    NotFoundError,
    SourceMismatchError,
)

class _BaseProofTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="drive_tool_lw_proof_")
        self.root = os.path.join(self.tmpdir, "root")
        os.mkdir(self.root)
        self.adapter = LocalAdapter(
            "src", self.root, max_read_bytes=DEFAULT_MAX_WRITE_BYTES
        )
        self.writer = LocalWriter(self.adapter)

    def tearDown(self) -> None:
        try:
            self.adapter.close()
        except Exception:
            pass
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def ref(self, file_id: str) -> FileRef:
        return FileRef(self.adapter.source_id, file_id)

    def root_ref(self) -> FileRef:
        return self.ref("root")

class TestNit1IntermediateSymlink(_BaseProofTest):
    def test_intermediate_symlink_in_parts_before_last_refused(self) -> None:
        outside = os.path.join(self.tmpdir, "outside")
        os.mkdir(outside)
        os.mkdir(os.path.join(self.root, "sub"))
        os.symlink(outside, os.path.join(self.root, "sub", "mid_link"))

        with self.assertRaises(UnsafePathError):
            self.writer.write_bytes(
                self.ref("p/sub/mid_link/deep"), "a.txt", b"x"
            )

        self.assertEqual(os.listdir(outside), [])

class TestNit2PublishSeams(_BaseProofTest):
    class RecordingWriter(LocalWriter):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.link_calls = []
            self.rename_calls = []

        def _os_link(
            self,
            src,
            dst,
            *,
            src_dir_fd,
            dst_dir_fd,
            follow_symlinks=False,
        ):
            self.link_calls.append(
                (src, dst, src_dir_fd, dst_dir_fd, follow_symlinks)
            )
            return os.link(
                src,
                dst,
                src_dir_fd=src_dir_fd,
                dst_dir_fd=dst_dir_fd,
                follow_symlinks=follow_symlinks,
            )

        def _os_rename(self, src, dst, *, src_dir_fd, dst_dir_fd):
            self.rename_calls.append((src, dst, src_dir_fd, dst_dir_fd))
            return os.rename(
                src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd
            )

    def test_publish_uses_link_for_no_overwrite_and_rename_for_overwrite(self) -> None:
        w = self.RecordingWriter(self.adapter)
        w.write_bytes(self.root_ref(), "a.bin", b"x", overwrite=False)
        self.assertEqual(len(w.link_calls), 1)
        self.assertFalse(w.link_calls[0][4])
        self.assertEqual(len(w.rename_calls), 0)

        w.write_bytes(self.root_ref(), "b.bin", b"y", overwrite=True)
        self.assertEqual(len(w.rename_calls), 1)
        self.assertEqual(len(w.link_calls), 1)

class TestNit3TempOpenFlagsAndName(_BaseProofTest):
    class OpenSpyWriter(LocalWriter):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.opens = []

        def _os_open(self, path, flags, mode=0o777, *, dir_fd=None):
            self.opens.append((path, flags, mode))
            return os.open(path, flags, mode, dir_fd=dir_fd)

    def test_temp_open_has_cloexec_and_16_lower_hex_name(self) -> None:
        w = self.OpenSpyWriter(self.adapter)
        w.write_bytes(self.root_ref(), "a.bin", b"payload")

        temp_opens = [o for o in w.opens if o[0].startswith(TEMP_PREFIX)]
        self.assertEqual(len(temp_opens), 1)
        path, flags, mode = temp_opens[0]
        suffix = path[len(TEMP_PREFIX):]
        self.assertEqual(len(suffix), 16)
        self.assertEqual(suffix, suffix.lower())
        int(suffix, 16)
        if hasattr(os, "O_CLOEXEC"):
            self.assertTrue(flags & os.O_CLOEXEC)

class TestNit4PostLinkUnlinkFailure(_BaseProofTest):
    class UnlinkFailAfterLink(LocalWriter):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.unlink_calls = []

        def _os_unlink(self, path, *, dir_fd):
            self.unlink_calls.append(path)
            raise OSError(errno.EIO, "simulated post-link unlink failure")

    def test_post_link_unlink_failure_calls_unlink_once(self) -> None:
        w = self.UnlinkFailAfterLink(self.adapter)
        with self.assertRaises(LocalStorageError):
            w.write_bytes(self.root_ref(), "a.bin", b"x", overwrite=False)

        self.assertEqual(len(w.unlink_calls), 1)
        self.assertTrue(os.path.exists(os.path.join(self.root, "a.bin")))

class TestNit5ClosedPrecedenceAndMkdirValidation(_BaseProofTest):
    def test_closed_wrong_source_precedes_closed_and_args_and_mkdir_validation(self) -> None:
        tmpdir = tempfile.mkdtemp(prefix="drive_tool_lw_proof_closed_")
        try:
            root = os.path.join(tmpdir, "root")
            os.mkdir(root)
            adapter = LocalAdapter(
                "src2", root, max_read_bytes=DEFAULT_MAX_WRITE_BYTES
            )
            writer = LocalWriter(adapter)
            adapter.close()

            with self.assertRaises(SourceMismatchError):
                writer.write_bytes(FileRef("wrong", "root"), "", b"")
            with self.assertRaises(SourceMismatchError):
                writer.mkdir(FileRef("wrong", "root"), "", exist_ok="bad")

            with self.assertRaises(AdapterClosedError):
                writer.write_bytes(FileRef("src2", "root"), "", b"")
            with self.assertRaises(AdapterClosedError):
                writer.mkdir(FileRef("src2", "root"), "", exist_ok="bad")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        with self.assertRaises(UnsafePathError):
            self.writer.mkdir(self.root_ref(), "")
        with self.assertRaises(UnsafePathError):
            self.writer.mkdir(self.root_ref(), "a/b")
        with self.assertRaises(UnsafePathError):
            self.writer.mkdir(self.root_ref(), TEMP_PREFIX + "x")

        with self.assertRaises(NotFoundError):
            self.writer.mkdir(self.ref("p/missing"), "d")

        with open(os.path.join(self.root, "afile"), "wb") as f:
            f.write(b"x")
        with self.assertRaises(NotDirectoryError):
            self.writer.mkdir(self.ref("p/afile"), "d")

        outside = os.path.join(self.tmpdir, "outside")
        os.mkdir(outside)
        os.symlink(outside, os.path.join(self.root, "final_link"))
        with self.assertRaises(UnsafePathError):
            self.writer.mkdir(self.ref("p/final_link"), "d")

        os.mkdir(os.path.join(self.root, "sub"))
        os.symlink(outside, os.path.join(self.root, "sub", "mid_link"))
        with self.assertRaises(UnsafePathError):
            self.writer.mkdir(self.ref("p/sub/mid_link/deep"), "d")

        self.assertEqual(os.listdir(outside), [])

if __name__ == "__main__":
    unittest.main()
```

EDIT drive_tool/local_write.py:

```text
<<<< old
                try:
                    self._os_unlink(tmp_name, dir_fd=parent_fd)
                except OSError as exc:
                    raise LocalStorageError(
                        f"failed to unlink temp name after linking "
                        f"{name!r}: {exc}"
                    ) from exc
                tmp_on_disk = False
==== new
                tmp_on_disk = False
                try:
                    self._os_unlink(tmp_name, dir_fd=parent_fd)
                except OSError as exc:
                    raise LocalStorageError(
                        f"failed to unlink temp name after linking "
                        f"{name!r}: {exc}"
                    ) from exc
>>>>
```

EDIT drive_tool/local_write.py:

```text
<<<< old
    for flag_name in ("O_WRONLY", "O_CREAT", "O_EXCL"):
==== new
    for flag_name in ("O_WRONLY", "O_CREAT", "O_EXCL", "O_NOFOLLOW", "O_CLOEXEC"):
>>>>
```

TestNit1IntermediateSymlink.test_intermediate_symlink_in_parts_before_last_refused — catches dropping O_NOFOLLOW during intermediate traversal or accepting a symlink strictly inside parts[:-1].
TestNit2PublishSeams.test_publish_uses_link_for_no_overwrite_and_rename_for_overwrite — catches check-then-rename or using the wrong publish primitive for overwrite=False/True.
TestNit3TempOpenFlagsAndName.test_temp_open_has_cloexec_and_16_lower_hex_name — catches dropping O_CLOEXEC or using a non-16-lowercase-hex temp suffix.
TestNit4PostLinkUnlinkFailure.test_post_link_unlink_failure_calls_unlink_once — catches leaving tmp_on_disk True after link so the exception handler double-unlinks.
TestNit5ClosedPrecedenceAndMkdirValidation.test_closed_wrong_source_precedes_closed_and_args_and_mkdir_validation — catches checking closed/arguments before source mismatch and mkdir skipping name/parent validation.

STATUS: GENERATED, TESTS_NOT_RUN
