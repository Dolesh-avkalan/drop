"""Regression tests for the d035 MODULE-005A review fixes (F-A, F-B, F-C).

These tests were written *before* the corrections and fail against
``593759a40645386427bad35d53e8b856aeaa68d5`` for the intended reasons:

- F-B: a skipped subdirectory produced an unqualified complete result.
- F-A: a malformed ``ScanFailure.error`` was rejected only at the root.
- F-C: a post-yield ``StorageError`` from the metadata/stat seam escaped
  ``ScanFailure`` uncharged.

Physical entry order and seam failures are controlled by ``OrderedScanAdapter``;
no test assumes filesystem alphabetical order.
"""

from __future__ import annotations

import errno
import os
import sys
import tempfile
import unittest
from pathlib import Path

from drive_tool.local import LocalAdapter, LocalStorageError, UnsupportedPlatformError
from drive_tool.search import find
from drive_tool.storage import (
    ROOT_ID,
    FileMetadata,
    FileRef,
    NotFoundError,
    ScanBatch,
    ScanFailure,
    StorageError,
)


def _local_supported() -> bool:
    try:
        with tempfile.TemporaryDirectory() as td:
            a = LocalAdapter("probe", td)
            a.close()
        return True
    except UnsupportedPlatformError:
        return False


_LOCAL_SUPPORTED = _local_supported()


# ---------------------------------------------------------------------------
# Deterministic seam (order + scripted failures)
# ---------------------------------------------------------------------------


class _ScanProbe:
    def __init__(self, order=None):
        self.order = order
        self.next_attempts = 0
        self.yielded = 0
        self.stat_calls = 0
        self.stat_error: dict[str, BaseException] = {}
        self.build_error: dict[str, BaseException] = {}
        self.next_error: BaseException | None = None
        self.next_error_after = 0
        self.iterate_error_after: int | None = None
        self.close_error = False


class _ProbeEntry:
    def __init__(self, inner, probe):
        self._inner = inner
        self._probe = probe

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def stat(self, *, follow_symlinks=True):
        self._probe.stat_calls += 1
        exc = self._probe.stat_error.get(self._inner.name)
        if exc is not None:
            raise exc
        return self._inner.stat(follow_symlinks=follow_symlinks)


class _ProbeScandir:
    def __init__(self, inner, probe):
        self._inner = inner
        self._probe = probe
        self._it = None

    def __enter__(self):
        self._inner.__enter__()
        entries = list(self._inner)
        if self._probe.order is not None:
            rank = {name: i for i, name in enumerate(self._probe.order)}
            entries.sort(key=lambda e: rank.get(e.name, len(rank)))
        self._it = iter(entries)
        return self

    def __iter__(self):
        return self

    def __next__(self):
        self._probe.next_attempts += 1
        if (
            self._probe.next_error is not None
            and self._probe.yielded >= self._probe.next_error_after
        ):
            raise self._probe.next_error
        after = self._probe.iterate_error_after
        if after is not None and self._probe.yielded >= after:
            raise OSError(errno.EIO, "iteration boom")
        entry = next(self._it)
        self._probe.yielded += 1
        return _ProbeEntry(entry, self._probe)

    def __exit__(self, exc_type, exc, tb):
        result = self._inner.__exit__(exc_type, exc, tb)
        if self._probe.close_error:
            raise OSError(errno.EIO, "scandir close boom")
        return result


class OrderedScanAdapter(LocalAdapter):
    def __init__(self, source_id, root, *, order=None, **kwargs):
        self.probe = _ScanProbe(order=order)
        super().__init__(source_id, root, **kwargs)

    def _os_scandir(self, fd):
        return _ProbeScandir(super()._os_scandir(fd), self.probe)

    def _build_metadata(self, parts, *, kind, size_bytes):
        name = parts[-1] if parts else ""
        exc = self.probe.build_error.get(name)
        if exc is not None:
            raise exc
        return super()._build_metadata(parts, kind=kind, size_bytes=size_bytes)


def _write_files(root: Path, names):
    for name in names:
        (root / name).write_text("x")


# ---------------------------------------------------------------------------
# Scripted adapter for search-level tests
# ---------------------------------------------------------------------------


