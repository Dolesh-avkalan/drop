"""Unit and containment tests for MODULE-003 (drive_tool.local)."""

from __future__ import annotations

import errno
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from drive_tool.local import (
    DEFAULT_MAX_READ_BYTES,
    AdapterClosedError,
    LocalAdapter,
    LocalStorageError,
    ReadLimitExceededError,
    UnsafePathError,
    UnsupportedEntryError,
    UnsupportedPlatformError,
    _dir_open_flags,
    _no_follow_semantics_available,
)
from drive_tool.storage import (
    ROOT_ID,
    FileMetadata,
    FileRef,
    IsDirectoryError,
    NotDirectoryError,
    NotFoundError,
    SourceMismatchError,
    StorageAdapter,
    StorageError,
)

def _static_posix_prerequisites_met() -> bool:
    """Return True when the STATIC POSIX facilities the adapter needs exist.

    This deliberately does NOT run the runtime no-follow probe: the probe and
    platform-denial tests must still run when static facilities exist even if
    the runtime probe returns False. A correctly rejected (non-conformant)
    kernel is a legitimate fail-closed outcome, not a reason to skip the tests
    that check it.
    """
    return (
        os.name == "posix"
        and hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_NONBLOCK")
        and os.open in getattr(os, "supports_dir_fd", set())
        and os.stat in getattr(os, "supports_dir_fd", set())
        and os.stat in getattr(os, "supports_follow_symlinks", set())
        and os.scandir in getattr(os, "supports_fd", set())
    )


def _runtime_nofollow_enforced() -> bool:
    """Return True when the running kernel actually enforces the adapter flags."""
    return _no_follow_semantics_available()


class _PosixStaticTestCase(unittest.TestCase):
    """Base case gated only on STATIC POSIX facilities.

    Probe/platform-denial tests derive from this class so they run whenever the
    static facilities exist, even when the runtime probe returns False.
    """

    def setUp(self) -> None:
        if not _static_posix_prerequisites_met():
            self.skipTest("static POSIX dir_fd/O_NOFOLLOW facilities required")
        # Resolve OS-level symlinks in the system temp root so the fixture path
        # has zero symlinks in its ancestor chain from /.
        raw_base = tempfile.mkdtemp(prefix="drive_tool_mod003_")
        self.base_dir = Path(os.path.realpath(raw_base))
        self.root_dir = self.base_dir / "root"
        self.outside_dir = self.base_dir / "outside"
        self.root_dir.mkdir()
        self.outside_dir.mkdir()

    def tearDown(self) -> None:
        if hasattr(self, "base_dir") and self.base_dir.exists():
            shutil.rmtree(self.base_dir, ignore_errors=True)


class _PosixRuntimeTestCase(_PosixStaticTestCase):
    """Base case for OPERATIONAL tests that actually drive the adapter.

    These may skip when the runtime probe reports that O_NOFOLLOW is not
    enforced (the adapter is then correctly unsupported / fail-closed), with a
    precise reason. The probe/denial tests derive from ``_PosixStaticTestCase``
    so they are never skipped by the result they test.
    """

    def setUp(self) -> None:
        super().setUp()
        if not _runtime_nofollow_enforced():
            self.skipTest(
                "adapter unsupported on this kernel: O_NOFOLLOW is not enforced "
                "(runtime probe returned False); operational containment tests "
                "are not meaningful here"
            )


class _PosixTempRootTestCase(_PosixRuntimeTestCase):
    """Operational base: static facilities plus an enforced no-follow kernel."""

class TestPlatformCapabilityGate(unittest.TestCase):
    """Tests for explicit platform capability gating (runs on all platforms)."""

    def test_error_hierarchy_extends_storage_error(self) -> None:
        self.assertTrue(issubclass(LocalStorageError, StorageError))
        self.assertTrue(issubclass(UnsafePathError, LocalStorageError))
        self.assertTrue(issubclass(UnsupportedEntryError, LocalStorageError))
        self.assertTrue(issubclass(ReadLimitExceededError, LocalStorageError))
        self.assertTrue(issubclass(AdapterClosedError, LocalStorageError))
        self.assertTrue(issubclass(UnsupportedPlatformError, LocalStorageError))

    def test_non_posix_os_name_raises_unsupported_platform_error(self) -> None:
        with mock.patch("drive_tool.local.os.name", "nt"):
            with self.assertRaises(UnsupportedPlatformError):
                LocalAdapter("local-src", "/tmp")

    def test_missing_o_nofollow_raises_unsupported_platform_error(self) -> None:
        with mock.patch("drive_tool.local.os.O_NOFOLLOW", 0, create=True):
            with self.assertRaises(UnsupportedPlatformError):
                LocalAdapter("local-src", "/tmp")

    def test_missing_dir_fd_support_raises_unsupported_platform_error(self) -> None:
        with mock.patch("drive_tool.local.os.supports_dir_fd", set()):
            with self.assertRaises(UnsupportedPlatformError):
                LocalAdapter("local-src", "/tmp")

    def test_missing_follow_symlinks_support_raises_unsupported_platform_error(
        self,
    ) -> None:
        with mock.patch("drive_tool.local.os.supports_follow_symlinks", set()):
            with self.assertRaises(UnsupportedPlatformError):
                LocalAdapter("local-src", "/tmp")

    def test_missing_scandir_fd_support_raises_unsupported_platform_error(
        self,
    ) -> None:
        with mock.patch("drive_tool.local.os.supports_fd", set()):
            with self.assertRaises(UnsupportedPlatformError):
                LocalAdapter("local-src", "/tmp")

class TestPlatformNoFollowSemantics(_PosixStaticTestCase):
    """Real-kernel checks that O_NOFOLLOW (without O_DIRECTORY) is enforced.

    These assert against the actual kernel rather than a simulated result: the
    adapter's chosen strategy relies on ``O_NOFOLLOW`` alone being honoured.
    """

    def test_dir_open_flags_exclude_o_directory(self) -> None:
        flags = _dir_open_flags()
        self.assertTrue(flags & os.O_NOFOLLOW)
        self.assertTrue(flags & os.O_NONBLOCK)
        self.assertFalse(
            flags & getattr(os, "O_DIRECTORY", 0),
            "directory-component opens must not use O_DIRECTORY",
        )

    def test_real_kernel_rejects_symlink_with_component_flags(self) -> None:
        """Raw kernel: production flags either reject the symlink or fail closed.

        Runs whenever static facilities exist and is NOT skipped by the result
        it tests. On a kernel that enforces O_NOFOLLOW the open is rejected with
        ELOOP/EMLINK; on one that does not, the correct product behaviour is
        fail-closed, so the adapter must raise UnsupportedPlatformError rather
        than proceed unsafely.
        """
        (self.outside_dir / "inside").mkdir()
        link = self.root_dir / "linkdir"
        os.symlink(self.outside_dir, link)

        flags = _dir_open_flags()
        rejected = False
        try:
            fd = os.open(str(link), flags)
        except OSError as exc:
            rejected = exc.errno in (errno.ELOOP, getattr(errno, "EMLINK", -1))
        else:
            os.close(fd)

        if _no_follow_semantics_available():
            self.assertTrue(
                rejected,
                msg="probe reports no-follow enforced, but the kernel followed a "
                "symlink with the production component flags",
            )
        else:
            with self.assertRaises(UnsupportedPlatformError):
                LocalAdapter("src", self.root_dir)

    def test_real_kernel_opens_real_directory_and_fstat_is_dir(self) -> None:
        flags = _dir_open_flags()
        fd = os.open(str(self.root_dir), flags)
        try:
            self.assertTrue(stat.S_ISDIR(os.fstat(fd).st_mode))
        finally:
            os.close(fd)

    def test_runtime_probe_matches_raw_kernel_nofollow(self) -> None:
        """The runtime probe must agree with the raw kernel, not a constant."""
        (self.outside_dir / "inside").mkdir()
        link = self.root_dir / "linkdir"
        os.symlink(self.outside_dir, link)

        flags = _dir_open_flags()
        try:
            fd = os.open(str(link), flags)
        except OSError as exc:
            enforced = exc.errno in (errno.ELOOP, getattr(errno, "EMLINK", -1))
        else:
            os.close(fd)
            enforced = False

        self.assertEqual(
            _no_follow_semantics_available(),
            enforced,
            msg="runtime probe disagrees with actual kernel O_NOFOLLOW behaviour",
        )

    def test_probe_follows_production_dir_flags(self) -> None:
        """Removing O_NOFOLLOW from the production helper must be detected.

        The probe must derive its flags from the production helper rather than a
        separately reconstructed bitmask, so weakening the helper makes the
        probe detect following and the constructor fail closed.
        """
        real_helper = _dir_open_flags

        def weakened_helper() -> int:
            return real_helper() & ~os.O_NOFOLLOW

        with mock.patch(
            "drive_tool.local._dir_open_flags", side_effect=weakened_helper
        ):
            self.assertFalse(
                _no_follow_semantics_available(),
                msg="probe did not follow the weakened production flags",
            )
            with self.assertRaises(UnsupportedPlatformError):
                LocalAdapter("src", self.root_dir)

    def test_file_and_dir_open_flags_share_safe_flags(self) -> None:
        """File and directory component opens share the same safe flags."""
        from drive_tool.local import _file_open_flags

        dir_flags = _dir_open_flags()
        file_flags = _file_open_flags()
        for flags in (dir_flags, file_flags):
            self.assertTrue(flags & os.O_NOFOLLOW)
            self.assertTrue(flags & os.O_NONBLOCK)
            self.assertFalse(flags & getattr(os, "O_DIRECTORY", 0))
        self.assertEqual(dir_flags, file_flags)

    def test_unsupported_platform_when_runtime_probe_fails(self) -> None:
        with mock.patch(
            "drive_tool.local._no_follow_semantics_available",
            return_value=False,
        ):
            with self.assertRaises(UnsupportedPlatformError):
                LocalAdapter("src", self.root_dir)

