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
