# d017 (deepseek)

- status: done
- chat: https://chat.deepseek.com/a/chat/s/786062c5-f88c-4a21-94b9-2b84b0159b14
- model: deepseek (deepthink on, search off)
- finished: 2026-10-15T12:33:29Z

## Question

DeepSeek, I'm Claude, leading the drive-tool project. I need you to implement MODULE-004 and its tests. Attached below: the brief (the contract and the exact delivery format), Gemini's design review and test plan (follow it where it refines the brief; where it conflicts with the brief, the brief wins and you note the conflict), and the current source files.

Deliver exactly in the brief's format:
- `FILE: <path>` then a fenced block with the complete contents, for drive_tool/storage.py, drive_tool/listing.py, drive_tool/search.py, tests/test_enumeration.py and tests/test_search.py.
- For drive_tool/local.py only three `REPLACE IN drive_tool/local.py:` blocks (the import block, __init__, list_children), each naming the exact first line it replaces.
No ellipses, no placeholders, no "rest unchanged" inside a block. Sarvam will apply your output exactly and run the tests; I will review it. You cannot run code, so end with STATUS: GENERATED, TESTS_NOT_RUN and a short list of anything you were unsure about.

(input files: Dolesh-avkalan/drive-tool:tasks/MODULE-004.md@main, Dolesh-avkalan/drop:drive-tool/module-004/d016-argon-design-review.md, Dolesh-avkalan/drive-tool:drive_tool/storage.py@main, Dolesh-avkalan/drive-tool:drive_tool/listing.py@main, Dolesh-avkalan/drive-tool:drive_tool/local.py@main)

## Answer

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
    """A directory has more entries than the configured enumeration limit.

    ``limit`` is the effective bound that was exceeded (the per-call
    ``max_entries`` when given, otherwise the adapter's configured default).
    """

    def __init__(self, limit: int, message: str | None = None) -> None:
        self.limit = limit
        super().__init__(
            message if message is not None else (
                f"directory entry count exceeded limit of {limit}"
            )
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

        ``max_entries``, when not ``None``, bounds the number of entries the
        adapter may return. Implementations raise :class:`EnumerationLimitError`
        as soon as the directory has more than ``max_entries`` entries.
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
    """Validate an optional enumeration bound. ``None`` is accepted."""
    if max_entries is None:
        return
    if isinstance(max_entries, bool) or not isinstance(max_entries, int):
        raise ValueError(
            f"max_entries must be None or an int, got {type(max_entries).__name__}"
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
        # Source mismatch is always checked first, before argument validation.
        self._check_source(parent)
        _validate_max_entries(max_entries)
        if parent.file_id == ROOT_ID:
            if max_entries is not None and len(self._files) > max_entries:
                raise EnumerationLimitError(
                    max_entries,
                    f"directory {ROOT_ID!r} has {len(self._files)} entries, "
                    f"exceeding limit of {max_entries}",
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

MODULE-004 adds an optional ``max_entries`` bound that is validated before the
adapter is called and is forwarded to the adapter only when it is not ``None``,
so adapters and test fakes without the keyword keep working. An
``EnumerationLimitError`` from the adapter propagates unchanged.

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
            f"max_entries must be None or an int, got {type(max_entries).__name__}"
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
        never reaches the adapter. ``max_entries``, when not ``None``, is
        forwarded to the adapter as the per-call enumeration bound; it is
        omitted from the adapter call when ``None``. Ordering is by
        ``(name, source_id, file_id)``. Filtering is a case-sensitive substring
        match applied before pagination.
        """
        # Validate everything first: bad arguments must not touch the adapter.
        _validate_limit(limit)
        _validate_offset(offset)
        _validate_name_contains(name_contains)
        _validate_max_entries(max_entries)

        # Fresh listing each call; copy before sorting so the adapter's own
        # return value is never mutated. The keyword is only passed when a
        # bound was requested, so legacy adapters/fakes still work.
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

FILE: drive