def _meta(file_id, name, kind="file"):
    return FileMetadata(
        ref=FileRef("fake", file_id),
        name=name,
        parent_id=ROOT_ID,
        kind=kind,
        size_bytes=0 if kind == "file" else None,
    )


class _ScriptedAdapter:
    source_id = "fake"

    def __init__(self, script):
        self._script = script
        self.calls = []

    def scan_children(self, parent, *, max_entries):
        self.calls.append((parent.file_id, max_entries))
        result = self._script.get(parent.file_id, ScanBatch((), 0, True))
        if isinstance(result, BaseException):
            raise result
        return result

    def stat(self, ref):
        raise NotImplementedError

    def read_bytes(self, ref):
        raise NotImplementedError


def _find(script, **kwargs):
    adapter = _ScriptedAdapter(script)
    return find(adapter, FileRef("fake", ROOT_ID), kwargs.pop("needle", "x"), **kwargs), adapter


# ---------------------------------------------------------------------------
# F-B — a skipped folder must not yield an unqualified complete result
# ---------------------------------------------------------------------------


class SkippedCompletenessTests(unittest.TestCase):
    def test_prescan_skipped_subdir_is_not_complete(self):
        bad = _meta("p/bad", "bad", kind="directory")
        script = {ROOT_ID: ScanBatch((bad,), 1, True), "p/bad": NotFoundError("gone")}
        result, _ = _find(script, needle="zzz")
        self.assertEqual(result.items, ())
        self.assertEqual(result.skipped, ("p/bad",))
        self.assertTrue(result.truncated)
        self.assertEqual(result.reason, "skipped")

    def test_midscan_skipped_subdir_is_not_complete(self):
        sub = _meta("p/sub", "sub", kind="directory")
        script = {
            ROOT_ID: ScanBatch((sub,), 1, True),
            "p/sub": ScanFailure(2, LocalStorageError("sub boom")),
        }
        result, _ = _find(script, needle="zzz", max_entries=100)
        self.assertEqual(result.skipped, ("p/sub",))
        self.assertEqual(result.inspected, 3)
        self.assertTrue(result.truncated)
        self.assertEqual(result.reason, "skipped")

    def test_skipped_means_unknown_not_not_found(self):
        bad = _meta("p/bad", "bad", kind="directory")
        script = {ROOT_ID: ScanBatch((bad,), 1, True), "p/bad": NotFoundError("gone")}
        result, _ = _find(script, needle="zzz")
        # Not "searched exhaustively and found nothing".
        self.assertFalse(not result.truncated and result.items == ())
        self.assertEqual(result.reason, "skipped")

    def test_max_results_reason_takes_precedence_over_skipped(self):
        bad = _meta("p/bad", "bad", kind="directory")
        good = _meta("p/good", "good", kind="directory")
        good_children = (
            _meta("p/good/m0.txt", "m0.txt"),
            _meta("p/good/m1.txt", "m1.txt"),
        )
        script = {
            ROOT_ID: ScanBatch((bad, good), 2, True),
            "p/bad": NotFoundError("gone"),
            "p/good": ScanBatch(good_children, 2, True),
        }
        result, _ = _find(script, needle="m0", max_results=1)
        self.assertEqual(result.skipped, ("p/bad",))
        self.assertTrue(result.truncated)
        self.assertEqual(result.reason, "max_results")

    def test_max_depth_reason_takes_precedence_over_skipped(self):
        bad = _meta("p/bad", "bad", kind="directory")
        deep = _meta("p/deep", "deep", kind="directory")
        deep_child = _meta("p/deep/q", "q", kind="directory")
        script = {
            ROOT_ID: ScanBatch((bad, deep), 2, True),
            "p/bad": NotFoundError("gone"),
            "p/deep": ScanBatch((deep_child,), 1, True),
        }
        result, _ = _find(script, needle="zzz", max_depth=1)
        self.assertEqual(result.skipped, ("p/bad",))
        self.assertTrue(result.truncated)
        self.assertEqual(result.reason, "max_depth")

    def test_empty_skipped_truly_exhausted_is_complete(self):
        hit = _meta("m.txt", "m.txt")
        script = {ROOT_ID: ScanBatch((hit,), 1, True)}
        result, _ = _find(script, needle="m")
        self.assertEqual(result.skipped, ())
        self.assertFalse(result.truncated)
        self.assertIsNone(result.reason)
        self.assertEqual([m.name for m in result.items], ["m.txt"])


