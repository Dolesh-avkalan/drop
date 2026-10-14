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

    def list_children(self, parent: FileRef) -> list[FileMetadata]:
        """Return metadata for the direct children of directory ``parent``."""
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

    def list_children(self, parent: FileRef) -> list[FileMetadata]:
        self._check_source(parent)
        if parent.file_id == ROOT_ID:
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
