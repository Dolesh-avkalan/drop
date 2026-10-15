# d020 (deepseek)

- status: done
- chat: https://chat.deepseek.com/a/chat/s/dadc2cd1-ed7b-4541-a710-2dd71dffed0c
- model: deepseek (deepthink on, search off)
- finished: 2026-10-15T12:54:49Z

## Question

DeepSeek, I'm Claude, leading the drive-tool project. I need you to implement MODULE-004 and its tests. Attached below: the brief (the contract and the exact delivery format), Gemini's design review and test plan (I have reviewed it and accept Gemini's recommended rules 1-7 in its section 1 as my decisions: where they differ from the brief, they win; e.g. an EnumerationLimitError on the starting parent returns a truncated result with reason max_entries instead of raising. Follow its sections 2-4 as the plan), and the current source files.

Deliver exactly in the brief's format:
- `FILE: <path>` then a fenced block with the complete contents, for drive_tool/storage.py, drive_tool/listing.py, drive_tool/search.py, tests/test_enumeration.py and tests/test_search.py.
- For drive_tool/local.py only three `REPLACE IN drive_tool/local.py:` blocks (the import block, __init__, list_children), each naming the exact first line it replaces.
No ellipses, no placeholders, no "rest unchanged" inside a block. Sarvam will apply your output exactly and run the tests; I will review it. You cannot run code, so end with STATUS: GENERATED, TESTS_NOT_RUN and a short list of anything you were unsure about.

(input files: Dolesh-avkalan/drive-tool:tasks/MODULE-004.md@main, Dolesh-avkalan/drop:drive-tool/module-004/d016-argon-design-review.md, Dolesh-avkalan/drive-tool:drive_tool/storage.py@main, Dolesh-avkalan/drive-tool:drive_tool/listing.py@main, Dolesh-avkalan/drive-tool:drive_tool/local.py@main)

## Answer

Looking at this carefully, I need to implement MODULE-004 following the brief and Gemini's design decisions (rules 1-7). Let me work through the exact contract requirements.

Key decisions from Gemini's review I must honor:

- Rule 1: Catch EnumerationLimitError explicitly before StorageError at every depth including depth 0

- Rule 2: EnumerationLimitError.__init__(self, limit, message=None)

- Rule 5: In LocalAdapter.list_children, validate max_entries after _check_source_and_state but before _parse_file_id

- Rule 6: Do not touch __all__ or add constants outside the three replaceable blocks in local.py

- Rule 7: case_sensitive must be validated as bool

Here is the complete delivery.

FILE: drive_tool/storage.py

```python
"""Read-only storage contract and in-memory adapter for the drive tool.

MODULE-001: the smallest useful first module. This file defines the storage
contract (frozen value objects, a StorageAdapter protocol, and a small error
hierarchy) plus an InMemoryAdapter backed by synthetic fixtures.

Python 3.11+, standard library only. No network, no filesystem, no writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, runtime_checkable

__all__ = [
    "FileRef",
    "FileMetadata",
    "StorageAdapter",
    "StorageError",
    "SourceMismatchError",
    "NotFoundError",
    "NotDirectoryError",
    "IsDirectoryError",
    "EnumerationLimitError",
    "InMemoryAdapter",
    "ROOT_ID",
]

#: The synthetic root directory id used by the in-memory adapter.
ROOT_ID = "root"

@dataclass(frozen=True)
class FileRef:
    """An opaque reference to a file (or the synthetic root) in a source."""

    source_id: str
    file_id: str

@dataclass(frozen=True)
class FileMetadata:
    """Metadata for a file or directory.

    ``parent_id`` and ``size_bytes`` are ``None`` for the synthetic root.
    """

    ref: FileRef
    name: str
    parent_id: str | None
    kind: str
    size_bytes: int | None

class StorageError(Exception):
    """Base class for all storage contract errors."""

class SourceMismatchError(StorageError):
    """The reference's source_id does not match the adapter's source."""

class NotFoundError(StorageError):
    """The referenced file_id is unknown to this adapter."""

class NotDirectoryError(StorageError):
    """A directory-only operation was requested on a non-directory."""

class IsDirectoryError(StorageError):
    """A file-only operation was requested on a directory."""

class EnumerationLimitError(StorageError):
    """A directory enumeration exceeded its configured entry limit.

    ``limit`` is the configured maximum that was exceeded.
    """

    def __init__(self, limit: int, message: str | None = None) -> None:
        self.limit = limit
        super().__init__(
            message or f"directory entry count exceeded limit of {limit}"
        )

@runtime_checkable
class StorageAdapter(Protocol):
    """The read-only storage contract.

    Implementations expose a single ``source_id`` and resolve opaque
    ``file_id`` values within it. Every method rejects a mismatched
    ``source_id`` before it inspects the ``file_id``.
    """

    source_id: str

    def stat(self, ref: FileRef) -> FileMetadata:
        """Return metadata for ``ref``."""
        ...

    def list_children(
        self, parent: FileRef, *, max_entries: int | None = None
    ) -> list[FileMetadata]:
        """Return metadata for the direct children of directory ``parent``.

        When ``max_entries`` is not ``None`` it is an upper bound on the
        number of directory entries examined; adapters may raise
        :class:`EnumerationLimitError` when the directory holds more.
        """
        ...

    def read_bytes(self, ref: FileRef) -> bytes:
        """Return the exact bytes stored for file ``ref``."""
        ...

_INVALID_FILENAME_TOKENS = (".", "..", ROOT_ID)
_INVALID_FILENAME_CHARS = ("/", "\\", "\x00")

def _validate_filename(name: object) -> str:
    """Validate a fixture filename, returning it if valid.

    A valid filename is a non-empty string that is not ``"."``, ``".."``,
    or ``"root"`` and that contains no slash, backslash, or NUL.
    """
    if not isinstance(name, str):
        raise ValueError(f"filename must be a string, got {type(name).__name__}")
    if name == "":
        raise ValueError("filename must be non-empty")
    if name in _INVALID_FILENAME_TOKENS:
        raise ValueError(f"filename {name!r} is reserved")
    for char in _INVALID_FILENAME_CHARS:
        if char in name:
            raise ValueError(f"filename {name!r} must not contain {char!r}")
    return name

def _validate_max_entries(max_entries: object) -> None:
    """Validate an optional ``max_entries``: ``None`` or ``int >= 1``."""
    if max_entries is None:
        return
    if isinstance(max_entries, bool) or not isinstance(max_entries, int):
        raise ValueError(
            f"max_entries must be a positive int or None, "
            f"got {type(max_entries).__name__}"
        )
    if max_entries < 1:
        raise ValueError(f"max_entries must be >= 1, got {max_entries}")

class InMemoryAdapter:
    """A read-only adapter over flat synthetic fixtures held in memory.

    ``files`` maps a filename to its exact bytes. The filename is also the
    file's ``file_id``. A synthetic root directory (id ``"root"``) is the
    single parent of every fixture file.
    """

    def __init__(self, source_id: str, files: Mapping[str, bytes]) -> None:
        if not isinstance(source_id, str) or source_id == "":
            raise ValueError("source_id must be a non-empty string")
        if not isinstance(files, Mapping):
            raise ValueError(
                f"files must be a mapping, got {type(files).__name__}"
            )

        # Validate first, then copy, so a bad mapping never half-populates us.
        validated: dict[str, bytes] = {}
        for name, payload in files.items():
            _validate_filename(name)
            if not isinstance(payload, bytes):
                raise ValueError(
                    f"payload for {name!r} must be bytes, "
                    f"got {type(payload).__name__}"
                )
            validated[name] = payload

        self._source_id = source_id
        # Copy the mapping so later external mutation cannot affect us.
        self._files: dict[str, bytes] = dict(validated)

    @property
    def source_id(self) -> str:
        return self._source_id

    # -- internals ---------------------------------------------------------

    def _root_ref(self) -> FileRef:
        return FileRef(self._source_id, ROOT_ID)

    def _root_metadata(self) -> FileMetadata:
        return FileMetadata(
            ref=self._root_ref(),
            name="",
            parent_id=None,
            kind="directory",
            size_bytes=None,
        )

    def _file_metadata(self, name: str) -> FileMetadata:
        return FileMetadata(
            ref=FileRef(self._source_id, name),
            name=name,
            parent_id=ROOT_ID,
            kind="file",
            size_bytes=len(self._files[name]),
        )

    def _check_source(self, ref: FileRef) -> None:
        """Reject a mismatched source_id. Always runs before file_id checks."""
        if not isinstance(ref, FileRef):
            raise TypeError(f"expected FileRef, got {type(ref).__name__}")
        if ref.source_id != self._source_id:
            raise SourceMismatchError(
                f"ref source_id {ref.source_id!r} does not match "
                f"adapter source_id {self._source_id!r}"
            )

    # -- contract ----------------------------------------------------------

    def stat(self, ref: FileRef) -> FileMetadata:
        self._check_source(ref)
        if ref.file_id == ROOT_ID:
            return self._root_metadata()
        if ref.file_id not in self._files:
            raise NotFoundError(f"unknown file_id {ref.file_id!r}")
        return self._file_metadata(ref.file_id)

    def list_children(
        self, parent: FileRef, *, max_entries: int | None = None
    ) -> list[FileMetadata]:
        self._check_source(parent)
        _validate_max_entries(max_entries)
        if parent.file_id == ROOT_ID:
            if max_entries is not None and len(self._files) > max_entries:
                raise EnumerationLimitError(
                    max_entries,
                    f"directory {parent.file_id!r} exceeds limit of "
                    f"{max_entries} entries",
                )
            return [self._file_metadata(name) for name in sorted(self._files)]
        if parent.file_id not in self._files:
            raise NotFoundError(f"unknown file_id {parent.file_id!r}")
        raise NotDirectoryError(f"{parent.file_id!r} is not a directory")

    def read_bytes(self, ref: FileRef) -> bytes:
        self._check_source(ref)
        if ref.file_id == ROOT_ID:
            raise IsDirectoryError(f"{ROOT_ID!r} is a directory, not a file")
        if ref.file_id not in self._files:
            raise NotFoundError(f"unknown file_id {ref.file_id!r}")
        return self._files[ref.file_id]
```

FILE: drive_tool/listing.py

```python
"""Offset-paginated listing helper over the storage contract.

MODULE-002: a small read-only helper layered on the existing ``StorageAdapter``
contract. It adds no connectors and does not modify MODULE-001.

Consistency note
----------------
This is *offset pagination of a fresh listing*, not a consistent snapshot.
Each call re-reads ``adapter.list_children(parent)``, so if files are added,
removed, or renamed between calls, previously returned offsets can shift and a
page may repeat or skip items. Opaque, durable cursors that survive mutation
are explicitly out of scope for this module.

Python 3.11+, standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass

from drive_tool.storage import FileMetadata, FileRef, StorageAdapter

__all__ = ["ListingPage", "ListingService", "MIN_LIMIT", "MAX_LIMIT"]

MIN_LIMIT = 1
MAX_LIMIT = 100

@dataclass(frozen=True)
class ListingPage:
    """One page of listing results.

    ``items`` is an immutable tuple of metadata in sorted order.
    ``next_offset`` is the offset to pass for the next page, or ``None`` when
    the listing is exhausted.
    """

    items: tuple[FileMetadata, ...]
    next_offset: int | None

def _validate_limit(limit: object) -> None:
    # bool is a subclass of int, so reject it explicitly before the int check.
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError(f"limit must be an int, got {type(limit).__name__}")
    if limit < MIN_LIMIT or limit > MAX_LIMIT:
        raise ValueError(f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}, got {limit}")

def _validate_offset(offset: object) -> None:
    if isinstance(offset, bool) or not isinstance(offset, int):
        raise ValueError(f"offset must be an int, got {type(offset).__name__}")
    if offset < 0:
        raise ValueError(f"offset must be >= 0, got {offset}")

def _validate_name_contains(name_contains: object) -> None:
    if name_contains is not None and not isinstance(name_contains, str):
        raise ValueError(
            f"name_contains must be None or str, got {type(name_contains).__name__}"
        )

def _validate_max_entries(max_entries: object) -> None:
    if max_entries is None:
        return
    if isinstance(max_entries, bool) or not isinstance(max_entries, int):
        raise ValueError(
            f"max_entries must be a positive int or None, "
            f"got {type(max_entries).__name__}"
        )
    if max_entries < 1:
        raise ValueError(f"max_entries must be >= 1, got {max_entries}")

class ListingService:
    """Read-only paginated listing over a ``StorageAdapter``."""

    def __init__(self, adapter: StorageAdapter) -> None:
        self._adapter = adapter

    def list_page(
        self,
        parent: FileRef,
        *,
        limit: int = 50,
        offset: int = 0,
        name_contains: str | None = None,
        max_entries: int | None = None,
    ) -> ListingPage:
        """Return one page of the sorted, optionally filtered children of ``parent``.

        Arguments are validated before the adapter is called, so invalid input
        never reaches the adapter. Ordering is by ``(name, source_id, file_id)``.
        Filtering is a case-sensitive substring match applied before pagination.
        ``max_entries`` is passed through to the adapter only when not ``None``,
        so adapters and fakes without the keyword keep working. An
        :class:`~drive_tool.storage.EnumerationLimitError` from the adapter
        propagates unchanged.
        """
        # Validate everything first: bad arguments must not touch the adapter.
        _validate_limit(limit)
        _validate_offset(offset)
        _validate_name_contains(name_contains)
        _validate_max_entries(max_entries)

        # Fresh listing each call; copy before sorting so the adapter's own
        # return value is never mutated. Only pass max_entries when not None.
        if max_entries is None:
            items = list(self._adapter.list_children(parent))
        else:
            items = list(
                self._adapter.list_children(parent, max_entries=max_entries)
            )
        items.sort(key=lambda meta: (meta.name, meta.ref.source_id, meta.ref.file_id))

        if name_contains is not None:
            items = [meta for meta in items if name_contains in meta.name]

        total = len(items)
        if offset > total:
            raise ValueError(
                f"offset {offset} is greater than the filtered length {total}"
            )

        window = items[offset : offset + limit]
        end = offset + len(window)
        next_offset = end if end < total else None
        return ListingPage(items=tuple(window), next_offset=next_offset)
```

FILE: drive_tool/search.py

```python
"""Bounded breadth-first name search over the storage contract.

MODULE-004: :func:`find` walks a storage tree breadth-first, level by level,
and returns matching files and directories while enforcing an entry budget, a
result budget, and a depth bound. It never blocks on a large folder: each
``list_children`` call receives only the remaining entry budget, so a huge
directory is stopped early with ``truncated=True`` rather than fully read.

Python 3.11+, standard library only. No threads, no retries, no sleeps.
"""

from __future__ import annotations

from dataclasses import dataclass

from drive_tool.storage import (
    EnumerationLimitError,
    FileMetadata,
    FileRef,
    StorageAdapter,
    StorageError,
)

__all__ = ["FindResult", "find"]

@dataclass(frozen=True)
class FindResult:
    """The outcome of a bounded :func:`find`.

    ``items`` are the matches in walk order, ``truncated`` is ``True`` when a
    bound stopped the walk (``reason`` names it), ``inspected`` counts the
    entries the adapter returned and the walk examined, and ``skipped`` holds
    the ``file_id`` of every directory that could not be listed.
    """

    items: tuple[FileMetadata, ...]
    truncated: bool
    reason: str | None
    inspected: int
    skipped: tuple[str, ...]

def _validate_int_in_range(
    name: str, value: object, low: int, high: int
) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"{name} must be an int in {low}..{high}, "
            f"got {type(value).__name__}"
        )
    if value < low or value > high:
        raise ValueError(f"{name} must be in {low}..{high}, got {value}")

def find(
    adapter: StorageAdapter,
    parent: FileRef,
    name_contains: str,
    *,
    max_results: int = 20,
    max_entries: int = 5000,
    max_depth: int = 4,
    case_sensitive: bool = False,
) -> FindResult:
    """Return matches for ``name_contains`` in the subtree rooted at ``parent``.

    The walk is breadth-first; directories within a level are visited in name
    order and matches are returned in walk order (shallower first, then by
    name). A match is a substring test on the entry name (casefolded unless
    ``case_sensitive``), and both files and directories can match. All
    arguments are validated before the adapter is called. A non-limit
    ``StorageError`` listing a subdirectory adds its ``file_id`` to
    ``skipped`` and the walk continues; the same error listing ``parent``
    propagates. An :class:`EnumerationLimitError` at any depth, or a reached
    entry budget with directories left, ends the walk with
    ``truncated=True, reason="max_entries"``.
    """
    # -- validate before touching the adapter ------------------------------
    if not isinstance(name_contains, str) or name_contains == "":
        raise ValueError("name_contains must be a non-empty str")
    _validate_int_in_range("max_results", max_results, 1, 100)
    _validate_int_in_range("max_entries", max_entries, 1, 100_000)
    _validate_int_in_range("max_depth", max_depth, 0, 16)
    if not isinstance(case_sensitive, bool):
        raise ValueError(
            f"case_sensitive must be a bool, got {type(case_sensitive).__name__}"
        )

    needle = name_contains if case_sensitive else name_contains.casefold()
    matches: list[FileMetadata] = []
    skipped: list[str] = []
    inspected = 0
    hit_max_depth = False

    # Queue holds (dir_ref, depth) for the current BFS level. Directories for
    # the next depth accumulate in next_level_dirs and are sorted by
    # (name, file_id) before the next level begins.
    current_level: list[tuple[FileRef, int]] = [(parent, 0)]

    while current_level:
        next_level_dirs: list[tuple[FileMetadata, int]] = []

        for idx, (dir_ref, depth) in enumerate(current_level):
            remaining_budget = max_entries - inspected
            if remaining_budget <= 0:
                # Budget exhausted with directories still to open.
                return FindResult(
                    items=tuple(matches),
                    truncated=True,
                    reason="max_entries",
                    inspected=inspected,
                    skipped=tuple(skipped),
                )

            try:
                raw_children = adapter.list_children(
                    dir_ref, max_entries=remaining_budget
                )
            except EnumerationLimitError:
                # Explicit catch before StorageError (it is a subclass):
                # an over-limit directory stops the walk at any depth.
                return FindResult(
                    items=tuple(matches),
                    truncated=True,
                    reason="max_entries",
                    inspected=inspected,
                    skipped=tuple(skipped),
                )
            except StorageError:
                if depth == 0:
                    # The starting parent's own errors propagate.
                    raise
                # A subdirectory that vanished or became unreadable is skipped.
                skipped.append(dir_ref.file_id)
                continue

            children = sorted(
                raw_children, key=lambda m: (m.name, m.ref.file_id)
            )
            more_dirs_at_this_level = (idx + 1) < len(current_level)

            for child_idx, entry in enumerate(children):
                # Defensive guard: a fake adapter that ignores its budget must
                # not let us overshoot the entry limit.
                if inspected >= max_entries:
                    return FindResult(
                        items=tuple(matches),
                        truncated=True,
                        reason="max_entries",
                        inspected=inspected,
                        skipped=tuple(skipped),
                    )

                inspected += 1
                if entry.kind == "directory":
                    if depth < max_depth:
                        next_level_dirs.append((entry, depth + 1))
                    else:
                        hit_max_depth = True

                haystack = (
                    entry.name if case_sensitive else entry.name.casefold()
                )
                if needle in haystack:
                    matches.append(entry)
                    if len(matches) == max_results:
                        more_entries_in_dir = (child_idx + 1) < len(children)
                        more_dirs_queued = (
                            more_dirs_at_this_level or bool(next_level_dirs)
                        )
                        if more_entries_in_dir or more_dirs_queued:
                            return FindResult(
                                items=tuple(matches),
                                truncated=True,
                                reason="max_results",
                                inspected=inspected,
                                skipped=tuple(skipped),
                            )
                        # No more work anywhere: fall through and finish.
                        break

        if len(matches) == max_results:
            break

        next_level_dirs.sort(key=lambda pair: (pair[0].name, pair[0].ref.file_id))
        current_level = [(meta.ref, d) for meta, d in next_level_dirs]

    if hit_max_depth:
        return FindResult(
            items=tuple(matches),
            truncated=True,
            reason="max_depth",
            inspected=inspected,
            skipped=tuple(skipped),
        )

    return FindResult(
        items=tuple(matches),
        truncated=False,
        reason=None,
        inspected=inspected,
        skipped=tuple(skipped),
    )
```

FILE: tests/test_enumeration.py

```python
"""Tests for bounded enumeration (MODULE-004).

Covers LocalAdapter, InMemoryAdapter, and ListingService enumeration limits,
argument validation, check ordering, and descriptor hygiene.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from drive_tool.listing import ListingService
from drive_tool.local import (
    AdapterClosedError,
    LocalAdapter,
    UnsupportedPlatformError,
)
from drive_tool.storage import (
    ROOT_ID,
    EnumerationLimitError,
    FileRef,
    InMemoryAdapter,
    NotDirectoryError,
    SourceMismatchError,
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

def _make_local_adapter(root, **kwargs) -> LocalAdapter:
    return LocalAdapter("src", str(root), **kwargs)

@unittest.skipUnless(_LOCAL_SUPPORTED, "LocalAdapter unsupported on this platform")
class LocalAdapterEnumerationTests(unittest.TestCase):
    def test_limit_exact_passes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for i in range(3):
                (root / f"f{i}.txt").write_text("x")
            adapter = _make_local_adapter(root, max_list_entries=3)
            try:
                children = adapter.list_children(FileRef("src", ROOT_ID))
                self.assertEqual(len(children), 3)
                self.assertEqual(
                    sorted(c.name for c in children),
                    ["f0.txt", "f1.txt", "f2.txt"],
                )
            finally:
                adapter.close()

    def test_limit_exceeded_by_one_raises(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for i in range(4):
                (root / f"f{i}.txt").write_text("x")
            adapter = _make_local_adapter(root, max_list_entries=3)
            try:
                with self.assertRaises(EnumerationLimitError) as cm:
                    adapter.list_children(FileRef("src", ROOT_ID))
                self.assertEqual(cm.exception.limit, 3)
            finally:
                adapter.close()

    def test_symlinks_and_special_entries_count_toward_limit(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.txt").write_text("x")
            (root / "b.txt").write_text("x")
            os.symlink(root / "a.txt", root / "link")
            os.mkfifo(root / "fifo")

            # 4 entries on disk: limit 3 must raise.
            adapter = _make_local_adapter(root, max_list_entries=3)
            try:
                with self.assertRaises(EnumerationLimitError) as cm:
                    adapter.list_children(FileRef("src", ROOT_ID))
                self.assertEqual(cm.exception.limit, 3)
            finally:
                adapter.close()

            # Limit 4 passes; symlink and FIFO are omitted from the result.
            adapter = _make_local_adapter(root, max_list_entries=4)
            try:
                children = adapter.list_children(FileRef("src", ROOT_ID))
                self.assertEqual(sorted(c.name for c in children), ["a.txt", "b.txt"])
            finally:
                adapter.close()

    def test_per_call_max_entries_overrides_default(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for i in range(3):
                (root / f"f{i}.txt").write_text("x")
            adapter = _make_local_adapter(root, max_list_entries=2)
            try:
                ref = FileRef("src", ROOT_ID)
                # Default would raise.
                with self.assertRaises(EnumerationLimitError):
                    adapter.list_children(ref)
                # Per-call override with 3 passes.
                children = adapter.list_children(ref, max_entries=3)
                self.assertEqual(len(children), 3)
                # Per-call override with 1 raises with the tighter limit.
                with self.assertRaises(EnumerationLimitError) as cm:
                    adapter.list_children(ref, max_entries=1)
                self.assertEqual(cm.exception.limit, 1)
            finally:
                adapter.close()

    def test_invalid_limit_values_raise_value_error(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "f.txt").write_text("x")
            for bad in (0, -1, True, False, "5", 1.5):
                with self.assertRaises(ValueError):
                    _make_local_adapter(root, max_list_entries=bad)
            adapter = _make_local_adapter(root)
            try:
                ref = FileRef("src", ROOT_ID)
                for bad in (0, -1, True, False, "5", 1.5):
                    with self.assertRaises(ValueError):
                        adapter.list_children(ref, max_entries=bad)
            finally:
                adapter.close()

    def test_check_order_source_closed_validation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "f.txt").write_text("x")
            adapter = _make_local_adapter(root)
            try:
                # Source mismatch precedes argument validation.
                with self.assertRaises(SourceMismatchError):
                    adapter.list_children(FileRef("other", ROOT_ID), max_entries=0)
                # Open adapter, bad max_entries: ValueError.
                with self.assertRaises(ValueError):
                    adapter.list_children(FileRef("src", ROOT_ID), max_entries=0)
            finally:
                adapter.close()

        with tempfile.TemporaryDirectory() as td2:
            adapter2 = _make_local_adapter(td2)
            adapter2.close()
            # Closed adapter: source mismatch still checked first.
            with self.assertRaises(SourceMismatchError):
                adapter2.list_children(FileRef("other", ROOT_ID), max_entries=0)
            # Closed adapter beats argument validation.
            with self.assertRaises(AdapterClosedError):
                adapter2.list_children(FileRef("src", ROOT_ID), max_entries=0)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux /proc/self/fd only")
    def test_no_fd_leak_on_repeated_limit_errors(self):
        if not os.path.isdir("/proc/self/fd"):
            self.skipTest("/proc/self/fd not available")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for i in range(10):
                (root / f"f{i}.txt").write_text("x")
            adapter = _make_local_adapter(root)
            try:
                ref = FileRef("src", ROOT_ID)
                # Warm up so first-call allocations do not skew the count.
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

class InMemoryAdapterEnumerationTests(unittest.TestCase):
    def _make(self, n: int) -> InMemoryAdapter:
        return InMemoryAdapter("mem", {f"f{i}.txt": b"x" for i in range(n)})

    def test_limit_exact_passes_and_exceeded_raises(self):
        adapter = self._make(3)
        root = FileRef("mem", ROOT_ID)
        self.assertEqual(len(adapter.list_children(root)), 3)
        self.assertEqual(len(adapter.list_children(root, max_entries=3)), 3)
        with self.assertRaises(EnumerationLimitError) as cm:
            adapter.list_children(root, max_entries=2)
        self.assertEqual(cm.exception.limit, 2)

    def test_invalid_values_raise_value_error(self):
        adapter = self._make(1)
        root = FileRef("mem", ROOT_ID)
        for bad in (0, -1, True, False, "5", 1.5):
            with self.assertRaises(ValueError):
                adapter.list_children(root, max_entries=bad)

    def test_source_mismatch_precedes_validation(self):
        adapter = self._make(1)
        with self.assertRaises(SourceMismatchError):
            adapter.list_children(FileRef("other", ROOT_ID), max_entries=0)

    def test_non_directory_parent_still_raises_not_directory(self):
        adapter = self._make(2)
        with self.assertRaises(NotDirectoryError):
            adapter.list_children(FileRef("mem", "f0.txt"), max_entries=1)

class ListingServiceEnumerationTests(unittest.TestCase):
    def test_max_entries_validated_before_adapter(self):
        calls: list[int | None] = []

        class SpyAdapter:
            source_id = "spy"

            def list_children(self, parent, *, max_entries=None):
                calls.append(max_entries)
                return []

            def stat(self, ref):
                raise NotImplementedError

            def read_bytes(self, ref):
                raise NotImplementedError

        svc = ListingService(SpyAdapter())
        ref = FileRef("spy", ROOT_ID)
        for bad in (0, -1, True, False, "5", 1.5):
            with self.assertRaises(ValueError):
                svc.list_page(ref, max_entries=bad)
        self.assertEqual(calls, [])

    def test_max_entries_passed_through_only_when_given(self):
        calls: list[int | None] = []

        class RecordingAdapter:
            source_id = "rec"

            def list_children(self, parent, *, max_entries=None):
                calls.append(max_entries)
                return []

            def stat(self, ref):
                raise NotImplementedError

            def read_bytes(self, ref):
                raise NotImplementedError

        svc = ListingService(RecordingAdapter())
        ref = FileRef("rec", ROOT_ID)
        svc.list_page(ref, max_entries=5)
        svc.list_page(ref)
        self.assertEqual(calls, [5, None])

    def test_enumeration_limit_error_propagates(self):
        class RaisingAdapter:
            source_id = "r"

            def list_children(self, parent, *, max_entries=None):
                raise EnumerationLimitError(7)

            def stat(self, ref):
                raise NotImplementedError

            def read_bytes(self, ref):
                raise NotImplementedError

        svc = ListingService(RaisingAdapter())
        with self.assertRaises(EnumerationLimitError) as cm:
            svc.list_page(FileRef("r", ROOT_ID), max_entries=7)
        self.assertEqual(cm.exception.limit, 7)

    def test_legacy_adapter_without_keyword_works_when_max_entries_none(self):
        class LegacyAdapter:
            source_id = "leg"

            def list_children(self, parent):
                # Deliberately does NOT accept max_entries.
                return []

            def stat(self, ref):
                raise NotImplementedError

            def read_bytes(self, ref):
                raise NotImplementedError

        svc = ListingService(LegacyAdapter())
        page = svc.list_page(FileRef("leg", ROOT_ID))
        self.assertEqual(page.items, ())
        self.assertIsNone(page.next_offset)

if __name__ == "__main__":
    unittest.main()
```

FILE: tests/test_search.py

```python
"""Tests for bounded breadth-first search (MODULE-004)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from drive_tool.local import (
    AdapterClosedError,
    LocalAdapter,
    UnsupportedPlatformError,
)
from drive_tool.search import FindResult, find
from drive_tool.storage import (
    ROOT_ID,
    EnumerationLimitError,
    FileMetadata,
    FileRef,
    NotDirectoryError,
    NotFoundError,
    SourceMismatchError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _local_supported() -> bool:
    try:
        with tempfile.TemporaryDirectory() as td:
            a = LocalAdapter("probe", td)
            a.close()
        return True
    except UnsupportedPlatformError:
        return False

_LOCAL_SUPPORTED = _local_supported()

def _make_local(root, **kwargs) -> LocalAdapter:
    return LocalAdapter("src", str(root), **kwargs)

def _file(file_id, name, parent_id, kind="file", size=0, source_id="fake"):
    return FileMetadata(
        ref=FileRef(source_id, file_id),
        name=name,
        parent_id=parent_id,
        kind=kind,
        size_bytes=size if kind == "file" else None,
    )

class FakeAdapter:
    """Minimal StorageAdapter for search tests.

    ``children_by_id`` maps a ``file_id`` to its list of ``FileMetadata``.
    When ``enforce_limit`` is true, a listing whose length exceeds the
    requested ``max_entries`` raises :class:`EnumerationLimitError`.
    ``raise_on`` maps a ``file_id`` to an exception instance that
    ``list_children`` raises instead of returning. Every call is recorded in
    ``calls`` as ``(file_id, max_entries)``.
    """

    def __init__(
        self, source_id, children_by_id, *, enforce_limit=True, raise_on=None
    ):
        self.source_id = source_id
        self._children = {k: list(v) for k, v in children_by_id.items()}
        self._enforce_limit = enforce_limit
        self._raise_on = dict(raise_on or {})
        self.calls = []

    def list_children(self, parent, *, max_entries=None):
        self.calls.append((parent.file_id, max_entries))
        if parent.source_id != self.source_id:
            raise SourceMismatchError(
                f"source mismatch: {parent.source_id!r} != {self.source_id!r}"
            )
        if parent.file_id in self._raise_on:
            raise self._raise_on[parent.file_id]
        items = list(self._children.get(parent.file_id, []))
        if (
            self._enforce_limit
            and max_entries is not None
            and len(items) > max_entries
        ):
            raise EnumerationLimitError(max_entries)
        return items

    def stat(self, ref):
        raise NotImplementedError

    def read_bytes(self, ref):
        raise NotImplementedError

# ---------------------------------------------------------------------------
# LocalAdapter-backed tests
# ---------------------------------------------------------------------------

@unittest.skipUnless(_LOCAL_SUPPORTED, "LocalAdapter unsupported on this platform")
class FindLocalAdapterTests(unittest.TestCase):
    def test_matches_files_and_dirs_case_modes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "Report.txt").write_text("x")
            (root / "report_dir").mkdir()
            (root / "other.txt").write_text("x")
            adapter = _make_local(root)
            try:
                ref = FileRef("src", ROOT_ID)
                r = find(adapter, ref, "report")
                self.assertEqual(
                    sorted(m.name for m in r.items), ["Report.txt", "report_dir"]
                )
                self.assertFalse(r.truncated)
                self.assertIsNone(r.reason)

                r = find(adapter, ref, "report", case_sensitive=True)
                self.assertEqual([m.name for m in r.items], ["report_dir"])
            finally:
                adapter.close()

    def test_bfs_walk_order(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "root_match_a.txt").write_text("x")
            (root / "root_match_b.txt").write_text("x")
            (root / "a_dir").mkdir()
            (root / "b_dir").mkdir()
            (root / "a_dir" / "deep_a_match.txt").write_text("x")
            (root / "b_dir" / "deep_b_match.txt").write_text("x")
            (root / "a_dir" / "z_dir").mkdir()
            (root / "b_dir" / "c_dir").mkdir()
            (root / "a_dir" / "z_dir" / "z_match.txt").write_text("x")
            (root / "b_dir" / "c_dir" / "c_match.txt").write_text("x")
            adapter = _make_local(root)
            try:
                r = find(adapter, FileRef("src", ROOT_ID), "match")
                self.assertEqual(
                    [m.name for m in r.items],
                    [
                        "root_match_a.txt",
                        "root_match_b.txt",
                        "deep_a_match.txt",
                        "deep_b_match.txt",
                        "c_match.txt",
                        "z_match.txt",
                    ],
                )
                self.assertFalse(r.truncated)
                self.assertIsNone(r.reason)
            finally:
                adapter.close()

    def test_max_depth_zero_and_deeper(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "top.txt").write_text("x")
            (root / "d1").mkdir()
            (root / "d1" / "mid.txt").write_text("x")
            (root / "d1" / "d2").mkdir()
            (root / "d1" / "d2" / "deep.txt").write_text("x")
            adapter = _make_local(root)
            try:
                ref = FileRef("src", ROOT_ID)
                r0 = find(adapter, ref, "txt", max_depth=0)
                self.assertEqual([m.name for m in r0.items], ["top.txt"])
                self.assertTrue(r0.truncated)
                self.assertEqual(r0.reason, "max_depth")

                r1 = find(adapter, ref, "txt", max_depth=1)
                self.assertEqual(
                    sorted(m.name for m in r1.items), ["mid.txt", "top.txt"]
                )
                self.assertTrue(r1.truncated)
                self.assertEqual(r1.reason, "max_depth")

                r3 = find(adapter, ref, "txt", max_depth=3)
                self.assertEqual(
                    sorted(m.name for m in r3.items),
                    ["deep.txt", "mid.txt", "top.txt"],
                )
                self.assertFalse(r3.truncated)
                self.assertIsNone(r3.reason)
            finally:
                adapter.close()

    def test_max_depth_zero_only_files_not_truncated(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.txt").write_text("x")
            (root / "b.txt").write_text("x")
            adapter = _make_local(root)
            try:
                r = find(adapter, FileRef("src", ROOT_ID), "txt", max_depth=0)
                self.assertEqual(
                    sorted(m.name for m in r.items), ["a.txt", "b.txt"]
                )
                self.assertFalse(r.truncated)
                self.assertIsNone(r.reason)
            finally:
                adapter.close()

    def test_max_results_truncation_vs_exact_last_entry(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "m1.txt").write_text("x")
            (root / "m2.txt").write_text("x")
            (root / "m3.txt").write_text("x")
            adapter = _make_local(root)
            try:
                ref = FileRef("src", ROOT_ID)
                r = find(adapter, ref, "m", max_results=2)
                self.assertEqual(len(r.items), 2)
                self.assertTrue(r.truncated)
                self.assertEqual(r.reason, "max_results")
                self.assertEqual(r.inspected, 2)

                r = find(adapter, ref, "m", max_results=3)
                self.assertEqual(len(r.items), 3)
                self.assertFalse(r.truncated)
                self.assertIsNone(r.reason)
                self.assertEqual(r.inspected, 3)
            finally:
                adapter.close()

    def test_max_results_on_last_entry_at_max_depth(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sub_match").mkdir()
            adapter = _make_local(root)
            try:
                r = find(
                    adapter,
                    FileRef("src", ROOT_ID),
                    "match",
                    max_results=1,
                    max_depth=0,
                )
                self.assertEqual(len(r.items), 1)
                self.assertEqual(r.items[0].name, "sub_match")
                self.assertTrue(r.truncated)
                self.assertEqual(r.reason, "max_depth")
                self.assertEqual(r.inspected, 1)
            finally:
                adapter.close()

    def test_max_entries_exact_budget_vs_dirs_remaining(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.txt").write_text("x")
            (root / "b.txt").write_text("x")
            adapter = _make_local(root)
            try:
                r = find(
                    adapter,
                    FileRef("src", ROOT_ID),
                    "txt",
                    max_entries=2,
                    max_depth=2,
                )
                self.assertEqual(len(r.items), 2)
                self.assertFalse(r.truncated)
                self.assertIsNone(r.reason)
                self.assertEqual(r.inspected, 2)
            finally:
                adapter.close()

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.txt").write_text("x")
            (root / "sub").mkdir()
            (root / "sub" / "deep.txt").write_text("x")
            adapter = _make_local(root)
            try:
                r = find(
                    adapter,
                    FileRef("src", ROOT_ID),
                    "txt",
                    max_entries=2,
                    max_depth=2,
                )
                self.assertEqual(r.inspected, 2)
                self.assertTrue(r.truncated)
                self.assertEqual(r.reason, "max_entries")
            finally:
                adapter.close()

    def test_empty_tree(self):
        with tempfile.TemporaryDirectory() as td:
            adapter = _make_local(Path(td))
            try:
                r = find(adapter, FileRef("src", ROOT_ID), "x")
                self.assertEqual(r.items, ())
                self.assertFalse(r.truncated)
                self.assertIsNone(r.reason)
                self.assertEqual(r.inspected, 0)
                self.assertEqual(r.skipped, ())
            finally:
                adapter.close()

    def test_starting_parent_errors_propagate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "f.txt").write_text("x")
            adapter = _make_local(root)
            try:
                with self.assertRaises(NotFoundError):
                    find(adapter, FileRef("src", "p/nope"), "x")
                with self.assertRaises(NotDirectoryError):
                    find(adapter, FileRef("src", "p/f.txt"), "x")
                with self.assertRaises(SourceMismatchError):
                    find(adapter, FileRef("other", ROOT_ID), "x")
            finally:
                adapter.close()

        with tempfile.TemporaryDirectory() as td:
            adapter = _make_local(Path(td))
            adapter.close()
            with self.assertRaises(AdapterClosedError):
                find(adapter, FileRef("src", ROOT_ID), "x")

# ---------------------------------------------------------------------------
# Fake-adapter-backed tests (error injection and budget behaviour)
# ---------------------------------------------------------------------------

class FindFakeAdapterTests(unittest.TestCase):
    def test_large_folder_stops_early_via_adapter_limit(self):
        children = [
            _file(f"f{i}.txt", f"f{i}.txt", ROOT_ID) for i in range(2000)
        ]
        fake = FakeAdapter("fake", {ROOT_ID: children})
        r = find(fake, FileRef("fake", ROOT_ID), "x", max_entries=100)
        self.assertTrue(r.truncated)
        self.assertEqual(r.reason, "max_entries")
        self.assertEqual(r.inspected, 0)
        # The adapter received the remaining budget and nothing more.
        self.assertEqual(fake.calls, [(ROOT_ID, 100)])

    def test_defensive_guard_against_adapter_ignoring_budget(self):
        children = [_file(f"f{i}.txt", f"f{i}.txt", ROOT_ID) for i in range(50)]
        fake = FakeAdapter("fake", {ROOT_ID: children}, enforce_limit=False)
        r = find(fake, FileRef("fake", ROOT_ID), "zzz", max_entries=10)
        self.assertTrue(r.truncated)
        self.assertEqual(r.reason, "max_entries")
        self.assertEqual(r.inspected, 10)

    def test_subdirectory_storage_error_skipped(self):
        bad_id = "p/bad"
        good_id = "p/good"
        root_children = [
            _file(bad_id, "bad", ROOT_ID, kind="directory"),
            _file(good_id, "good", ROOT_ID, kind="directory"),
        ]
        good_children = [_file("p/good/x_match.txt", "x_match.txt", good_id)]
        fake = FakeAdapter(
            "fake",
            {ROOT_ID: root_children, good_id: good_children},
            raise_on={bad_id: NotFoundError("gone")},
        )
        r = find(fake, FileRef("fake", ROOT_ID), "match")
        self.assertEqual([m.name for m in r.items], ["x_match.txt"])
        self.assertEqual(r.skipped, (bad_id,))
        self.assertFalse(r.truncated)
        self.assertIsNone(r.reason)

    def test_subdirectory_enumeration_limit_stops_not_skipped(self):
        a_id = "p/a"
        b_id = "p/b"
        root_children = [
            _file(a_id, "a", ROOT_ID, kind="directory"),
            _file(b_id, "b", ROOT_ID, kind="directory"),
        ]
        a_children = [
            _file(f"p/a/f{i}.txt", f"f{i}.txt", a_id) for i in range(50)
        ]
        fake = FakeAdapter(
            "fake", {ROOT_ID: root_children, a_id: a_children}
        )
        r = find(fake, FileRef("fake", ROOT_ID), "zzz", max_entries=10, max_depth=4)
        self.assertTrue(r.truncated)
        self.assertEqual(r.reason, "max_entries")
        self.assertEqual(r.skipped, ())
        # Only the root and 'a' were listed; 'b' was never reached.
        self.assertEqual([c[0] for c in fake.calls], [ROOT_ID, a_id])
        # 'a' was asked for the remaining budget (10 - 2 inspected).
        self.assertEqual(fake.calls[1], (a_id, 8))

    def test_argument_validation_before_adapter(self):
        calls: list[int | None] = []

        class SpyAdapter:
            source_id = "spy"

            def list_children(self, parent, *, max_entries=None):
                calls.append(max_entries)
                return []

            def stat(self, ref):
                raise NotImplementedError

            def read_bytes(self, ref):
                raise NotImplementedError

        spy = SpyAdapter()
        ref = FileRef("spy", ROOT_ID)
        bad_kwargs = [
            {"name_contains": ""},
            {"name_contains": None},
            {"name_contains": 123},
            {"name_contains": "x", "max_results": 0},
            {"name_contains": "x", "max_results": 101},
            {"name_contains": "x", "max_results": True},
            {"name_contains": "x", "max_results": 1.5},
            {"name_contains": "x", "max_entries": 0},
            {"name_contains": "x", "max_entries": 100_001},
            {"name_contains": "x", "max_entries": True},
            {"name_contains": "x", "max_depth": -1},
            {"name_contains": "x", "max_depth": 17},
            {"name_contains": "x", "max_depth": True},
            {"name_contains": "x", "case_sensitive": 1},
            {"name_contains": "x", "case_sensitive": "yes"},
        ]
        for kwargs in bad_kwargs:
            with self.assertRaises(ValueError, msg=f"kwargs={kwargs}"):
                find(spy, ref, **kwargs)
        self.assertEqual(calls, [])

if __name__ == "__main__":
    unittest.main()
```

REPLACE IN drive_tool/local.py:
from drive_tool.storage import (

```python
from drive_tool.storage import (
    ROOT_ID,
    EnumerationLimitError,
    FileMetadata,
    FileRef,
    IsDirectoryError,
    NotDirectoryError,
    NotFoundError,
    SourceMismatchError,
    StorageError,
)
```

REPLACE IN drive_tool/local.py:
def init(

```python
    def __init__(
        self,
        source_id: str,
        root: str | os.PathLike[str],
        *,
        max_read_bytes: int = DEFAULT_MAX_READ_BYTES,
        max_list_entries: int = 10_000,
    ) -> None:
        if not isinstance(source_id, str) or source_id == "":
            raise ValueError("source_id must be a non-empty string")
        if (
            isinstance(max_read_bytes, bool)
            or not isinstance(max_read_bytes, int)
            or max_read_bytes <= 0
        ):
            raise ValueError("max_read_bytes must be a positive integer")
        if (
            isinstance(max_list_entries, bool)
            or not isinstance(max_list_entries, int)
            or max_list_entries < 1
        ):
            raise ValueError("max_list_entries must be a positive integer")

        _check_platform_capabilities()
        raw_root, root_parts = _validate_root_path_string(root)

        self._source_id = source_id
        self._max_read_bytes = max_read_bytes
        self._max_list_entries = max_list_entries
        self._closed = False
        self._root_fd: int | None = None
        self._root_fd = self._open_anchored_root(raw_root, root_parts)
```

REPLACE IN drive_tool/local.py:
def list_children(self, parent: FileRef) -> list[FileMetadata]:

```python
    def list_children(
        self, parent: FileRef, *, max_entries: int | None = None
    ) -> list[FileMetadata]:
        """Return sorted metadata for supported direct children of ``parent``.

        ``max_entries``, when not ``None``, bounds the number of directory
        entries examined during the scan (overriding ``max_list_entries``);
        exceeding it raises :class:`EnumerationLimitError`. Every entry
        yielded by the scan counts toward the limit, including symlinks and
        special files that are later omitted.
        """
        root_fd = self._check_source_and_state(parent)
        if max_entries is None:
            effective_limit = self._max_list_entries
        else:
            if (
                isinstance(max_entries, bool)
                or not isinstance(max_entries, int)
                or max_entries < 1
            ):
                raise ValueError(
                    "max_entries must be a positive integer or None"
                )
            effective_limit = max_entries
        parts = _parse_file_id(parent.file_id)
        dir_flags = _dir_open_flags()

        # A descriptor is owned the moment it is acquired. ``owned`` is released
        # exactly once by the single ``finally`` at the end of this method, which
        # covers the parent-close handoff as well as the scan, so a failing
        # parent close cannot skip the child's cleanup scope.
        owned: list[tuple[int, str]] = []
        try:
            if not parts:
                try:
                    scan_fd = self._os_open(".", dir_flags, dir_fd=root_fd)
                except OSError as exc:
                    raise LocalStorageError(
                        f"failed to open root directory for listing: {exc}"
                    ) from exc
            else:
                parent_fd = self._traverse_parent_dir(
                    root_fd, parts[:-1], parent.file_id
                )
                if parent_fd != root_fd:
                    owned.append(
                        (parent_fd, f"parent directory of {parent.file_id!r}")
                    )
                target_name = parts[-1]
                try:
                    scan_fd = self._os_open(
                        target_name, dir_flags, dir_fd=parent_fd
                    )
                except OSError as exc:
                    raise self._classify_component_open_error(
                        target_name,
                        parent_fd,
                        exc,
                        parent.file_id,
                        is_intermediate=False,
                        for_directory_op=True,
                    ) from exc

            # Child scan descriptor acquired: owned immediately.
            owned.append((scan_fd, f"scan descriptor for {parent.file_id!r}"))

            try:
                dir_st = self._os_fstat(scan_fd)
            except OSError as exc:
                raise LocalStorageError(
                    f"failed to fstat directory {parent.file_id!r}: {exc}"
                ) from exc
            if not stat.S_ISDIR(dir_st.st_mode):
                if stat.S_ISLNK(dir_st.st_mode):
                    raise UnsafePathError(
                        f"entry {parent.file_id!r} is a symbolic link"
                    )
                if stat.S_ISREG(dir_st.st_mode):
                    raise NotDirectoryError(
                        f"entry {parent.file_id!r} is not a directory"
                    )
                raise UnsupportedEntryError(
                    f"entry {parent.file_id!r} is not a supported directory"
                )

            try:
                scandir_it = self._os_scandir(scan_fd)
            except OSError as exc:
                raise LocalStorageError(
                    f"failed to scan directory {parent.file_id!r}: {exc}"
                ) from exc

            # os.scandir(scan_fd) DUPLICATES the descriptor: CPython performs an
            # internal _Py_dup() before calling fdopendir(), so the iterator's
            # context manager closes the duplicate and NOT our scan_fd. Close
            # scan_fd explicitly in the finally below, so a failed listing
            # cannot leak it.
            children: list[FileMetadata] = []
            entry_count = 0
            with scandir_it as entries:
                for entry in entries:
                    # Count every entry yielded by the scan, before any name
                    # filtering or stat, so symlinks, special files and odd
                    # names all count toward the limit.
                    entry_count += 1
                    if entry_count > effective_limit:
                        raise EnumerationLimitError(
                            effective_limit,
                            f"directory {parent.file_id!r} exceeds limit of "
                            f"{effective_limit} entries",
                        )
                    name = entry.name
                    if (
                        name in ("", ".", "..")
                        or "/" in name
                        or "\\" in name
                        or "\x00" in name
                    ):
                        continue
                    try:
                        st = entry.stat(follow_symlinks=False)
                    except FileNotFoundError:
                        # An entry disappearing concurrently during listing is skipped.
                        continue
                    except OSError as exc:
                        if exc.errno == errno.ENOENT:
                            continue
                        raise LocalStorageError(
                            f"failed to inspect child {name!r} in "
                            f"{parent.file_id!r}: {exc}"
                        ) from exc

                    if stat.S_ISLNK(st.st_mode):
                        continue
                    if stat.S_ISDIR(st.st_mode):
                        children.append(
                            self._build_metadata(
                                (*parts, name), kind="directory", size_bytes=None
                            )
                        )
                    elif stat.S_ISREG(st.st_mode):
                        children.append(
                            self._build_metadata(
                                (*parts, name),
                                kind="file",
                                size_bytes=st.st_size,
                            )
                        )
                    # Special entries (FIFOs, sockets, device nodes) are omitted.
        except OSError as exc:
            # A readdir()/scandir iteration failure (or iterator close failure)
            # is surfaced as a LocalStorageError with the cause preserved.
            raise LocalStorageError(
                f"failed to iterate directory {parent.file_id!r}: {exc}"
            ) from exc
        finally:
            self._release_owned(owned)

        children.sort(key=lambda meta: meta.name)
        return children
```

STATUS: GENERATED, TESTS_NOT_RUN

Things I was unsure about (for your review):

1. REPLACE IN block delimiter format. The brief says "each preceded by REPLACE IN drive_tool/local.py: and the exact first line of the definition it replaces". I emitted the marker line, then the exact first line on its own line, then the fenced replacement block. If Sarvam expects the first line on the same line as the marker (REPLACE IN drive_tool/local.py: from drive_tool.storage import (), a trivial reflow is needed. The replacement blocks themselves are unambiguous.

2. local.py list_children block extent. I replaced from def list_children(self, parent: FileRef) -> list[FileMetadata]: through the final return children. The docstring was extended (still short/factual) to mention max_entries. __all__, module docstring and all other methods are untouched, per Gemini rule 6.

3. EnumerationLimitError message default. Rule 2 only specified the signature; the default message string is my choice. Tests only assert .limit, never the message.

4. ListingService._validate_max_entries is a new private helper in listing.py (mirrors the storage.py helper rather than importing a private name). The brief says "validated like above before the adapter is called" and does not forbid a local helper.

5. test_enumeration.py uses NotDirectoryError (imported from storage) in one InMemoryAdapter test — this is a pre-existing class, not new. Test only asserts the exception type on a file parent, which is the established contract.

6. os.mkfifo in the symlink/FIFO test assumes POSIX FIFO creation is permitted in the test environment. The whole LocalAdapterEnumerationTests class is skipped via a runtime probe if LocalAdapter construction raises UnsupportedPlatformError, but mkfifo failure itself would be a hard test error rather than a skip.

7. local.py — I did not add a max_list_entries property. Rule 6 said "optionally"; I left it out so the __init__ replacement block is the only place the new attribute is introduced and no property had to be appended outside the three blocks. Tests read behavior, not the attribute.

8. Search defensive guard. Gemini's section-3 pseudocode contains a mid-loop guard if inspected >= max_entries for adapters that ignore the budget. I kept it verbatim; with conforming adapters it is dead code, but it is exercised by test_defensive_guard_against_adapter_ignoring_budget.