class TestConfigurationAndRootValidation(_PosixTempRootTestCase):
    """Tests for constructor argument validation and no-follow root setup."""

    def test_invalid_source_id_raises_value_error(self) -> None:
        for bad_source in ("", None, 123, ["src"]):  # type: ignore[list-item]
            with self.subTest(bad_source=bad_source):
                with self.assertRaises(ValueError):
                    LocalAdapter(bad_source, self.root_dir)  # type: ignore[arg-type]

    def test_invalid_max_read_bytes_raises_value_error(self) -> None:
        for bad_limit in (0, -1, -1024, True, False, "1024", 1.5, None):
            with self.subTest(bad_limit=bad_limit):
                with self.assertRaises(ValueError):
                    LocalAdapter(
                        "local-src",
                        self.root_dir,
                        max_read_bytes=bad_limit,  # type: ignore[arg-type]
                    )

    def test_invalid_root_types_and_non_canonical_roots_rejected(self) -> None:
        for bad_root in (
            123,
            None,
            "",
            "relative/path",
            "./relative",
            f"{self.root_dir}/.",
            f"{self.root_dir}/..",
            f"{self.root_dir}/",
            f"{self.root_dir}//sub",
            f"{self.root_dir}/bad\x00name",
            f"{self.root_dir}/bad\\name",
        ):
            with self.subTest(bad_root=bad_root):
                with self.assertRaises(ValueError):
                    LocalAdapter("local-src", bad_root)  # type: ignore[arg-type]

    def test_nonexistent_and_file_root_rejected(self) -> None:
        missing_root = self.base_dir / "does_not_exist"
        with self.assertRaises(ValueError):
            LocalAdapter("local-src", missing_root)

        file_root = self.base_dir / "regular_file.txt"
        file_root.write_bytes(b"not a dir")
        with self.assertRaises(ValueError):
            LocalAdapter("local-src", file_root)

    def test_symlink_root_and_symlink_ancestor_rejected(self) -> None:
        real_target = self.outside_dir / "real_subdir"
        real_target.mkdir()

        symlink_root = self.base_dir / "symlink_root"
        os.symlink(real_target, symlink_root)

        with self.assertRaises(UnsafePathError):
            LocalAdapter("local-src", symlink_root)

        nested_inside_target = real_target / "nested_dir"
        nested_inside_target.mkdir()
        path_with_symlink_ancestor = symlink_root / "nested_dir"

        with self.assertRaises(UnsafePathError):
            LocalAdapter("local-src", path_with_symlink_ancestor)

class TestBasicOperationsAndMetadata(_PosixTempRootTestCase):
    """Tests for stat, list_children, read_bytes, parent IDs, and real 'root' file."""

    def test_protocol_conformance_and_defaults(self) -> None:
        with LocalAdapter("local-a", self.root_dir) as adapter:
            self.assertIsInstance(adapter, StorageAdapter)
            self.assertEqual(adapter.source_id, "local-a")
            self.assertEqual(adapter.max_read_bytes, DEFAULT_MAX_READ_BYTES)

    def test_synthetic_root_and_real_top_level_root_filename(self) -> None:
        real_root_file = self.root_dir / "root"
        real_root_file.write_bytes(b"real-root-file-payload")

        with LocalAdapter("local-a", self.root_dir) as adapter:
            synth_meta = adapter.stat(FileRef("local-a", ROOT_ID))
            self.assertEqual(
                synth_meta,
                FileMetadata(
                    ref=FileRef("local-a", "root"),
                    name="",
                    parent_id=None,
                    kind="directory",
                    size_bytes=None,
                ),
            )

            real_meta = adapter.stat(FileRef("local-a", "p/root"))
            self.assertEqual(
                real_meta,
                FileMetadata(
                    ref=FileRef("local-a", "p/root"),
                    name="root",
                    parent_id="root",
                    kind="file",
                    size_bytes=22,
                ),
            )
            self.assertEqual(
                adapter.read_bytes(FileRef("local-a", "p/root")),
                b"real-root-file-payload",
            )

    def test_nested_stat_list_and_read_exact_binary_and_empty_files(self) -> None:
        empty_file = self.root_dir / "empty.bin"
        empty_file.write_bytes(b"")

        notes_dir = self.root_dir / "notes"
        notes_dir.mkdir()
        nested_dir = notes_dir / "2026"
        nested_dir.mkdir()

        binary_payload = bytes(range(256)) + b"\x00\xff\xfe\r\n"
        report_file = nested_dir / "report.bin"
        report_file.write_bytes(binary_payload)

        with LocalAdapter("src-1", self.root_dir) as adapter:
            empty_meta = adapter.stat(FileRef("src-1", "p/empty.bin"))
            self.assertEqual(
                empty_meta,
                FileMetadata(
                    ref=FileRef("src-1", "p/empty.bin"),
                    name="empty.bin",
                    parent_id="root",
                    kind="file",
                    size_bytes=0,
                ),
            )
            self.assertEqual(
                adapter.read_bytes(FileRef("src-1", "p/empty.bin")), b""
            )

            notes_meta = adapter.stat(FileRef("src-1", "p/notes"))
            self.assertEqual(
                notes_meta,
                FileMetadata(
                    ref=FileRef("src-1", "p/notes"),
                    name="notes",
                    parent_id="root",
                    kind="directory",
                    size_bytes=None,
                ),
            )

            nested_dir_meta = adapter.stat(FileRef("src-1", "p/notes/2026"))
            self.assertEqual(
                nested_dir_meta,
                FileMetadata(
                    ref=FileRef("src-1", "p/notes/2026"),
                    name="2026",
                    parent_id="p/notes",
                    kind="directory",
                    size_bytes=None,
                ),
            )

            report_meta = adapter.stat(
                FileRef("src-1", "p/notes/2026/report.bin")
            )
            self.assertEqual(
                report_meta,
                FileMetadata(
                    ref=FileRef("src-1", "p/notes/2026/report.bin"),
                    name="report.bin",
                    parent_id="p/notes/2026",
                    kind="file",
                    size_bytes=len(binary_payload),
                ),
            )
            self.assertEqual(
                adapter.read_bytes(
                    FileRef("src-1", "p/notes/2026/report.bin")
                ),
                binary_payload,
            )

            nested_children = adapter.list_children(
                FileRef("src-1", "p/notes/2026")
            )
            self.assertEqual(nested_children, [report_meta])

    def test_sorted_listing_and_empty_directory(self) -> None:
        (self.root_dir / "zeta.txt").write_bytes(b"z")
        (self.root_dir / "alpha.txt").write_bytes(b"abc")
        (self.root_dir / "middle_dir").mkdir()
        (self.root_dir / "root").write_bytes(b"r")

        with LocalAdapter("src-1", self.root_dir) as adapter:
            # Empty subdirectory returns empty list
            self.assertEqual(
                adapter.list_children(FileRef("src-1", "p/middle_dir")), []
            )

            # Root listing is sorted by basename and repeatable across calls
            first_listing = adapter.list_children(FileRef("src-1", ROOT_ID))
            second_listing = adapter.list_children(FileRef("src-1", ROOT_ID))
            self.assertEqual(first_listing, second_listing)
            self.assertEqual(
                [m.name for m in first_listing],
                ["alpha.txt", "middle_dir", "root", "zeta.txt"],
            )
            self.assertEqual(
                [m.ref.file_id for m in first_listing],
                ["p/alpha.txt", "p/middle_dir", "p/root", "p/zeta.txt"],
            )