# ---------------------------------------------------------------------------
# F-A — ScanFailure.error validated at every depth
# ---------------------------------------------------------------------------


class MalformedFailureValidationTests(unittest.TestCase):
    def test_malformed_failure_error_at_root_raises(self):
        script = {ROOT_ID: ScanFailure(1, "not-a-storage-error")}
        with self.assertRaises(StorageError):
            _find(script)

    def test_malformed_failure_error_below_root_raises_not_skipped(self):
        sub = _meta("p/sub", "sub", kind="directory")
        script = {
            ROOT_ID: ScanBatch((sub,), 1, True),
            "p/sub": ScanFailure(1, "not-a-storage-error"),
        }
        with self.assertRaises(StorageError):
            _find(script, max_entries=100)

    def test_valid_root_failure_identity_and_cause_preserved(self):
        original = LocalStorageError("root boom")
        original.__cause__ = OSError(errno.EIO, "underlying")
        script = {ROOT_ID: ScanFailure(2, original)}
        with self.assertRaises(LocalStorageError) as cm:
            _find(script)
        self.assertIs(cm.exception, original)
        self.assertIsInstance(cm.exception.__cause__, OSError)


# ---------------------------------------------------------------------------
# F-C — post-yield StorageError from the metadata/stat seam is charged
# ---------------------------------------------------------------------------


