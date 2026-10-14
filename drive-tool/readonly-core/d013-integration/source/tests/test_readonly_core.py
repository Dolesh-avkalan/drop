"""d013 integration tests: MODULE-002 ListingService over the MODULE-003 LocalAdapter.

Provenance: written for d013 (feature/readonly-core-candidate). These tests drive
the *real* filesystem adapter (``drive_tool.local.LocalAdapter``) through the real
pagination helper (``drive_tool.listing.ListingService``); they deliberately do
NOT re-test each module in isolation (MODULE-002's own tests already cover the
helper over in-memory/fake adapters, and MODULE-003's own tests cover the adapter).
Every check here is observable cross-module behaviour over tiny synthetic
directories created in the sandbox.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import errno
import os
import shutil
import tempfile
import unittest

from drive_tool.listing import MAX_LIMIT, MIN_LIMIT, ListingPage, ListingService
from drive_tool.local import (
    LocalAdapter,
    LocalStorageError,
    _no_follow_semantics_available,
)
from drive_tool.storage import FileRef, SourceMismatchError

SOURCE = "core-src"


def _static_ok() -> bool:
    return (
        os.name == "posix"
        and hasattr(os, "O_NOFOLLOW")
        and os.open in getattr(os, "supports_dir_fd", set())
        and os.stat in getattr(os, "supports_dir_fd", set())
    )


class _CoreTestCase(unittest.TestCase):
    """Base case: real synthetic tree, gated on a supported platform."""

    def setUp(self) -> None:
        if not _static_ok():
            self.skipTest("static POSIX dir_fd/O_NOFOLLOW facilities required")
        if not _no_follow_semantics_available():
            self.skipTest(
                "adapter unsupported on this kernel: O_NOFOLLOW not enforced "
                "(runtime probe returned False); integration listing tests are "
                "not meaningful here"
            )
        raw = tempfile.mkdtemp(prefix="d013_core_")
        self.base = os.path.realpath(raw)
        self.root = os.path.join(self.base, "root")
        self.outside = os.path.join(self.base, "outside")
        os.makedirs(os.path.join(self.root, "sub", "deep"))
        os.makedirs(self.outside)
        self._write("root/z.txt", b"z")
        self._write("root/m.txt", b"mmm")
        self._write("root/sub/a.txt", b"a")
        self._write("root/sub/b.txt", b"bb")
        self._write("root/sub/deep/leaf.txt", b"leaf")
        with open(os.path.join(self.outside, "secret.txt"), "wb") as fh:
            fh.write(b"SECRET")
        self.adapter = LocalAdapter(SOURCE, self.root)
        self.service = ListingService(self.adapter)

    def tearDown(self) -> None:
        if hasattr(self, "adapter"):
            self.adapter.close()
        if hasattr(self, "base") and os.path.isdir(self.base):
            shutil.rmtree(self.base, ignore_errors=True)

    def _write(self, rel: str, data: bytes) -> None:
        with open(os.path.join(self.base, rel), "wb") as fh:
            fh.write(data)

    def _names(self, ref, **kw):
        return [m.name for m in self.service.list_page(ref, **kw).items]


class TestNestedMultiPageListings(_CoreTestCase):
    """Multi-page pagination across nested directories via the real adapter."""

    def test_root_pages_cover_all_real_children(self) -> None:
        root = FileRef(SOURCE, "root")
        page1 = self.service.list_page(root, limit=2, offset=0)
        self.assertEqual([m.name for m in page1.items], ["m.txt", "sub"])
        self.assertEqual(page1.next_offset, 2)
        page2 = self.service.list_page(root, limit=2, offset=page1.next_offset)
        self.assertEqual([m.name for m in page2.items], ["z.txt"])
        self.assertIsNone(page2.next_offset)

    def test_subdirectory_pages_one_at_a_time(self) -> None:
        sub = FileRef(SOURCE, "p/sub")
        seen, offset = [], 0
        while True:
            page = self.service.list_page(sub, limit=MIN_LIMIT, offset=offset)
            seen.extend(m.name for m in page.items)
            if page.next_offset is None:
                break
            offset = page.next_offset
        self.assertEqual(seen, ["a.txt", "b.txt", "deep"])

    def test_deep_directory_listing(self) -> None:
        deep = FileRef(SOURCE, "p/sub/deep")
        self.assertEqual(self._names(deep), ["leaf.txt"])

    def test_full_traversal_reconstructs_sorted_listing(self) -> None:
        # Paginate the whole directory at page size 1 and compare to a single
        # large page: the two paths must agree (offset pagination is consistent
        # for a quiescent directory).
        root = FileRef(SOURCE, "root")
        walked, offset = [], 0
        while True:
            page = self.service.list_page(root, limit=1, offset=offset)
            walked.extend(m.name for m in page.items)
            if page.next_offset is None:
                break
            offset = page.next_offset
        single = self._names(root, limit=MAX_LIMIT)
        self.assertEqual(walked, single)


class TestMetadataRefsAndSorting(_CoreTestCase):
    """Sorted metadata with correct parent_id / source_id / file_id refs."""

    def test_nested_metadata_parent_and_refs(self) -> None:
        sub = FileRef(SOURCE, "p/sub")
        items = {m.name: m for m in self.service.list_page(sub, limit=MAX_LIMIT).items}
        self.assertEqual(list(items), ["a.txt", "b.txt", "deep"])  # sorted
        a = items["a.txt"]
        self.assertEqual(a.ref.source_id, SOURCE)
        self.assertEqual(a.ref.file_id, "p/sub/a.txt")
        self.assertEqual(a.parent_id, "p/sub")
        self.assertEqual(a.kind, "file")
        self.assertEqual(a.size_bytes, 1)  # b"a"
        deep = items["deep"]
        self.assertEqual(deep.kind, "directory")
        self.assertIsNone(deep.size_bytes)
        self.assertEqual(deep.ref.file_id, "p/sub/deep")

    def test_top_level_parent_is_root(self) -> None:
        items = {m.name: m for m in self.service.list_page(
            FileRef(SOURCE, "root"), limit=MAX_LIMIT).items}
        self.assertEqual(items["m.txt"].parent_id, "root")
        self.assertEqual(items["sub"].parent_id, "root")
        self.assertEqual(items["m.txt"].ref.file_id, "p/m.txt")
        self.assertEqual(items["m.txt"].size_bytes, 3)

    def test_filtering_over_real_adapter(self) -> None:
        sub = FileRef(SOURCE, "p/sub")
        self.assertEqual(self._names(sub, name_contains=".txt"), ["a.txt", "b.txt"])
        self.assertEqual(self._names(sub, name_contains="eep"), ["deep"])
        self.assertEqual(self._names(sub, name_contains="zzz"), [])

    def test_page_shape_over_real_adapter(self) -> None:
        page = self.service.list_page(FileRef(SOURCE, "root"), limit=1)
        self.assertIsInstance(page, ListingPage)
        self.assertIsInstance(page.items, tuple)


class TestOmittedSpecialEntries(_CoreTestCase):
    """Symlinks and special entries are omitted from real-adapter listings."""

    def test_symlink_and_fifo_omitted(self) -> None:
        os.symlink(os.path.join(self.outside, "secret.txt"),
                   os.path.join(self.root, "link_out"))
        made_fifo = True
        try:
            os.mkfifo(os.path.join(self.root, "pipe"))
        except OSError:
            made_fifo = False
        names = self._names(FileRef(SOURCE, "root"), limit=MAX_LIMIT)
        self.assertEqual(names, ["m.txt", "sub", "z.txt"])
        self.assertNotIn("link_out", names)
        if made_fifo:
            self.assertNotIn("pipe", names)


class TestWrongSourcePropagation(_CoreTestCase):
    """A wrong-source ref surfaces from the adapter through the service unchanged."""

    def test_wrong_source_on_root(self) -> None:
        with self.assertRaises(SourceMismatchError):
            self.service.list_page(FileRef("other-src", "root"))

    def test_wrong_source_on_nested(self) -> None:
        with self.assertRaises(SourceMismatchError):
            self.service.list_page(FileRef("other-src", "p/sub"))

    def test_source_mismatch_is_not_swallowed_by_filtering(self) -> None:
        with self.assertRaises(SourceMismatchError):
            self.service.list_page(FileRef("other-src", "root"), name_contains="a")


class _CountingLocalAdapter(LocalAdapter):
    """Counts list_children calls to prove the service's pre-validation."""

    def __init__(self, *args, **kwargs):
        self.list_calls = 0
        super().__init__(*args, **kwargs)

    def list_children(self, parent):
        self.list_calls += 1
        return super().list_children(parent)