class TestPrecedenceAndMalformedIds(_PosixTempRootTestCase):
    """Tests for source mismatch precedence, missing entries, and malformed IDs."""

    def test_source_mismatch_precedence_across_all_methods_and_states(
        self,
    ) -> None:
        adapter = LocalAdapter("expected-source", self.root_dir)
        try:
            bad_refs = [
                FileRef("wrong-source", ROOT_ID),
                FileRef("wrong-source", "p/missing.txt"),
                FileRef("wrong-source", ""),
                FileRef("wrong-source", "../escape"),
                FileRef("wrong-source", "/etc/passwd"),
                FileRef("wrong-source", "p/a//b"),
                FileRef("wrong-source", "p/bad\x00id"),
                FileRef("wrong-source", "p/bad\\id"),
            ]
            for bad_ref in bad_refs:
                with self.subTest(state="open", ref=bad_ref):
                    with self.assertRaises(SourceMismatchError):
                        adapter.stat(bad_ref)
                    with self.assertRaises(SourceMismatchError):
                        adapter.list_children(bad_ref)
                    with self.assertRaises(SourceMismatchError):
                        adapter.read_bytes(bad_ref)
        finally:
            adapter.close()

        # Even after close(), source mismatch still takes precedence over AdapterClosedError.
        for bad_ref in bad_refs:
            with self.subTest(state="closed", ref=bad_ref):
                with self.assertRaises(SourceMismatchError):
                    adapter.stat(bad_ref)
                with self.assertRaises(SourceMismatchError):
                    adapter.list_children(bad_ref)
                with self.assertRaises(SourceMismatchError):
                    adapter.read_bytes(bad_ref)

    def test_non_fileref_raises_type_error(self) -> None:
        with LocalAdapter("src", self.root_dir) as adapter:
            for invalid in ("root", None, 42):
                with self.assertRaises(TypeError):
                    adapter.stat(invalid)  # type: ignore[arg-type]
                with self.assertRaises(TypeError):
                    adapter.list_children(invalid)  # type: ignore[arg-type]
                with self.assertRaises(TypeError):
                    adapter.read_bytes(invalid)  # type: ignore[arg-type]

    def test_missing_entries_and_file_directory_type_errors(self) -> None:
        (self.root_dir / "file.txt").write_bytes(b"hello")
        (self.root_dir / "subdir").mkdir()

        with LocalAdapter("src", self.root_dir) as adapter:
            for missing_id in ("p/missing.txt", "p/subdir/missing.txt", "p/no_dir/a.txt"):
                ref = FileRef("src", missing_id)
                with self.assertRaises(NotFoundError):
                    adapter.stat(ref)
                with self.assertRaises(NotFoundError):
                    adapter.list_children(ref)
                with self.assertRaises(NotFoundError):
                    adapter.read_bytes(ref)

            # read_bytes on synthetic root or real directory raises IsDirectoryError
            with self.assertRaises(IsDirectoryError):
                adapter.read_bytes(FileRef("src", ROOT_ID))
            with self.assertRaises(IsDirectoryError):
                adapter.read_bytes(FileRef("src", "p/subdir"))

            # list_children on regular file raises NotDirectoryError
            with self.assertRaises(NotDirectoryError):
                adapter.list_children(FileRef("src", "p/file.txt"))

            # Traversing through a regular file as an intermediate component raises NotDirectoryError
            with self.assertRaises(NotDirectoryError):
                adapter.stat(FileRef("src", "p/file.txt/child"))
            with self.assertRaises(NotDirectoryError):
                adapter.list_children(FileRef("src", "p/file.txt/child"))
            with self.assertRaises(NotDirectoryError):
                adapter.read_bytes(FileRef("src", "p/file.txt/child"))

    def test_all_malformed_id_classes_rejected_with_unsafe_path_error(
        self,
    ) -> None:
        malformed_ids: list[object] = [
            "",
            "p",
            "p/",
            "file.txt",
            "root/",
            "/root",
            "/etc/passwd",
            "/p/file.txt",
            "p//file.txt",
            "p/a//b",
            "p/a/",
            "p/.",
            "p/..",
            "p/./a",
            "p/../a",
            "p/a/./b",
            "p/a/../b",
            "p/a\\b",
            "p/a\x00b",
            None,
            123,
        ]
        with LocalAdapter("src", self.root_dir) as adapter:
            for bad_id in malformed_ids:
                ref = FileRef("src", bad_id)  # type: ignore[arg-type]
                with self.subTest(bad_id=bad_id):
                    with self.assertRaises(UnsafePathError):
                        adapter.stat(ref)
                    with self.assertRaises(UnsafePathError):
                        adapter.list_children(ref)
                    with self.assertRaises(UnsafePathError):
                        adapter.read_bytes(ref)