@unittest.skipUnless(_LOCAL_SUPPORTED, "LocalAdapter unsupported on this platform")
class PostYieldStorageErrorTests(unittest.TestCase):
    def _adapter(self, root, order=None):
        return OrderedScanAdapter("src", str(root), order=order)

    def test_metadata_storage_error_after_prefix_is_scanfailure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            names = ["a.txt", "b.txt"]
            _write_files(root, names)
            adapter = self._adapter(root, order=names)
            boom = LocalStorageError("metadata boom")
            adapter.probe.build_error = {"a.txt": boom}
            try:
                with self.assertRaises(ScanFailure) as cm:
                    adapter.scan_children(FileRef("src", ROOT_ID), max_entries=10)
                self.assertEqual(cm.exception.inspected, 1)
                self.assertIs(cm.exception.error, boom)
            finally:
                adapter.close()

    def test_stat_storage_error_after_prefix_is_scanfailure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            names = ["a.txt", "b.txt"]
            _write_files(root, names)
            adapter = self._adapter(root, order=names)
            boom = LocalStorageError("stat seam boom")
            adapter.probe.stat_error = {"b.txt": boom}
            try:
                with self.assertRaises(ScanFailure) as cm:
                    adapter.scan_children(FileRef("src", ROOT_ID), max_entries=10)
                self.assertEqual(cm.exception.inspected, 2)
                self.assertIs(cm.exception.error, boom)
            finally:
                adapter.close()

    def test_storage_error_before_any_entry_is_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_files(root, ["a.txt", "b.txt"])
            adapter = self._adapter(root)
            boom = LocalStorageError("pre-yield boom")
            adapter.probe.next_error = boom
            adapter.probe.next_error_after = 0
            try:
                with self.assertRaises(LocalStorageError) as cm:
                    adapter.scan_children(FileRef("src", ROOT_ID), max_entries=10)
                self.assertNotIsInstance(cm.exception, ScanFailure)
                self.assertIs(cm.exception, boom)
            finally:
                adapter.close()

    def test_next_seam_storage_error_after_prefix_is_scanfailure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            names = ["a.txt", "b.txt", "c.txt"]
            _write_files(root, names)
            adapter = self._adapter(root, order=names)
            boom = LocalStorageError("iteration seam boom")
            adapter.probe.next_error = boom
            adapter.probe.next_error_after = 2
            try:
                with self.assertRaises(ScanFailure) as cm:
                    adapter.scan_children(FileRef("src", ROOT_ID), max_entries=10)
                self.assertEqual(cm.exception.inspected, 2)
                self.assertIs(cm.exception.error, boom)
            finally:
                adapter.close()

    def test_existing_scanfailure_not_double_wrapped(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_files(root, ["a.txt", "b.txt"])
            adapter = self._adapter(root)
            inner = ScanFailure(7, LocalStorageError("inner"))
            adapter.probe.build_error = {"a.txt": inner}
            try:
                with self.assertRaises(ScanFailure) as cm:
                    adapter.scan_children(FileRef("src", ROOT_ID), max_entries=10)
                self.assertIs(cm.exception, inner)
            finally:
                adapter.close()

    def test_metadata_failure_at_root_find_reraises_original(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_files(root, ["a.txt", "b.txt"])
            adapter = self._adapter(root)
            boom = LocalStorageError("root metadata boom")
            adapter.probe.build_error = {"a.txt": boom}
            try:
                with self.assertRaises(LocalStorageError) as cm:
                    find(adapter, FileRef("src", ROOT_ID), "zzz")
                self.assertIs(cm.exception, boom)
            finally:
                adapter.close()

    def test_metadata_failure_below_root_is_skipped_and_charged(self):
        cases = (
            (["sub", "a.txt", "b.txt"], 2),
            (["sub", "b.txt", "a.txt"], 3),
        )
        for order, expected_inspected in cases:
            with self.subTest(order=order, expected_inspected=expected_inspected):
                with tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    (root / "sub").mkdir()
                    _write_files(root / "sub", ["a.txt", "b.txt"])
                    adapter = self._adapter(root, order=order)
                    boom = LocalStorageError("sub metadata boom")
                    adapter.probe.build_error = {"a.txt": boom}
                    try:
                        result = find(adapter, FileRef("src", ROOT_ID), "zzz", max_entries=100)
                        # root (1) + charged sub entries at/after the failure.
                        self.assertEqual(result.inspected, expected_inspected)
                        self.assertEqual(result.skipped, ("p/sub",))
                        self.assertTrue(result.truncated)
                        self.assertEqual(result.reason, "skipped")
                    finally:
                        adapter.close()

    def test_no_sibling_scan_after_failed_work_exhausts_budget(self):
        sub1 = _meta("p/s1", "s1", kind="directory")
        sub2 = _meta("p/s2", "s2", kind="directory")
        script = {
            ROOT_ID: ScanBatch((sub1, sub2), 2, True),
            "p/s1": ScanFailure(1, LocalStorageError("s1 boom")),
        }
        result, adapter = _find(script, needle="zzz", max_entries=3, max_depth=4)
        self.assertEqual(result.inspected, 3)
        self.assertEqual(result.skipped, ("p/s1",))
        self.assertTrue(result.truncated)
        self.assertEqual(result.reason, "max_entries")
        self.assertEqual([c[0] for c in adapter.calls], [ROOT_ID, "p/s1"])

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux /proc/self/fd only")
    def test_primary_and_cleanup_errors_no_leak_no_retry(self):
        if not os.path.isdir("/proc/self/fd"):
            self.skipTest("/proc/self/fd not available")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            names = ["a.txt", "b.txt"]
            _write_files(root, names)
            adapter = self._adapter(root, order=names)
            primary = LocalStorageError("primary boom")
            adapter.probe.stat_error = {"b.txt": primary}

            real_close = adapter._os_close
            leaked = {"fd": None}
            close_calls = {"n": 0}

            def failing_close(fd):
                close_calls["n"] += 1
                if leaked["fd"] is None:
                    leaked["fd"] = fd
                    raise OSError(errno.EIO, "cleanup boom")
                return real_close(fd)

            try:
                adapter._os_close = failing_close
                before = len(os.listdir("/proc/self/fd"))
                with self.assertRaises(ScanFailure) as cm:
                    adapter.scan_children(FileRef("src", ROOT_ID), max_entries=10)
                # The primary error wins; cleanup failure never masks it.
                self.assertIs(cm.exception.error, primary)
                self.assertEqual(cm.exception.inspected, 2)
                # An ambiguous close is never retried for the same fd.
                self.assertEqual(close_calls["n"], 1)
                adapter._os_close = real_close
                if leaked["fd"] is not None:
                    os.close(leaked["fd"])
                # Measured with the adapter still open, so the only difference
                # would be a leaked scan descriptor.
                after = len(os.listdir("/proc/self/fd"))
                self.assertEqual(before, after)
            finally:
                adapter._os_close = real_close
                adapter.close()


if __name__ == "__main__":
    unittest.main()