class TestInvalidOptionsAvoidAdapterWork(_CoreTestCase):
    """Invalid options raise before any adapter work happens."""

    def setUp(self) -> None:
        super().setUp()
        self.counting = _CountingLocalAdapter(SOURCE, self.root)
        self.counting_service = ListingService(self.counting)

    def tearDown(self) -> None:
        if hasattr(self, "counting"):
            self.counting.close()
        super().tearDown()

    def test_invalid_limit_does_not_touch_adapter(self) -> None:
        for bad in (0, 101, -1, True, False, 1.5, "5", None):
            with self.subTest(limit=bad):
                with self.assertRaises(ValueError):
                    self.counting_service.list_page(FileRef(SOURCE, "root"), limit=bad)
        self.assertEqual(self.counting.list_calls, 0)

    def test_invalid_offset_and_filter_do_not_touch_adapter(self) -> None:
        with self.assertRaises(ValueError):
            self.counting_service.list_page(FileRef(SOURCE, "root"), offset=-1)
        with self.assertRaises(ValueError):
            self.counting_service.list_page(FileRef(SOURCE, "root"), name_contains=7)
        self.assertEqual(self.counting.list_calls, 0)

    def test_valid_call_consults_adapter_once(self) -> None:
        self.counting_service.list_page(FileRef(SOURCE, "root"))
        self.assertEqual(self.counting.list_calls, 1)