class TestContainmentSymlinksAndAnchoredRoot(_PosixTempRootTestCase):
    """Tests for symlink rejection, anchored root rename, and adversarial swaps."""

    def test_final_and_intermediate_symlinks_rejected_and_omitted_from_listing(
        self,
    ) -> None:
        outside_secret = self.outside_dir / "secret.txt"
        outside_secret.write_bytes(b"TOP_SECRET_OUTSIDE")
        outside_sub = self.outside_dir / "sub"
        outside_sub.mkdir()
        (outside_sub / "deep.txt").write_bytes(b"DEEP_OUTSIDE")

        inside_file = self.root_dir / "safe.txt"
        inside_file.write_bytes(b"safe")
        inside_dir = self.root_dir / "real_dir"
        inside_dir.mkdir()
        (inside_dir / "inside.txt").write_bytes(b"inside")

        # Create symlinks inside root pointing outside, inside, and broken
        os.symlink(outside_secret, self.root_dir / "sym_outside_file")
        os.symlink(self.outside_dir, self.root_dir / "sym_outside_dir")
        os.symlink(inside_file, self.root_dir / "sym_inside_file")
        os.symlink(
            self.root_dir / "nonexistent_target", self.root_dir / "sym_broken"
        )
        os.symlink(outside_sub, inside_dir / "sym_nested_dir")

        with LocalAdapter("src", self.root_dir) as adapter:
            # Direct stat/read on symlinks raises UnsafePathError
            for sym_id in (
                "p/sym_outside_file",
                "p/sym_outside_dir",
                "p/sym_inside_file",
                "p/sym_broken",
                "p/real_dir/sym_nested_dir",
            ):
                ref = FileRef("src", sym_id)
                with self.subTest(sym_id=sym_id):
                    with self.assertRaises(UnsafePathError):
                        adapter.stat(ref)
                    with self.assertRaises(UnsafePathError):
                        adapter.read_bytes(ref)
                    with self.assertRaises(UnsafePathError):
                        adapter.list_children(ref)

            # Intermediate traversal through symlinks raises UnsafePathError
            for traversal_id in (
                "p/sym_outside_dir/secret.txt",
                "p/sym_outside_dir/sub/deep.txt",
                "p/real_dir/sym_nested_dir/deep.txt",
            ):
                ref = FileRef("src", traversal_id)
                with self.subTest(traversal_id=traversal_id):
                    with self.assertRaises(UnsafePathError):
                        adapter.stat(ref)
                    with self.assertRaises(UnsafePathError):
                        adapter.read_bytes(ref)
                    with self.assertRaises(UnsafePathError):
                        adapter.list_children(ref)

            # Directory listing omits all symlinks and returns only real supported entries
            root_children = adapter.list_children(FileRef("src", ROOT_ID))
            self.assertEqual(
                [m.name for m in root_children], ["real_dir", "safe.txt"]
            )
            nested_children = adapter.list_children(
                FileRef("src", "p/real_dir")
            )
            self.assertEqual([m.name for m in nested_children], ["inside.txt"])

    def test_disappearing_entry_during_listing_is_skipped(self) -> None:
        (self.root_dir / "keep.txt").write_bytes(b"keep")
        vanish_path = self.root_dir / "vanish.txt"
        vanish_path.write_bytes(b"vanish")

        with LocalAdapter("src", self.root_dir) as adapter:
            orig_scandir = adapter._os_scandir

            class _DisappearingEntryWrapper:
                def __init__(self, inner_entry: os.DirEntry[str]) -> None:
                    self._inner = inner_entry
                    self.name = inner_entry.name

                def stat(self, *, follow_symlinks: bool = True) -> os.stat_result:
                    if self.name == "vanish.txt":
                        raise FileNotFoundError(
                            errno.ENOENT, "No such file or directory", self.name
                        )
                    return self._inner.stat(follow_symlinks=follow_symlinks)

            class _ScandirCtxWrapper:
                def __init__(self, inner_ctx) -> None:
                    self._inner_ctx = inner_ctx

                def __enter__(self):
                    entries = self._inner_ctx.__enter__()
                    return [_DisappearingEntryWrapper(e) for e in entries]

                def __exit__(self, exc_type, exc_val, exc_tb):
                    return self._inner_ctx.__exit__(exc_type, exc_val, exc_tb)

            with mock.patch.object(
                adapter,
                "_os_scandir",
                side_effect=lambda fd: _ScandirCtxWrapper(orig_scandir(fd)),
            ):
                listing = adapter.list_children(FileRef("src", ROOT_ID))
                self.assertEqual([m.name for m in listing], ["keep.txt"])

    def test_root_renamed_and_replaced_by_outside_symlink_stays_anchored(
        self,
    ) -> None:
        (self.root_dir / "anchored.txt").write_bytes(b"ORIGINAL_DATA")
        (self.outside_dir / "anchored.txt").write_bytes(b"OUTSIDE_FORGED_DATA")
        (self.outside_dir / "outside_only.txt").write_bytes(b"OUTSIDE_ONLY")

        with LocalAdapter("src", self.root_dir) as adapter:
            moved_root = self.base_dir / "root_moved"
            os.rename(self.root_dir, moved_root)
            os.symlink(self.outside_dir, self.root_dir)

            # Old adapter remains anchored to the originally opened directory descriptor
            self.assertEqual(
                adapter.read_bytes(FileRef("src", "p/anchored.txt")),
                b"ORIGINAL_DATA",
            )
            listing = adapter.list_children(FileRef("src", ROOT_ID))
            self.assertEqual([m.name for m in listing], ["anchored.txt"])
            with self.assertRaises(NotFoundError):
                adapter.stat(FileRef("src", "p/outside_only.txt"))

    def test_adversarial_symlink_swap_between_stat_and_read_and_mid_traversal(
        self,
    ) -> None:
        """Deterministic mechanism proof that symlink swaps cannot escape root.

        Part 1: Target file is replaced by a symlink to an outside secret file
        after `stat` succeeds and immediately before `read_bytes` opens it.
        `O_NOFOLLOW` on `openat` atomically rejects the swapped symlink.

        Part 2: Intermediate directory `sub` is opened via anchored `openat`,
        then `sub` is renamed on disk and replaced at its old path by a symlink
        to `outside_dir` right before `target.txt` is opened inside `parent_fd`.
        Because `openat` uses `dir_fd=parent_fd`, it stays inside the original
        directory and ignores the newly placed symlink at the old path.
        """
        sub_dir = self.root_dir / "sub"
        sub_dir.mkdir()
        target_file = sub_dir / "target.txt"
        target_file.write_bytes(b"SAFE_PAYLOAD")

        outside_secret = self.outside_dir / "target.txt"
        outside_secret.write_bytes(b"OUTSIDE_SECRET")

        with LocalAdapter("src", self.root_dir) as adapter:
            # Part 1: Swap target_file with a symlink to outside_secret right before open
            meta = adapter.stat(FileRef("src", "p/sub/target.txt"))
            self.assertEqual(meta.size_bytes, len(b"SAFE_PAYLOAD"))

            orig_open = adapter._os_open

            def swap_target_before_file_open(
                path: str, flags: int, *, dir_fd: int | None = None
            ) -> int:
                if path == "target.txt":
                    tmp_link = sub_dir / "target.txt.lnk"
                    if tmp_link.exists() or tmp_link.is_symlink():
                        tmp_link.unlink()
                    os.symlink(outside_secret, tmp_link)
                    os.replace(tmp_link, target_file)
                return orig_open(path, flags, dir_fd=dir_fd)

            with mock.patch.object(
                adapter, "_os_open", side_effect=swap_target_before_file_open
            ):
                with self.assertRaises(UnsafePathError):
                    adapter.read_bytes(FileRef("src", "p/sub/target.txt"))

            # Restore safe target_file for Part 2
            target_file.unlink()
            target_file.write_bytes(b"SAFE_PAYLOAD_2")

            # Part 2: Mid-traversal rename of `sub` + replacement with symlink to outside_dir
            moved_sub = self.root_dir / "sub_moved"

            def swap_parent_dir_after_parent_open(
                path: str, flags: int, *, dir_fd: int | None = None
            ) -> int:
                if path == "target.txt":
                    os.rename(sub_dir, moved_sub)
                    os.symlink(self.outside_dir, sub_dir)
                return orig_open(path, flags, dir_fd=dir_fd)

            with mock.patch.object(
                adapter,
                "_os_open",
                side_effect=swap_parent_dir_after_parent_open,
            ):
                data = adapter.read_bytes(FileRef("src", "p/sub/target.txt"))
                self.assertEqual(data, b"SAFE_PAYLOAD_2")

    # -- directory swapped for an outside symlink immediately before its open --
    #
    # These are deterministic mechanism proofs of the atomic-open strategy: the
    # hook fires inside the _os_open call for the component, i.e. after any
    # check and immediately before the kernel open. On the chosen strategy the
    # kernel rejects the swapped symlink atomically with ELOOP, so no outside
    # data, metadata or listing is ever exposed. They assert outcomes (and fail
    # if the operation returns outside content) rather than printing.

    SENTINEL_BYTES = b"OUTSIDE_SENTINEL_BYTES_0123456789"

    def _reset_fixture(self) -> None:
        shutil.rmtree(self.root_dir, ignore_errors=True)
        shutil.rmtree(self.outside_dir, ignore_errors=True)
        self.root_dir.mkdir()
        self.outside_dir.mkdir()

    def _assert_contained(self, operation) -> None:
        """Assert ``operation`` raises UnsafePathError and exposes nothing."""
        try:
            result = operation()
        except UnsafePathError:
            return
        except Exception as exc:  # noqa: BLE001
            self.fail(
                f"expected UnsafePathError, got {type(exc).__name__}: {exc}"
            )
        self.fail(
            f"expected UnsafePathError, but the operation returned {result!r} "
            "(outside data exposed)"
        )

    def _make_swap_hook(self, adapter, real_sub, outside):
        """Return an _os_open hook that swaps ``real_sub`` for a symlink."""
        orig_open = adapter._os_open
        state = {"done": False}

        def hook(path: str, flags: int, *, dir_fd: int | None = None) -> int:
            if path == "sub" and not state["done"]:
                state["done"] = True
                os.rename(real_sub, str(real_sub) + "__moved")
                os.symlink(outside, real_sub)
            return orig_open(path, flags, dir_fd=dir_fd)

        return hook

    def _build_sub_fixture(self):
        self._reset_fixture()
        sub = self.root_dir / "sub"
        sub.mkdir()
        (sub / "target.txt").write_bytes(b"SAFE_INSIDE")
        (self.outside_dir / "target.txt").write_bytes(self.SENTINEL_BYTES)
        (self.outside_dir / "secret.txt").write_bytes(b"OUTSIDE_SECRET_ONLY")
        return sub

    def test_dir_swap_before_component_open_read_traversal_rejected(self) -> None:
        sub = self._build_sub_fixture()
        adapter = LocalAdapter("src", self.root_dir)
        try:
            hook = self._make_swap_hook(adapter, sub, self.outside_dir)
            with mock.patch.object(adapter, "_os_open", side_effect=hook):
                self._assert_contained(
                    lambda: adapter.read_bytes(
                        FileRef("src", "p/sub/target.txt")
                    )
                )
        finally:
            adapter.close()

    def test_dir_swap_before_component_open_stat_traversal_rejected(self) -> None:
        sub = self._build_sub_fixture()
        adapter = LocalAdapter("src", self.root_dir)
        try:
            hook = self._make_swap_hook(adapter, sub, self.outside_dir)
            with mock.patch.object(adapter, "_os_open", side_effect=hook):
                self._assert_contained(
                    lambda: adapter.stat(FileRef("src", "p/sub/target.txt"))
                )
        finally:
            adapter.close()

    def test_dir_swap_before_list_children_final_open_rejected(self) -> None:
        sub = self._build_sub_fixture()
        adapter = LocalAdapter("src", self.root_dir)
        try:
            hook = self._make_swap_hook(adapter, sub, self.outside_dir)
            with mock.patch.object(adapter, "_os_open", side_effect=hook):
                self._assert_contained(
                    lambda: adapter.list_children(FileRef("src", "p/sub"))
                )
        finally:
            adapter.close()

    def test_dir_swap_before_ancestor_open_rejected_at_root_setup(self) -> None:
        self._reset_fixture()
        anc = self.base_dir / "anc"
        anc.mkdir()
        inner = anc / "inner"
        inner.mkdir()
        outside_target = self.outside_dir / "anc_target"
        outside_target.mkdir()
        (outside_target / "leak.txt").write_bytes(self.SENTINEL_BYTES)

        state = {"done": False}

        def hook(self_, path: str, flags: int, *, dir_fd: int | None = None) -> int:
            if path == "anc" and not state["done"]:
                state["done"] = True
                os.rename(anc, self.base_dir / "anc__moved")
                os.symlink(outside_target, anc)
            return os.open(path, flags, dir_fd=dir_fd)

        with mock.patch.object(LocalAdapter, "_os_open", hook):
            with self.assertRaises(UnsafePathError):
                LocalAdapter("src", inner)

