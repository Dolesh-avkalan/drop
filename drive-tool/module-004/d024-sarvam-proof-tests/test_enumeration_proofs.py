"""Adversarial proof tests for the MODULE-004 enumeration rules.

These tests target the exact rules that the existing suites only exercised:
they fail if the implementation takes the forbidden shortcut each rule
forbids (early scan termination, counting skipped names, parent descriptor
release, the two max_results branches, and the omitted-vs-None keyword).
"""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

from drive_tool.listing import ListingService
from drive_tool.local import LocalAdapter, UnsupportedPlatformError
from drive_tool.search import find
from drive_tool.storage import (
    ROOT_ID,
    EnumerationLimitError,
    FileMetadata,
    FileRef,
    StorageError,
)

def _local_supported() -> bool:
    try:
        with tempfile.TemporaryDirectory() as td:
            adapter = LocalAdapter("probe", td)
            adapter.close()
        return True
    except UnsupportedPlatformError:
        return False

_LOCAL_SUPPORTED = _local_supported()

class _CountingScandir:
    """Wraps a scandir iterator, counting yields and close and stat calls."""

    def __init__(self, inner, counters):
        self._inner = inner
        self._counters = counters

    def __iter__(self):
        return self

    def __next__(self):
        entry = next(self._inner)
        self._counters["yielded"] += 1
        return _CountingEntry(entry, self._counters)

    def close(self):
        self._counters["closed"] += 1
        return self._inner.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self._counters["exit"] += 1
        self.close()
        return False

class _CountingEntry:
    def __init__(self, inner, counters):
        self._inner = inner
        self._counters = counters

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def stat(self, *, follow_symlinks=True):
        self._counters["stat"] += 1
        return self._inner.stat(follow_symlinks=follow_symlinks)

@unittest.skipUnless(_LOCAL_SUPPORTED, "LocalAdapter unsupported on this platform")
class EnumerationProofTests(unittest.TestCase):
    def _adapter(self, root, **kwargs):
        return LocalAdapter("src", str(root), **kwargs)

    # -- Nit 1: the scan stops early ---------------------------------------

    def test_scan_stops_early_on_limit(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for i in range(10):
                (root / f"f{i:02d}.txt").write_text("x")
            adapter = self._adapter(root)
            counters = {"yielded": 0, "stat": 0, "closed": 0, "exit": 0}
            inner_scandir = adapter._os_scandir

            def counting_scandir(fd):
                return _CountingScandir(inner_scandir(fd), counters)

            adapter._os_scandir = counting_scandir
            try:
                with self.assertRaises(EnumerationLimitError) as cm:
                    adapter.list_children(FileRef("src", ROOT_ID), max_entries=3)
                self.assertEqual(cm.exception.limit, 3)
                # At most limit + 1 entries are ever pulled from the scan.
                self.assertLessEqual(counters["yielded"], 4)
                # The 4th entry is rejected before any stat on it.
                self.assertLessEqual(counters["stat"], 3)
                self.assertGreaterEqual(counters["closed"], 1)
                self.assertGreaterEqual(counters["exit"], 1)
            finally:
                adapter.close()

    # -- Nit 2: a backslash name counts and is omitted ---------------------

    def test_backslash_name_counts_toward_limit_and_is_omitted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.txt").write_text("x")
            (root / "b.txt").write_text("x")
            (root / "odd\\name.txt").write_text("x")

            # 3 scanned entries, limit 2: the backslash entry must count.
            adapter = self._adapter(root, max_list_entries=2)
            try:
                with self.assertRaises(EnumerationLimitError) as cm:
                    adapter.list_children(FileRef("src", ROOT_ID))
                self.assertEqual(cm.exception.limit, 2)
            finally:
                adapter.close()

            # Limit 3 passes, and the backslash entry is still omitted.
            adapter = self._adapter(root, max_list_entries=3)
            try:
                children = adapter.list_children(FileRef("src", ROOT_ID))
                self.assertEqual(
                    sorted(c.name for c in children), ["a.txt", "b.txt"]
                )
                self.assertNotIn("odd\\name.txt", [c.name for c in children])
            finally:
                adapter.close()

    # -- Nit 3: no descriptor leak listing a NESTED directory --------------

    @unittest.skipUnless(
        sys.platform.startswith("linux"), "Linux /proc/self/fd only"
    )
    def test_no_fd_leak_on_repeated_limit_errors_in_nested_directory(self):
        if not os.path.isdir("/proc/self/fd"):
            self.skipTest("/proc/self/fd not available")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sub" / "leaf").mkdir(parents=True)
            for i in range(10):
                (root / "sub" / "leaf" / f"f{i}.txt").write_text("x")
            adapter = self._adapter(root)
            ref = FileRef("src", "p/sub/leaf")
            try:
                with self.assertRaises(EnumerationLimitError):
                    adapter.list_children(ref, max_entries=2)
                before = len(os.listdir("/proc/self/fd"))
                for _ in range(50):
                    with self.assertRaises(EnumerationLimitError):
                        adapter.list_children(ref, max_entries=2)
                after = len(os.listdir("/proc/self/fd"))
                self.assertEqual(before, after)
            finally:
                adapter.close()

    # -- Nit 4: find() truncates on the last entry with dirs queued --------

    def test_max_results_on_last_entry_with_child_directory_queued(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a_sub").mkdir()
            (root / "z_match.txt").write_text("x")
            adapter = self._adapter(root)
            try:
                result = find(
                    adapter,
                    FileRef("src", ROOT_ID),
                    "match",
                    max_results=1,
                )
                self.assertEqual(len(result.items), 1)
                self.assertTrue(result.truncated)
                self.assertEqual(result.reason, "max_results")
            finally:
                adapter.close()

    def test_max_results_on_last_entry_with_sibling_directory_remaining(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "p" / "a").mkdir(parents=True)
            (root / "p" / "b").mkdir()
            (root / "p" / "a" / "z_match.txt").write_text("x")
            adapter = self._adapter(root)
            try:
                result = find(
                    adapter,
                    FileRef("src", ROOT_ID),
                    "match",
                    max_results=1,
                )
                self.assertEqual(len(result.items), 1)
                self.assertTrue(result.truncated)
                self.assertEqual(result.reason, "max_results")
            finally:
                adapter.close()

    # -- Nit 5: list_page passes max_entries only when given --------------

    def test_list_page_passes_max_entries_only_when_given(self):
        calls: list[dict] = []

        class RecordingAdapter:
            source_id = "rec"

            def list_children(self, parent, **kwargs):
                calls.append(dict(kwargs))
                return []

            def stat(self, ref):
                raise NotImplementedError

            def read_bytes(self, ref):
                raise NotImplementedError

        svc = ListingService(RecordingAdapter())
        ref = FileRef("rec", ROOT_ID)
        svc.list_page(ref, max_entries=5)
        svc.list_page(ref)
        self.assertEqual(calls, [{"max_entries": 5}, {}])

if __name__ == "__main__":
    unittest.main()