class _CloseFailingLocalAdapter(LocalAdapter):
    """Fails the close of the descriptor opened for a chosen path name."""

    def __init__(self, *args, fail_close_name=None, **kwargs):
        self._fail_close_name = fail_close_name
        self._open_paths: dict[int, str] = {}
        super().__init__(*args, **kwargs)

    def _os_open(self, path, flags, *, dir_fd=None):
        fd = super()._os_open(path, flags, dir_fd=dir_fd)
        self._open_paths[fd] = path
        return fd

    def _os_close(self, fd):
        name = self._open_paths.get(fd)
        super()._os_close(fd)  # real close first (kernel releases the fd)
        if name == self._fail_close_name:
            raise OSError(errno.EIO, "injected listing cleanup close failure")


class TestAdapterListingFailureSurfacesThroughService(_CoreTestCase):
    """A real adapter listing cleanup failure propagates through the service."""

    def test_listing_cleanup_failure_surfaces_unchanged(self) -> None:
        adapter = _CloseFailingLocalAdapter(SOURCE, self.root, fail_close_name="sub")
        try:
            service = ListingService(adapter)
            with self.assertRaises(LocalStorageError) as ctx:
                service.list_page(FileRef(SOURCE, "p/sub"))
            exc = ctx.exception
            # The adapter's storage error must reach the caller unwrapped (not a
            # ValueError, and not re-typed), with its OSError cause preserved.
            self.assertIsInstance(exc, LocalStorageError)
            self.assertNotIsInstance(exc, ValueError)
            self.assertIsInstance(exc.__cause__, OSError)
            self.assertIn("close", str(exc).lower())
        finally:
            adapter.close()


if __name__ == "__main__":
    unittest.main()