class TestBoundedReads(_PosixTempRootTestCase):
    """Tests for max_read_bytes threshold enforcement and concurrent file growth."""

    def test_read_limit_below_exact_and_above_threshold(self) -> None:
        (self.root_dir / "below.bin").write_bytes(b"a" * 15)
        (self.root_dir / "exact.bin").write_bytes(b"b" * 16)
        (self.root_dir / "above.bin").write_bytes(b"c" * 17)

        with LocalAdapter("src", self.root_dir, max_read_bytes=16) as adapter:
            self.assertEqual(
                adapter.read_bytes(FileRef("src", "p/below.bin")), b"a" * 15
            )
            self.assertEqual(
                adapter.read_bytes(FileRef("src", "p/exact.bin")), b"b" * 16
            )

            with mock.patch.object(
                adapter, "_os_read", wraps=adapter._os_read
            ) as spy_read:
                with self.assertRaises(ReadLimitExceededError):
                    adapter.read_bytes(FileRef("src", "p/above.bin"))
                # Rejected immediately by fstat check before any os.read call
                spy_read.assert_not_called()

    def test_simulated_file_growth_after_fstat_reads_at_most_limit_plus_one(
        self,
    ) -> None:
        """Proves a file growing after fstat cannot bypass max_read_bytes."""
        growing_file = self.root_dir / "grow.bin"
        growing_file.write_bytes(b"0123456789")  # 10 bytes initially

        with LocalAdapter("src", self.root_dir, max_read_bytes=16) as adapter:
            orig_fstat = adapter._os_fstat
            orig_read = adapter._os_read
            bytes_read_from_os = 0

            def fstat_then_append(fd: int) -> os.stat_result:
                st = orig_fstat(fd)
                # Append 100 extra bytes to the underlying file after fstat succeeds
                with open(growing_file, "ab") as writer:
                    writer.write(b"X" * 100)
                return st

            def counting_read(fd: int, length: int) -> bytes:
                nonlocal bytes_read_from_os
                chunk = orig_read(fd, length)
                bytes_read_from_os += len(chunk)
                return chunk

            with (
                mock.patch.object(
                    adapter, "_os_fstat", side_effect=fstat_then_append
                ),
                mock.patch.object(
                    adapter, "_os_read", side_effect=counting_read
                ),
            ):
                with self.assertRaises(ReadLimitExceededError):
                    adapter.read_bytes(FileRef("src", "p/grow.bin"))

            # At most max_read_bytes + 1 (17) bytes were read from the descriptor
            self.assertEqual(bytes_read_from_os, 17)

    def test_multi_chunk_streaming_growth_seam(self) -> None:
        """Proves chunked reading caps total bytes requested at max_read_bytes + 1."""
        small_file = self.root_dir / "stream.bin"
        small_file.write_bytes(b"init")

        with LocalAdapter("src", self.root_dir, max_read_bytes=16) as adapter:
            requested_lengths: list[int] = []
            total_returned = 0

            def fake_streaming_read(fd: int, length: int) -> bytes:
                nonlocal total_returned
                requested_lengths.append(length)
                # Simulate small 6-byte reads from an endlessly growing file
                chunk = b"z" * min(6, length)
                total_returned += len(chunk)
                return chunk

            with mock.patch.object(
                adapter, "_os_read", side_effect=fake_streaming_read
            ):
                with self.assertRaises(ReadLimitExceededError):
                    adapter.read_bytes(FileRef("src", "p/stream.bin"))

            # 6 + 6 + 5 = 17 bytes total (max_read_bytes + 1)
            self.assertEqual(total_returned, 17)
            self.assertEqual(requested_lengths, [17, 11, 5])

class TestSpecialEntriesAndNonblockingFifo(_PosixTempRootTestCase):
    """Tests that FIFOs and sockets are rejected without hanging and omitted from listing."""

    def test_fifo_rejected_without_blocking_in_bounded_subprocess(self) -> None:
        if not hasattr(os, "mkfifo"):
            self.skipTest("os.mkfifo is not available on this platform")

        fifo_path = self.root_dir / "test_pipe.fifo"
        try:
            os.mkfifo(fifo_path)
        except OSError as exc:
            self.skipTest(f"filesystem does not support mkfifo: {exc}")

        (self.root_dir / "normal.txt").write_bytes(b"ok")

        # Run in a child process with a strict timeout to guarantee no hang occurs
        repo_root = str(Path(__file__).resolve().parents[1])
        script = (
            "import sys\n"
            f"sys.path.insert(0, {repo_root!r})\n"
            "from drive_tool.local import LocalAdapter, UnsupportedEntryError\n"
            "from drive_tool.storage import FileRef, ROOT_ID\n"
            f"with LocalAdapter('src', {str(self.root_dir)!r}) as adapter:\n"
            "    children = adapter.list_children(FileRef('src', ROOT_ID))\n"
            "    assert [c.name for c in children] == ['normal.txt'], children\n"
            "    for fn in (adapter.stat, adapter.read_bytes, adapter.list_children):\n"
            "        try:\n"
            "            fn(FileRef('src', 'p/test_pipe.fifo'))\n"
            "        except UnsupportedEntryError:\n"
            "            pass\n"
            "        else:\n"
            "            raise AssertionError('Expected UnsupportedEntryError')\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
        self.assertEqual(
            proc.returncode,
            0,
            msg=f"FIFO subprocess failed: stdout={proc.stdout!r}, stderr={proc.stderr!r}",
        )

    def test_unix_socket_rejected_and_omitted_from_listing(self) -> None:
        if not hasattr(socket, "AF_UNIX"):
            self.skipTest("AF_UNIX sockets not available on this platform")

        # Use a short path inside root_dir for AF_UNIX sun_path length limits
        sock_path = self.root_dir / "s.sock"
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            try:
                srv.bind(str(sock_path))
            except OSError as exc:
                self.skipTest(f"cannot bind AF_UNIX socket in temp root: {exc}")

            (self.root_dir / "regular.txt").write_bytes(b"data")
            with LocalAdapter("src", self.root_dir) as adapter:
                with self.assertRaises(UnsupportedEntryError):
                    adapter.stat(FileRef("src", "p/s.sock"))
                with self.assertRaises(UnsupportedEntryError):
                    adapter.read_bytes(FileRef("src", "p/s.sock"))
                with self.assertRaises(UnsupportedEntryError):
                    adapter.list_children(FileRef("src", "p/s.sock"))

                listing = adapter.list_children(FileRef("src", ROOT_ID))
                self.assertEqual([m.name for m in listing], ["regular.txt"])
        finally:
            srv.close()

class TestDescriptorLifetimeAndClose(_PosixTempRootTestCase):
    """Tests for close(), context manager cleanup, and descriptor leak prevention."""

    def test_close_idempotency_and_operations_after_close(self) -> None:
        (self.root_dir / "file.txt").write_bytes(b"data")
        adapter = LocalAdapter("src", self.root_dir)
        adapter.close()
        adapter.close()  # Idempotent second call

        for method in (adapter.stat, adapter.list_children, adapter.read_bytes):
            with self.assertRaises(AdapterClosedError):
                method(FileRef("src", ROOT_ID))

        with self.assertRaises(AdapterClosedError):
            with adapter:
                pass

    def test_deterministic_descriptor_accounting_across_success_and_failures(
        self,
    ) -> None:
        sub = self.root_dir / "a" / "b"
        sub.mkdir(parents=True)
        (sub / "file.txt").write_bytes(b"hello world")
        (sub / "big.txt").write_bytes(b"x" * 100)
        os.symlink(self.outside_dir, sub / "sym")

        active_fds: set = set()
        orig_open = os.open
        orig_close = os.close
        orig_scandir = os.scandir

        class _TrackedScandirWrapper:
            """Wrap os.scandir(fd) while modelling its internal dup.

            ``os.scandir(fd)`` duplicates ``fd`` internally (CPython _Py_dup
            before fdopendir); its context manager closes the *duplicate* and
            leaves the caller's ``fd`` open. We therefore track the duplicate
            as a distinct token, and only the duplicate is retired on
            ``__exit__``. The caller's ``fd`` stays in ``active_fds`` until
            ``LocalAdapter`` explicitly closes it via ``_os_close`` - so this
            test fails if that explicit close is removed.
            """

            def __init__(self, fd: int) -> None:
                self._fd = fd
                self._inner = orig_scandir(fd)
                self._dup_token = ("scandir_dup", fd)
                active_fds.add(self._dup_token)

            def __enter__(self):
                return self._inner.__enter__()

            def __exit__(self, exc_type, exc_val, exc_tb):
                try:
                    return self._inner.__exit__(exc_type, exc_val, exc_tb)
                finally:
                    # scandir closes its own duplicate, NOT the passed fd.
                    active_fds.discard(self._dup_token)

        def tracked_open(
            path: str, flags: int, *, dir_fd: int | None = None
        ) -> int:
            fd = orig_open(path, flags, dir_fd=dir_fd)
            active_fds.add(fd)
            return fd

        def tracked_close(fd: int) -> None:
            active_fds.discard(fd)
            orig_close(fd)

        with (
            mock.patch.object(LocalAdapter, "_os_open", side_effect=tracked_open),
            mock.patch.object(
                LocalAdapter, "_os_close", side_effect=tracked_close
            ),
            mock.patch.object(
                LocalAdapter,
                "_os_scandir",
                side_effect=_TrackedScandirWrapper,
            ),
        ):
            # Failed init with symlink root leaves zero leaked descriptors
            sym_root = self.base_dir / "bad_sym_root"
            os.symlink(self.root_dir, sym_root)
            with self.assertRaises(UnsafePathError):
                LocalAdapter("src", sym_root)
            self.assertEqual(len(active_fds), 0)

            with LocalAdapter(
                "src", self.root_dir, max_read_bytes=20
            ) as adapter:
                # Only the single anchored root descriptor is retained
                self.assertEqual(len(active_fds), 1)

                for _ in range(10):
                    adapter.stat(FileRef("src", ROOT_ID))
                    adapter.stat(FileRef("src", "p/a/b/file.txt"))
                    adapter.list_children(FileRef("src", ROOT_ID))
                    adapter.list_children(FileRef("src", "p/a/b"))
                    adapter.read_bytes(FileRef("src", "p/a/b/file.txt"))

                    with self.assertRaises(NotFoundError):
                        adapter.read_bytes(FileRef("src", "p/a/b/missing.txt"))
                    with self.assertRaises(UnsafePathError):
                        adapter.stat(FileRef("src", "p/a/b/sym/escape"))
                    with self.assertRaises(ReadLimitExceededError):
                        adapter.read_bytes(FileRef("src", "p/a/b/big.txt"))

                    self.assertEqual(len(active_fds), 1)

            # After exiting the context manager, all descriptors are closed
            self.assertEqual(len(active_fds), 0)

    def test_linux_proc_self_fd_bounded_count(self) -> None:
        proc_fd = Path("/proc/self/fd")
        if not proc_fd.is_dir():
            self.skipTest("/proc/self/fd not available on this platform")

        sub = self.root_dir / "nested"
        sub.mkdir()
        (sub / "data.txt").write_bytes(b"payload")

        baseline_fds = len(os.listdir(proc_fd))
        adapter = LocalAdapter("src", self.root_dir)
        try:
            self.assertEqual(len(os.listdir(proc_fd)), baseline_fds + 1)
            for _ in range(25):
                adapter.stat(FileRef("src", "p/nested/data.txt"))
                adapter.list_children(FileRef("src", "p/nested"))
                adapter.read_bytes(FileRef("src", "p/nested/data.txt"))
                with self.assertRaises(NotFoundError):
                    adapter.stat(FileRef("src", "p/nested/missing"))
            self.assertEqual(len(os.listdir(proc_fd)), baseline_fds + 1)
        finally:
            adapter.close()

        self.assertEqual(len(os.listdir(proc_fd)), baseline_fds)

    def test_list_children_closes_the_scan_descriptor(self) -> None:
        """The explicit scan_fd close must actually be issued.

        scandir dups the descriptor internally, so asserting on the raw scandir
        close is not enough; this spies the adapter's own seam and requires the
        descriptor it opened for scandir to be closed.
        """
        (self.root_dir / "one.txt").write_bytes(b"1")
        with LocalAdapter("src", self.root_dir) as adapter:
            opened: list[int] = []
            closed: list[int] = []
            scan_fds: list[int] = []
            real_open = adapter._os_open
            real_close = adapter._os_close
            real_scandir = adapter._os_scandir

            def spy_open(path, flags, *, dir_fd=None):
                fd = real_open(path, flags, dir_fd=dir_fd)
                opened.append(fd)
                return fd

            def spy_close(fd):
                closed.append(fd)
                return real_close(fd)

            def spy_scandir(fd):
                scan_fds.append(fd)
                return real_scandir(fd)

            with (
                mock.patch.object(adapter, "_os_open", side_effect=spy_open),
                mock.patch.object(adapter, "_os_close", side_effect=spy_close),
                mock.patch.object(
                    adapter, "_os_scandir", side_effect=spy_scandir
                ),
            ):
                adapter.list_children(FileRef("src", ROOT_ID))

            self.assertTrue(scan_fds, "list_children must open a scan descriptor")
            for scan_fd in scan_fds:
                self.assertIn(
                    scan_fd,
                    closed,
                    "list_children must close the descriptor it opened for scandir",
                )
            for fd in opened:
                self.assertIn(fd, closed)

class TestCloseFailureOwnership(_PosixTempRootTestCase):
    """Close-failure ownership: no double-close, no retry, no orphaned fd.

    Linux releases a descriptor even when close() reports an error, so the
    adapter must never retry close on the same fd. When a close fails mid
    traversal the newly opened descriptor must still be cleaned up and the
    failure surfaced as LocalStorageError with its cause preserved.
    """

    def test_traversal_close_failure_cleans_new_fd_without_double_close(self) -> None:
        (self.root_dir / "a").mkdir()
        (self.root_dir / "a" / "b").mkdir()
        (self.root_dir / "a" / "b" / "file.txt").write_bytes(b"data")

        with LocalAdapter("src", self.root_dir) as adapter:
            opened: list[int] = []
            close_calls: list[int] = []
            real_open = adapter._os_open
            real_close = adapter._os_close

            def spy_open(path, flags, *, dir_fd=None):
                fd = real_open(path, flags, dir_fd=dir_fd)
                opened.append(fd)
                return fd

            def flaky_close(fd):
                close_calls.append(fd)
                # Model Linux semantics: close() releases the descriptor even
                # when it reports an error.
                real_close(fd)
                if len(close_calls) == 1:
                    raise OSError(errno.EIO, "injected close failure")

            with (
                mock.patch.object(adapter, "_os_open", side_effect=spy_open),
                mock.patch.object(adapter, "_os_close", side_effect=flaky_close),
            ):
                with self.assertRaises(LocalStorageError) as cm:
                    adapter.read_bytes(FileRef("src", "p/a/b/file.txt"))

            self.assertIsInstance(cm.exception.__cause__, OSError)
            self.assertEqual(cm.exception.__cause__.errno, errno.EIO)
            # No descriptor is closed twice...
            self.assertEqual(len(close_calls), len(set(close_calls)))
            # ...and every descriptor opened during the operation is released.
            self.assertEqual(set(opened), set(close_calls))
            for fd in opened:
                with self.assertRaises(OSError):
                    os.fstat(fd)

    def test_root_setup_close_failure_cleans_new_fd_without_double_close(self) -> None:
        anc = self.base_dir / "x"
        anc.mkdir()
        inner = anc / "y"
        inner.mkdir()

        opened: list[int] = []
        close_calls: list[int] = []
        real_open = os.open
        real_close = os.close

        def spy_open(path, flags, *, dir_fd=None):
            fd = real_open(path, flags, dir_fd=dir_fd)
            opened.append(fd)
            return fd

        def flaky_close(fd):
            close_calls.append(fd)
            real_close(fd)
            if len(close_calls) == 1:
                raise OSError(errno.EIO, "injected close failure")

        with (
            mock.patch.object(LocalAdapter, "_os_open", side_effect=spy_open),
            mock.patch.object(LocalAdapter, "_os_close", side_effect=flaky_close),
        ):
            with self.assertRaises(LocalStorageError) as cm:
                LocalAdapter("src", inner)

        self.assertIsInstance(cm.exception.__cause__, OSError)
        self.assertEqual(cm.exception.__cause__.errno, errno.EIO)
        self.assertEqual(len(close_calls), len(set(close_calls)))
        self.assertEqual(set(opened), set(close_calls))
        for fd in opened:
            with self.assertRaises(OSError):
                os.fstat(fd)

class TestOsErrorWrapping(_PosixTempRootTestCase):
    """Injected OS failures surface as LocalStorageError with cause + cleanup."""

    def test_scandir_iteration_error_wrapped_and_scan_fd_closed(self) -> None:
        (self.root_dir / "keep.txt").write_bytes(b"k")
        with LocalAdapter("src", self.root_dir) as adapter:
            scan_fd_holder: dict = {}

            class _FailingIter:
                def __enter__(self):
                    return self

                def __iter__(self):
                    return self

                def __next__(self):
                    raise OSError(errno.EIO, "injected readdir failure")

                def __exit__(self, exc_type, exc_val, exc_tb):
                    return False

            def fake_scandir(fd):
                scan_fd_holder["fd"] = fd
                return _FailingIter()

            closed: list[int] = []
            real_close = adapter._os_close

            def spy_close(fd):
                closed.append(fd)
                return real_close(fd)

            with (
                mock.patch.object(adapter, "_os_scandir", side_effect=fake_scandir),
                mock.patch.object(adapter, "_os_close", side_effect=spy_close),
            ):
                with self.assertRaises(LocalStorageError) as cm:
                    adapter.list_children(FileRef("src", ROOT_ID))

            self.assertIsInstance(cm.exception.__cause__, OSError)
            self.assertEqual(cm.exception.__cause__.errno, errno.EIO)
            self.assertIn(scan_fd_holder["fd"], closed)

    def test_traversal_fstat_error_wrapped_and_fds_cleaned(self) -> None:
        (self.root_dir / "a").mkdir()
        (self.root_dir / "a" / "b").mkdir()
        (self.root_dir / "a" / "b" / "f.txt").write_bytes(b"x")

        with LocalAdapter("src", self.root_dir) as adapter:
            opened: list[int] = []
            closed: list[int] = []
            real_open = adapter._os_open
            real_close = adapter._os_close
            real_fstat = adapter._os_fstat
            fstat_calls = {"n": 0}

            def spy_open(path, flags, *, dir_fd=None):
                fd = real_open(path, flags, dir_fd=dir_fd)
                opened.append(fd)
                return fd

            def spy_close(fd):
                closed.append(fd)
                return real_close(fd)

            def flaky_fstat(fd):
                fstat_calls["n"] += 1
                st = real_fstat(fd)
                if fstat_calls["n"] == 2:
                    raise OSError(errno.EIO, "injected fstat failure")
                return st

            with (
                mock.patch.object(adapter, "_os_open", side_effect=spy_open),
                mock.patch.object(adapter, "_os_close", side_effect=spy_close),
                mock.patch.object(adapter, "_os_fstat", side_effect=flaky_fstat),
            ):
                with self.assertRaises(LocalStorageError) as cm:
                    adapter.read_bytes(FileRef("src", "p/a/b/f.txt"))

            self.assertIsInstance(cm.exception.__cause__, OSError)
            self.assertEqual(cm.exception.__cause__.errno, errno.EIO)
            self.assertEqual(set(opened), set(closed))
            self.assertEqual(len(closed), len(set(closed)))

    def test_root_fstat_error_wrapped_and_root_fd_closed(self) -> None:
        opened: list[int] = []
        closed: list[int] = []

        def spy_open(path, flags, *, dir_fd=None):
            fd = os.open(path, flags, dir_fd=dir_fd)
            opened.append(fd)
            return fd

        def spy_close(fd):
            closed.append(fd)
            os.close(fd)

        def flaky_fstat(fd):
            raise OSError(errno.EACCES, "injected fstat failure")

        with (
            mock.patch.object(LocalAdapter, "_os_open", side_effect=spy_open),
            mock.patch.object(LocalAdapter, "_os_close", side_effect=spy_close),
            mock.patch.object(LocalAdapter, "_os_fstat", side_effect=flaky_fstat),
        ):
            with self.assertRaises(LocalStorageError) as cm:
                LocalAdapter("src", self.root_dir)

        self.assertIsInstance(cm.exception.__cause__, OSError)
        self.assertEqual(cm.exception.__cause__.errno, errno.EACCES)
        self.assertEqual(set(opened), set(closed))


class _OwnershipTracker:
    """Lifetime-accurate descriptor accounting.

    Each acquisition gets a unique token; closes pop the most-recent token for
    that fd number (LIFO, matching the kernel). This identifies descriptor
    lifetimes by acquisition rather than assuming an integer fd uniquely
    identifies one lifetime, so it stays correct even when the kernel reuses a
    freed fd number.
    """

    def __init__(self) -> None:
        self._next = 0
        self._stacks: dict = {}
        self._info: dict = {}
        self.released: list = []
        self.close_without_open: int = 0

    def on_open(self, fd: int, dir_fd):
        token = self._next
        self._next += 1
        self._info[token] = (fd, dir_fd)
        self._stacks.setdefault(fd, []).append(token)
        return token

    def on_close(self, fd: int):
        stack = self._stacks.get(fd)
        if not stack:
            self.close_without_open += 1
            return None
        token = stack.pop()
        self.released.append(token)
        return token

    def last_token_for(self, fd: int):
        stack = self._stacks.get(fd)
        return stack[-1] if stack else None

    def release_count(self, token) -> int:
        return self.released.count(token)

    def open_tokens(self) -> list:
        return [t for stack in self._stacks.values() for t in stack]

    def token_for(self, predicate):
        for token, (fd, dir_fd) in self._info.items():
            if predicate(token, fd, dir_fd):
                return token
        return None


class TestChildDescriptorOwnershipHandoff(_PosixTempRootTestCase):
    """Child descriptors must be released exactly once across the parent-close
    handoff, including when the parent close fails after the child is acquired.

    Regression for the base-revision leak: in read_bytes/list_children the
    parent fd is closed in a ``finally`` that runs after the child fd is
    acquired; a failing parent close exited before the child's cleanup scope,
    orphaning the child. Descriptors are identified by acquisition, not by
    assuming an integer fd uniquely identifies a lifetime.
    """

    def _make_tree(self) -> None:
        (self.root_dir / "a").mkdir()
        (self.root_dir / "a" / "file.txt").write_bytes(b"A")
        (self.root_dir / "a" / "b").mkdir()
        (self.root_dir / "a" / "b" / "file.txt").write_bytes(b"AB")
        (self.root_dir / "a" / "b" / "c").mkdir()
        (self.root_dir / "a" / "b" / "c" / "file.txt").write_bytes(b"ABC")

    def _run_handoff(self, op):
        """Run op with the parent-handoff close failing after the child open."""
        self._make_tree()
        adapter = LocalAdapter("src", self.root_dir)
        tracker = _OwnershipTracker()
        parent_box: dict = {}

        real_open = adapter._os_open
        real_close = adapter._os_close
        real_trav = adapter._traverse_parent_dir

        def trav(rfd, dir_parts, file_id):
            fd = real_trav(rfd, dir_parts, file_id)
            parent_box["fd"] = fd
            parent_box["token"] = tracker.last_token_for(fd)
            return fd

        def open_hook(path, flags, *, dir_fd=None):
            fd = real_open(path, flags, dir_fd=dir_fd)
            tracker.on_open(fd, dir_fd)
            return fd

        def close_hook(fd):
            tracker.on_close(fd)
            real_close(fd)  # Linux releases the fd even if close() reports error
            if parent_box.get("fd") == fd:
                raise OSError(errno.EIO, "injected parent-handoff close failure")

        adapter._traverse_parent_dir = trav
        adapter._os_open = open_hook
        adapter._os_close = close_hook
        exc = None
        try:
            try:
                op(adapter)
            except LocalStorageError as e:
                exc = e
        finally:
            adapter._traverse_parent_dir = real_trav
            adapter._os_open = real_open
            adapter._os_close = real_close
        return adapter, tracker, parent_box, exc

    def _assert_handoff_release(self, op) -> None:
        adapter, tracker, parent_box, exc = self._run_handoff(op)
        try:
            self.assertIsNotNone(exc, "operation must surface the close failure")
            self.assertIsInstance(exc.__cause__, OSError)
            self.assertEqual(exc.__cause__.errno, errno.EIO)

            parent_fd = parent_box.get("fd")
            parent_token = parent_box.get("token")
            child_token = tracker.token_for(
                lambda t, fd, dfd: dfd == parent_fd and fd != parent_fd
            )
            self.assertIsNotNone(
                child_token, "child descriptor should have been acquired"
            )
            self.assertEqual(
                tracker.release_count(child_token), 1,
                "child descriptor lifetime must be released exactly once "
                f"(got {tracker.release_count(child_token)})",
            )
            self.assertNotIn(
                child_token, tracker.open_tokens(),
                "child descriptor orphaned (still open)",
            )
            self.assertEqual(
                tracker.close_without_open, 0,
                "a descriptor was closed without a matching acquisition",
            )
            self.assertEqual(
                tracker.open_tokens(), [],
                "descriptors still open after the operation",
            )
            self.assertEqual(
                tracker.release_count(parent_token), 1,
                "parent descriptor must be released exactly once",
            )
            # Root ownership intact: the adapter is still usable.
            self.assertIsNotNone(adapter._root_fd)
            self.assertEqual(
                adapter.read_bytes(FileRef("src", "p/a/file.txt")), b"A"
            )
        finally:
            adapter.close()

    def test_read_bytes_parent_handoff_close_failure_releases_child(self) -> None:
        self._assert_handoff_release(
            lambda a: a.read_bytes(FileRef("src", "p/a/file.txt"))
        )

    def test_read_bytes_deep_parent_handoff_close_failure_releases_child(self) -> None:
        self._assert_handoff_release(
            lambda a: a.read_bytes(FileRef("src", "p/a/b/file.txt"))
        )

    def test_list_children_parent_handoff_close_failure_releases_child(self) -> None:
        self._assert_handoff_release(
            lambda a: a.list_children(FileRef("src", "p/a/b"))
        )

    def test_list_children_deep_parent_handoff_close_failure_releases_child(self) -> None:
        self._assert_handoff_release(
            lambda a: a.list_children(FileRef("src", "p/a/b/c"))
        )

    def test_earlier_traversal_close_failure_leaves_no_child_open(self) -> None:
        """A close failure earlier in traversal must not leak anything either."""
        self._make_tree()
        adapter = LocalAdapter("src", self.root_dir)
        tracker = _OwnershipTracker()
        real_open = adapter._os_open
        real_close = adapter._os_close
        seq = {"n": 0}

        def open_hook(path, flags, *, dir_fd=None):
            fd = real_open(path, flags, dir_fd=dir_fd)
            tracker.on_open(fd, dir_fd)
            return fd

        def close_hook(fd):
            seq["n"] += 1
            tracker.on_close(fd)
            real_close(fd)
            if seq["n"] == 1:
                raise OSError(errno.EIO, "injected first-close failure")

        adapter._os_open = open_hook
        adapter._os_close = close_hook
        exc = None
        try:
            try:
                adapter.read_bytes(FileRef("src", "p/a/b/file.txt"))
            except LocalStorageError as e:
                exc = e
        finally:
            adapter._os_open = real_open
            adapter._os_close = real_close
        try:
            self.assertIsNotNone(exc)
            self.assertIsInstance(exc.__cause__, OSError)
            self.assertEqual(tracker.close_without_open, 0)
            self.assertEqual(tracker.open_tokens(), [])
            self.assertEqual(
                adapter.read_bytes(FileRef("src", "p/a/file.txt")), b"A"
            )
        finally:
            adapter.close()


if __name__ == "__main__":
    unittest.main()
