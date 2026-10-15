# d026 (deepseek)

- status: done
- chat: https://chat.deepseek.com/a/chat/s/d21f7953-8b08-4777-a637-48b837ff15c5
- model: deepseek (deepthink on, search off)
- finished: 2026-10-15T13:41:55Z

## Question

DeepSeek, I'm Claude, leading the drive-tool project. Your MODULE-004 code passed review and is merged. I need you to implement MODULE-005 and its tests. Attached: the brief, Gemini's design review, and the current source.

I accept Gemini's recommended rules (its section 1) and its plan (sections 2-4) as my decisions, EXCEPT where one would weaken a security rule of the brief (atomic no-replace publish with link, no-follow opens, temp-file cleanup on every error path, no fallback to a racy method): there the brief wins, and you say so in one line.

Deliver exactly in the brief's format: FILE blocks with complete contents for drive_tool/local_write.py, tests/test_local_write.py and drive_tool/storage.py; exactly two EDIT drive_tool/local.py blocks (exact old lines, exact new lines). No ellipses, no placeholders. Then one line per test naming the mistake it catches. End with STATUS: GENERATED, TESTS_NOT_RUN and anything you were unsure about.

(input files: Dolesh-avkalan/drive-tool:tasks/MODULE-005.md@main, Dolesh-avkalan/drop:drive-tool/module-005/d025-argon-design-review.md, Dolesh-avkalan/drive-tool:drive_tool/storage.py@main, Dolesh-avkalan/drive-tool:drive_tool/local.py@main)

## Answer

I accept Gemini's rules and plan as-is; no brief security rule is weakened (atomic link publish, no-follow opens, per-error temp cleanup, and no racy fallback are all preserved verbatim).

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
    "AlreadyExistsError",
    "ReadOnlyError",
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

class AlreadyExistsError(StorageError):
    """A create-only operation found the target name already present."""

class ReadOnlyError(StorageError):
    """A mutating operation was attempted on a read-only storage source."""

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

EDIT drive_tool/local.py:

```python
<<<<
#: Mandatory prefix for all non-root entry IDs in ``LocalAdapter``.
PATH_PREFIX = "p/"
====
#: Mandatory prefix for all non-root entry IDs in ``LocalAdapter``.
PATH_PREFIX = "p/"

#: Prefix for hidden temporary files created by ``LocalWriter``.
TEMP_PREFIX = ".drive-tool-tmp-"
>>>>
```

EDIT drive_tool/local.py:

```python
<<<<
                    name = entry.name
                    if (
                        name in ("", ".", "..")
                        or "/" in name
                        or "\\" in name
                        or "\x00" in name
                    ):
                        continue
====
                    name = entry.name
                    if (
                        name in ("", ".", "..")
                        or "/" in name
                        or "\\" in name
                        or "\x00" in name
                        or name.startswith(TEMP_PREFIX)
                    ):
                        continue
>>>>
```

FILE: drive_tool/local_write.py

```python
"""Safe local writes: atomic no-overwrite save and mkdir (MODULE-005).

This module implements :class:`LocalWriter`, a write-side wrapper around an
open :class:`drive_tool.local.LocalAdapter`. Writes are strictly contained to
the adapter's anchored root directory and use anchored, no-follow opens.
Publication is an atomic no-replace ``link`` by default; ``overwrite=True``
uses an atomic ``rename`` after a no-follow target check.

Threat boundaries (see MODULE-003): hard links, bind mounts, submounts, and
adversarial provisioning of the root directory itself remain operator
responsibilities. Data is fully buffered as ``bytes`` in memory; streaming
writes are out of scope. A crash between syscalls can leave a temp file
behind; stale temp-file cleanup is out of scope. Python 3.11+, standard
library only, POSIX only.
"""

from __future__ import annotations

import errno
import os
import secrets
import stat

from drive_tool.local import (
    LocalAdapter,
    LocalStorageError,
    NotDirectoryError,
    TEMP_PREFIX,
    UnsafePathError,
    UnsupportedEntryError,
    UnsupportedPlatformError,
    _dir_open_flags,
    _parse_file_id,
)
from drive_tool.storage import (
    AlreadyExistsError,
    FileMetadata,
    FileRef,
    IsDirectoryError,
    NotFoundError,
)

__all__ = [
    "DEFAULT_MAX_WRITE_BYTES",
    "TEMP_PREFIX",
    "WriteLimitExceededError",
    "LocalWriter",
]

#: Default upper bound (10 MiB) for :meth:`LocalWriter.write_bytes`.
DEFAULT_MAX_WRITE_BYTES = 10_485_760

_MAX_NAME_BYTES = 255
_TEMP_NAME_RETRIES = 3
_TEMP_OPEN_MODE = 0o644
_MKDIR_MODE = 0o755

class WriteLimitExceededError(LocalStorageError):
    """Raised when the ``write_bytes`` payload exceeds ``max_write_bytes``."""

def _check_writer_platform_capabilities() -> None:
    """Fail closed when the runtime lacks write-related POSIX features."""
    for flag_name in ("O_WRONLY", "O_CREAT", "O_EXCL"):
        if not isinstance(getattr(os, flag_name, None), int):
            raise UnsupportedPlatformError(
                f"LocalWriter requires os.{flag_name} support on this platform"
            )
    for func_name in (
        "open",
        "close",
        "fstat",
        "stat",
        "write",
        "fsync",
        "link",
        "rename",
        "unlink",
        "mkdir",
    ):
        if not hasattr(os, func_name):
            raise UnsupportedPlatformError(
                f"LocalWriter requires os.{func_name} support on this platform"
            )
    supports_dir_fd = getattr(os, "supports_dir_fd", set())
    for fn in (os.link, os.rename, os.unlink, os.mkdir):
        if fn not in supports_dir_fd:
            raise UnsupportedPlatformError(
                f"LocalWriter requires dir_fd support for os.{fn.__name__}"
            )
    supports_follow_symlinks = getattr(os, "supports_follow_symlinks", set())
    if os.link not in supports_follow_symlinks:
        raise UnsupportedPlatformError(
            "LocalWriter requires follow_symlinks=False support for os.link"
        )

class LocalWriter:
    """Write-side wrapper around an open :class:`LocalAdapter`.

    A bare adapter stays read-only; a caller that wants to write must build a
    writer, which reuses the adapter's containment helpers so no path logic is
    duplicated. Every method checks source mismatch first, then closed
    adapter, then its arguments. The writer never raises
    :class:`drive_tool.storage.ReadOnlyError`; that error is reserved for
    later policy layers.
    """

    def __init__(
        self,
        adapter: LocalAdapter,
        *,
        max_write_bytes: int = DEFAULT_MAX_WRITE_BYTES,
    ) -> None:
        if not isinstance(adapter, LocalAdapter):
            raise TypeError(
                f"adapter must be a LocalAdapter, got {type(adapter).__name__}"
            )
        if (
            isinstance(max_write_bytes, bool)
            or not isinstance(max_write_bytes, int)
            or max_write_bytes < 1
        ):
            raise ValueError("max_write_bytes must be a positive integer")

        _check_writer_platform_capabilities()
        self._adapter = adapter
        self._max_write_bytes = max_write_bytes

    @property
    def max_write_bytes(self) -> int:
        """The maximum number of bytes permitted for a single write."""
        return self._max_write_bytes

    # -- OS seams (test injection) -------------------------------------------

    def _os_open(
        self,
        path: str,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        return os.open(path, flags, mode, dir_fd=dir_fd)

    def _os_close(self, fd: int) -> None:
        os.close(fd)

    def _os_write(self, fd: int, data) -> int:
        return os.write(fd, data)

    def _os_fsync(self, fd: int) -> None:
        os.fsync(fd)

    def _os_link(
        self,
        src: str,
        dst: str,
        *,
        src_dir_fd: int,
        dst_dir_fd: int,
        follow_symlinks: bool = False,
    ) -> None:
        os.link(
            src,
            dst,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )

    def _os_rename(
        self,
        src: str,
        dst: str,
        *,
        src_dir_fd: int,
        dst_dir_fd: int,
    ) -> None:
        os.rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    def _os_unlink(self, path: str, *, dir_fd: int) -> None:
        os.unlink(path, dir_fd=dir_fd)

    def _os_mkdir(self, path: str, mode: int = _MKDIR_MODE, *, dir_fd: int) -> None:
        os.mkdir(path, mode, dir_fd=dir_fd)

    # -- small helpers --------------------------------------------------------

    def _close_quietly(self, fd: int) -> None:
        try:
            self._os_close(fd)
        except OSError:
            pass

    def _unlink_quietly(self, name: str, parent_fd: int) -> None:
        try:
            self._os_unlink(name, dir_fd=parent_fd)
        except OSError:
            pass

    def _reject_temp_in_parent(self, parts: tuple[str, ...]) -> None:
        for part in parts:
            if part.startswith(TEMP_PREFIX):
                raise UnsafePathError(
                    f"parent path component {part!r} must not start with "
                    f"{TEMP_PREFIX!r}"
                )

    def _validate_name(self, name: object) -> str:
        if not isinstance(name, str):
            raise UnsafePathError(
                f"name must be a str, got {type(name).__name__}"
            )
        if name == "":
            raise UnsafePathError("name must be non-empty")
        if name in (".", ".."):
            raise UnsafePathError(f"name {name!r} is not a valid component")
        if "/" in name or "\\" in name or "\x00" in name:
            raise UnsafePathError(
                f"name {name!r} must not contain '/', backslash, or NUL"
            )
        if name.startswith(TEMP_PREFIX):
            raise UnsafePathError(
                f"name {name!r} must not start with reserved prefix "
                f"{TEMP_PREFIX!r}"
            )
        try:
            encoded = name.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise UnsafePathError(
                f"name must be valid UTF-8: {exc}"
            ) from exc
        if len(encoded) > _MAX_NAME_BYTES:
            raise UnsafePathError(
                f"name is {len(encoded)} UTF-8 bytes, exceeds "
                f"{_MAX_NAME_BYTES}"
            )
        return name

    def _open_parent_dir(
        self,
        root_fd: int,
        parts: tuple[str, ...],
        file_id: str,
        owned: list[tuple[int, str]],
    ) -> int:
        """Open and return a directory fd for ``file_id``'s parent.

        The fd is appended to ``owned`` the moment it is acquired so the
        caller's single ``finally`` releases it exactly once.
        """
        if not parts:
            try:
                parent_fd = self._os_open(
                    ".", _dir_open_flags(), dir_fd=root_fd
                )
            except OSError as exc:
                raise LocalStorageError(
                    f"failed to open anchored root for {file_id!r}: {exc}"
                ) from exc
            owned.append((parent_fd, f"parent directory of {file_id!r}"))
            try:
                st = self._adapter._os_fstat(parent_fd)
            except OSError as exc:
                raise LocalStorageError(
                    f"failed to fstat parent of {file_id!r}: {exc}"
                ) from exc
            if not stat.S_ISDIR(st.st_mode):
                raise LocalStorageError(
                    f"anchored root for {file_id!r} is not a directory"
                )
            return parent_fd

        traversed_fd = self._adapter._traverse_parent_dir(
            root_fd, parts[:-1], file_id
        )
        if traversed_fd != root_fd:
            owned.append(
                (traversed_fd, f"intermediate parent of {file_id!r}")
            )

        target_name = parts[-1]
        try:
            parent_fd = self._os_open(
                target_name, _dir_open_flags(), dir_fd=traversed_fd
            )
        except OSError as exc:
            raise self._adapter._classify_component_open_error(
                target_name,
                traversed_fd,
                exc,
                file_id,
                is_intermediate=False,
                for_directory_op=True,
            ) from exc
        owned.append((parent_fd, f"parent directory {file_id!r}"))

        try:
            st = self._adapter._os_fstat(parent_fd)
        except OSError as exc:
            raise LocalStorageError(
                f"failed to fstat parent directory {file_id!r}: {exc}"
            ) from exc
        if not stat.S_ISDIR(st.st_mode):
            if stat.S_ISLNK(st.st_mode):
                raise UnsafePathError(
                    f"parent directory {file_id!r} is a symbolic link"
                )
            if stat.S_ISREG(st.st_mode):
                raise NotDirectoryError(
                    f"parent {file_id!r} is not a directory"
                )
            raise UnsupportedEntryError(
                f"parent {file_id!r} is not a supported directory"
            )
        return parent_fd

    # -- write helpers ---------------------------------------------------------

    def _create_temp_file(self, parent_fd: int) -> tuple[str, int]:
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0)
        )
        last_exc: OSError | None = None
        for _ in range(_TEMP_NAME_RETRIES):
            candidate = TEMP_PREFIX + secrets.token_hex(8)
            try:
                fd = self._os_open(
                    candidate, flags, _TEMP_OPEN_MODE, dir_fd=parent_fd
                )
            except OSError as exc:
                if exc.errno == errno.EEXIST:
                    last_exc = exc
                    continue
                raise LocalStorageError(
                    f"failed to create temporary file: {exc}"
                ) from exc
            return candidate, fd
        raise LocalStorageError(
            f"failed to create temporary file after "
            f"{_TEMP_NAME_RETRIES} attempts: {last_exc}"
        )

    def _write_all(self, fd: int, data: bytes) -> None:
        view = memoryview(data)
        total = len(view)
        offset = 0
        while offset < total:
            try:
                written = self._os_write(fd, view[offset:])
            except OSError as exc:
                if exc.errno == errno.EINTR:
                    continue
                raise LocalStorageError(
                    f"failed while writing temporary file: {exc}"
                ) from exc
            if written <= 0:
                raise LocalStorageError(
                    "write returned no bytes while data remained"
                )
            offset += written

    def _check_overwrite_target(self, parent_fd: int, name: str) -> None:
        try:
            st = self._adapter._os_stat_nofollow(name, dir_fd=parent_fd)
        except OSError as exc:
            if exc.errno == errno.ENOENT:
                return
            if exc.errno in (errno.ELOOP, getattr(errno, "EMLINK", -1)):
                raise UnsafePathError(
                    f"symlink encountered at {name!r}"
                ) from exc
            raise LocalStorageError(
                f"failed to inspect target {name!r}: {exc}"
            ) from exc
        if stat.S_ISLNK(st.st_mode):
            raise UnsafePathError(f"target {name!r} is a symbolic link")
        if stat.S_ISDIR(st.st_mode):
            raise IsDirectoryError(
                f"target {name!r} is a directory, not a file"
            )
        if not stat.S_ISREG(st.st_mode):
            raise UnsupportedEntryError(
                f"target {name!r} is not a regular file"
            )

    # -- public API ------------------------------------------------------------

    def mkdir(
        self,
        parent: FileRef,
        name: str,
        *,
        exist_ok: bool = False,
    ) -> FileMetadata:
        """Create a single directory component ``name`` under ``parent``.

        When ``exist_ok`` is true and ``name`` already exists as a real
        directory, its metadata is returned without touching the filesystem.
        A symlink occupying ``name`` is never accepted.
        """
        root_fd = self._adapter._check_source_and_state(parent)
        parts = _parse_file_id(parent.file_id)
        self._reject_temp_in_parent(parts)
        self._validate_name(name)
        if not isinstance(exist_ok, bool):
            raise ValueError(
                f"exist_ok must be a bool, got {type(exist_ok).__name__}"
            )

        owned: list[tuple[int, str]] = []
        try:
            parent_fd = self._open_parent_dir(
                root_fd, parts, parent.file_id, owned
            )
            try:
                self._os_mkdir(name, _MKDIR_MODE, dir_fd=parent_fd)
            except OSError as exc:
                if exc.errno != errno.EEXIST:
                    raise LocalStorageError(
                        f"failed to create directory {name!r}: {exc}"
                    ) from exc
                return self._handle_mkdir_eexist(
                    parent_fd, name, parts, exist_ok
                )
            try:
                self._os_fsync(parent_fd)
            except OSError as exc:
                raise LocalStorageError(
                    f"failed to fsync parent after mkdir {name!r}: {exc}"
                ) from exc
            return self._adapter._build_metadata(
                (*parts, name), kind="directory", size_bytes=None
            )
        finally:
            self._adapter._release_owned(owned)

    def _handle_mkdir_eexist(
        self,
        parent_fd: int,
        name: str,
        parts: tuple[str, ...],
        exist_ok: bool,
    ) -> FileMetadata:
        try:
            st = self._adapter._os_stat_nofollow(name, dir_fd=parent_fd)
        except OSError as exc:
            if exc.errno in (errno.ELOOP, getattr(errno, "EMLINK", -1)):
                raise UnsafePathError(
                    f"symlink encountered at {name!r}"
                ) from exc
            if exc.errno == errno.ENOENT:
                raise AlreadyExistsError(
                    f"entry {name!r} already exists"
                ) from None
            raise LocalStorageError(
                f"failed to inspect existing entry {name!r}: {exc}"
            ) from exc
        if stat.S_ISLNK(st.st_mode):
            raise UnsafePathError(f"entry {name!r} is a symbolic link")
        if stat.S_ISDIR(st.st_mode) and exist_ok:
            return self._adapter._build_metadata(
                (*parts, name), kind="directory", size_bytes=None
            )
        raise AlreadyExistsError(f"entry {name!r} already exists")

    def write_bytes(
        self,
        parent: FileRef,
        name: str,
        data: bytes,
        *,
        overwrite: bool = False,
    ) -> FileMetadata:
        """Write ``data`` to ``name`` under ``parent`` and return metadata.

        With ``overwrite=False`` the publish step is an atomic no-replace
        ``link``; with ``overwrite=True`` the existing target (if any) must be
        a regular file and is replaced by an atomic ``rename``.
        """
        root_fd = self._adapter._check_source_and_state(parent)
        parts = _parse_file_id(parent.file_id)
        self._reject_temp_in_parent(parts)
        self._validate_name(name)
        if not isinstance(overwrite, bool):
            raise ValueError(
                f"overwrite must be a bool, got {type(overwrite).__name__}"
            )
        if not isinstance(data, bytes):
            raise ValueError(
                f"data must be bytes, got {type(data).__name__}"
            )
        if len(data) > self._max_write_bytes:
            raise WriteLimitExceededError(
                f"data size {len(data)} exceeds max_write_bytes "
                f"{self._max_write_bytes}"
            )

        owned: list[tuple[int, str]] = []
        parent_fd: int | None = None
        tmp_fd: int | None = None
        tmp_name: str | None = None
        tmp_on_disk = False
        try:
            parent_fd = self._open_parent_dir(
                root_fd, parts, parent.file_id, owned
            )

            tmp_name, tmp_fd = self._create_temp_file(parent_fd)
            tmp_on_disk = True

            self._write_all(tmp_fd, data)
            try:
                self._os_fsync(tmp_fd)
            except OSError as exc:
                raise LocalStorageError(
                    f"failed to fsync temporary file for {name!r}: {exc}"
                ) from exc

            fd_to_close = tmp_fd
            tmp_fd = None
            try:
                self._os_close(fd_to_close)
            except OSError as exc:
                raise LocalStorageError(
                    f"failed to close temporary file for {name!r}: {exc}"
                ) from exc

            if overwrite:
                self._check_overwrite_target(parent_fd, name)
                try:
                    self._os_rename(
                        tmp_name,
                        name,
                        src_dir_fd=parent_fd,
                        dst_dir_fd=parent_fd,
                    )
                except OSError as exc:
                    if exc.errno in (
                        errno.EISDIR,
                        errno.ENOTEMPTY,
                        errno.EEXIST,
                    ):
                        raise IsDirectoryError(
                            f"cannot replace {name!r} with a file"
                        ) from exc
                    if exc.errno in (
                        errno.ELOOP,
                        getattr(errno, "EMLINK", -1),
                    ):
                        raise UnsafePathError(
                            f"symlink encountered replacing {name!r}"
                        ) from exc
                    raise LocalStorageError(
                        f"failed to replace {name!r}: {exc}"
                    ) from exc
                tmp_on_disk = False
            else:
                try:
                    self._os_link(
                        tmp_name,
                        name,
                        src_dir_fd=parent_fd,
                        dst_dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                except OSError as exc:
                    if exc.errno == errno.EEXIST:
                        raise AlreadyExistsError(
                            f"entry {name!r} already exists"
                        ) from exc
                    if exc.errno in (
                        errno.EPERM,
                        errno.ENOTSUP,
                        errno.EOPNOTSUPP,
                        errno.EXDEV,
                        errno.ENOSYS,
                        errno.EMLINK,
                    ):
                        raise UnsupportedPlatformError(
                            f"atomic link publish not supported for "
                            f"{name!r}: {exc}"
                        ) from exc
                    raise LocalStorageError(
                        f"failed to link temporary file to {name!r}: {exc}"
                    ) from exc
                try:
                    self._os_unlink(tmp_name, dir_fd=parent_fd)
                except OSError as exc:
                    raise LocalStorageError(
                        f"failed to unlink temp name after linking "
                        f"{name!r}: {exc}"
                    ) from exc
                tmp_on_disk = False

            try:
                self._os_fsync(parent_fd)
            except OSError as exc:
                raise LocalStorageError(
                    f"failed to fsync parent after write {name!r}: {exc}"
                ) from exc

            return self._adapter._build_metadata(
                (*parts, name), kind="file", size_bytes=len(data)
            )
        except BaseException:
            if tmp_fd is not None:
                self._close_quietly(tmp_fd)
                tmp_fd = None
            if tmp_on_disk and tmp_name is not None and parent_fd is not None:
                self._unlink_quietly(tmp_name, parent_fd)
            raise
        finally:
            self._adapter._release_owned(owned)
```

FILE: tests/test_local_write.py

```python
"""MODULE-005 tests: safe local writes (atomic, no-overwrite save and mkdir)."""

from __future__ import annotations

import errno
import os
import shutil
import stat
import tempfile
import threading
import unittest

from drive_tool.local import (
    AdapterClosedError,
    EnumerationLimitError,
    LocalAdapter,
    LocalStorageError,
    NotDirectoryError,
    PATH_PREFIX,
    TEMP_PREFIX,
    UnsafePathError,
    UnsupportedEntryError,
    UnsupportedPlatformError,
)
from drive_tool.local_write import (
    DEFAULT_MAX_WRITE_BYTES,
    LocalWriter,
    WriteLimitExceededError,
)
from drive_tool.storage import (
    AlreadyExistsError,
    FileRef,
    IsDirectoryError,
    NotFoundError,
    SourceMismatchError,
    StorageError,
)

_HAS_PROC_FD = os.path.isdir("/proc/self/fd")

def _fd_count() -> int:
    return len(os.listdir("/proc/self/fd"))

def _no_temp_entries(path: str) -> bool:
    return not any(
        entry.startswith(TEMP_PREFIX) for entry in os.listdir(path)
    )

class BaseLocalWriteTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="drive_tool_lw_")
        self.root = os.path.join(self._tmpdir, "root")
        os.mkdir(self.root)
        self.adapter = LocalAdapter("src", self.root)
        self.writer = LocalWriter(self.adapter)

    def tearDown(self) -> None:
        try:
            self.adapter.close()
        except Exception:
            pass
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _root_ref(self) -> FileRef:
        return FileRef(self.adapter.source_id, "root")

    def _ref(self, file_id: str) -> FileRef:
        return FileRef(self.adapter.source_id, file_id)

class TestStorageContract(BaseLocalWriteTest):
    def test_storage_exports_new_errors(self) -> None:
        from drive_tool import storage
        self.assertIn("AlreadyExistsError", storage.__all__)
        self.assertIn("ReadOnlyError", storage.__all__)
        self.assertTrue(
            issubclass(storage.AlreadyExistsError, storage.StorageError)
        )
        self.assertTrue(
            issubclass(storage.ReadOnlyError, storage.StorageError)
        )

class TestWriterInit(BaseLocalWriteTest):
    def test_writer_init_validation(self) -> None:
        with self.assertRaises(TypeError):
            LocalWriter("not an adapter")  # type: ignore[arg-type]
        for bad in (0, -1, True, False, "10", None, 1.5, 10_485_760.0):
            with self.assertRaises(ValueError):
                LocalWriter(self.adapter, max_write_bytes=bad)  # type: ignore[arg-type]

class TestWriteHappyPaths(BaseLocalWriteTest):
    def test_write_and_read_back_root_and_nested(self) -> None:
        writer = self.writer
        root_ref = self._root_ref()
        meta = writer.write_bytes(root_ref, "a.txt", b"hello")
        self.assertEqual(meta.kind, "file")
        self.assertEqual(meta.size_bytes, 5)
        self.assertEqual(meta.name, "a.txt")
        self.assertEqual(meta.ref.file_id, "p/a.txt")
        self.assertEqual(meta.parent_id, "root")
        self.assertEqual(self.adapter.read_bytes(self._ref("p/a.txt")), b"hello")

        os.mkdir(os.path.join(self.root, "sub"))
        sub_ref = self._ref("p/sub")
        meta2 = writer.write_bytes(sub_ref, "b.txt", b"world!")
        self.assertEqual(meta2.ref.file_id, "p/sub/b.txt")
        self.assertEqual(meta2.parent_id, "p/sub")
        self.assertEqual(meta2.size_bytes, 6)
        self.assertEqual(
            self.adapter.read_bytes(self._ref("p/sub/b.txt")), b"world!"
        )

    def test_write_empty_and_exact_max_write_bytes(self) -> None:
        writer = self.writer
        root_ref = self._root_ref()
        writer.write_bytes(root_ref, "empty.bin", b"")
        self.assertEqual(
            self.adapter.read_bytes(self._ref("p/empty.bin")), b""
        )
        payload = b"x" * DEFAULT_MAX_WRITE_BYTES
        writer.write_bytes(root_ref, "max.bin", payload)
        self.assertEqual(
            self.adapter.read_bytes(self._ref("p/max.bin")), payload
        )
        self.assertTrue(_no_temp_entries(self.root))

    def test_write_overwrite_true_creates_and_replaces(self) -> None:
        writer = self.writer
        root_ref = self._root_ref()
        writer.write_bytes(root_ref, "a.txt", b"first", overwrite=True)
        self.assertEqual(self.adapter.read_bytes(self._ref("p/a.txt")), b"first")
        writer.write_bytes(
            root_ref, "a.txt", b"second-longer", overwrite=True
        )
        self.assertEqual(
            self.adapter.read_bytes(self._ref("p/a.txt")), b"second-longer"
        )
        st = self.adapter.stat(self._ref("p/a.txt"))
        self.assertEqual(st.size_bytes, len(b"second-longer"))

class TestWriteLimit(BaseLocalWriteTest):
    def test_write_exceeds_max_write_bytes_before_disk(self) -> None:
        writer = LocalWriter(self.adapter, max_write_bytes=10)
        root_ref = self._root_ref()
        with self.assertRaises(WriteLimitExceededError):
            writer.write_bytes(root_ref, "big.bin", b"x" * 11)
        self.assertEqual(os.listdir(self.root), [])

class TestWriteOverwriteFalse(BaseLocalWriteTest):
    def test_write_overwrite_false_existing_file(self) -> None:
        path = os.path.join(self.root, "a.txt")
        with open(path, "wb") as f:
            f.write(b"old")
        with self.assertRaises(AlreadyExistsError):
            self.writer.write_bytes(self._root_ref(), "a.txt", b"new")
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b"old")
        self.assertTrue(_no_temp_entries(self.root))

    def test_write_overwrite_false_existing_symlink(self) -> None:
        outside = os.path.join(self._tmpdir, "outside")
        os.mkdir(outside)
        target = os.path.join(outside, "victim.txt")
        with open(target, "wb") as f:
            f.write(b"victim")
        os.symlink(target, os.path.join(self.root, "link"))
        with self.assertRaises(AlreadyExistsError):
            self.writer.write_bytes(self._root_ref(), "link", b"new")
        with open(target, "rb") as f:
            self.assertEqual(f.read(), b"victim")
        self.assertTrue(_no_temp_entries(self.root))

        # Dangling symlink.
        os.symlink(
            os.path.join(self.root, "nope"),
            os.path.join(self.root, "dangling"),
        )
        with self.assertRaises(AlreadyExistsError):
            self.writer.write_bytes(self._root_ref(), "dangling", b"new")
        self.assertTrue(_no_temp_entries(self.root))

class TestWriteOverwriteTrueRejects(BaseLocalWriteTest):
    def test_write_overwrite_true_rejects_directory_symlink_fifo(self) -> None:
        writer = self.writer
        root_ref = self._root_ref()

        os.mkdir(os.path.join(self.root, "adir"))
        with self.assertRaises(IsDirectoryError):
            writer.write_bytes(root_ref, "adir", b"x", overwrite=True)
        self.assertTrue(os.path.isdir(os.path.join(self.root, "adir")))

        outside = os.path.join(self._tmpdir, "outside")
        os.mkdir(outside)
        os.symlink(
            os.path.join(outside, "target"), os.path.join(self.root, "link")
        )
        with self.assertRaises(UnsafePathError):
            writer.write_bytes(root_ref, "link", b"x", overwrite=True)

        fifo = os.path.join(self.root, "afifo")
        os.mkfifo(fifo, 0o644)
        with self.assertRaises(UnsupportedEntryError):
            writer.write_bytes(root_ref, "afifo", b"x", overwrite=True)

        self.assertTrue(_no_temp_entries(self.root))
        self.assertEqual(os.listdir(outside), [])

class TestNameValidation(BaseLocalWriteTest):
    def test_name_validation_all_invalid_classes(self) -> None:
        writer = self.writer
        root_ref = self._root_ref()
        invalid: list[object] = [
            "",
            ".",
            "..",
            "a/b",
            "a\\b",
            "a\x00b",
            TEMP_PREFIX + "1",
            "a" * 256,
            "\u00e9" * 128,  # 256 UTF-8 bytes
            123,
            b"a",
            None,
            "\ud800",  # lone surrogate, unencodable
        ]
        for bad in invalid:
            with self.assertRaises(UnsafePathError):
                writer.write_bytes(root_ref, bad, b"")  # type: ignore[arg-type]
        self.assertEqual(os.listdir(self.root), [])

        # Exactly 255 UTF-8 bytes is accepted.
        ok = "\u00e9" * 127 + "x"
        writer.write_bytes(root_ref, ok, b"")
        self.assertIn(ok, os.listdir(self.root))

class TestParentValidation(BaseLocalWriteTest):
    def test_parent_validation_and_containment(self) -> None:
        writer = self.writer

        with self.assertRaises(NotFoundError):
            writer.write_bytes(self._ref("p/missing"), "a", b"x")

        with open(os.path.join(self.root, "afile"), "wb") as f:
            f.write(b"x")
        with self.assertRaises(NotDirectoryError):
            writer.write_bytes(self._ref("p/afile"), "a", b"x")

        os.mkfifo(os.path.join(self.root, "afifo"), 0o644)
        with self.assertRaises(UnsupportedEntryError):
            writer.write_bytes(self._ref("p/afifo"), "a", b"x")

        with self.assertRaises(UnsafePathError):
            writer.write_bytes(
                self._ref("p/" + TEMP_PREFIX + "dir"), "a", b"x"
            )

        outside = os.path.join(self._tmpdir, "outside")
        os.mkdir(outside)
        os.symlink(outside, os.path.join(self.root, "final_link"))
        with self.assertRaises(UnsafePathError):
            writer.write_bytes(self._ref("p/final_link"), "a", b"x")

        os.mkdir(os.path.join(self.root, "sub"))
        os.symlink(outside, os.path.join(self.root, "sub", "mid_link"))
        with self.assertRaises(UnsafePathError):
            writer.write_bytes(self._ref("p/sub/mid_link"), "a", b"x")

        self.assertEqual(os.listdir(outside), [])

class TestPrecedence(BaseLocalWriteTest):
    def test_precedence_source_mismatch_then_closed_then_args(self) -> None:
        writer = self.writer

        wrong = FileRef("wrong-source", "root")
        with self.assertRaises(SourceMismatchError):
            writer.write_bytes(wrong, "", b"")

        tmpdir = tempfile.mkdtemp(prefix="drive_tool_lw_closed_")
        try:
            root = os.path.join(tmpdir, "root")
            os.mkdir(root)
            a = LocalAdapter("src2", root)
            w = LocalWriter(a)
            a.close()
            with self.assertRaises(AdapterClosedError):
                w.write_bytes(FileRef("src2", "root"), "", b"")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        root_ref = self._root_ref()
        with self.assertRaises(ValueError):
            writer.write_bytes(root_ref, "a", "not bytes")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            writer.write_bytes(root_ref, "a", bytearray(b"x"))  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            writer.write_bytes(root_ref, "a", b"", overwrite="yes")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            writer.mkdir(root_ref, "a", exist_ok="yes")  # type: ignore[arg-type]

class TestSeams(BaseLocalWriteTest):
    def test_seam_write_handles_short_writes_and_eintr(self) -> None:
        class ShortWriter(LocalWriter):
            def __init__(self, *a, **kw) -> None:
                super().__init__(*a, **kw)
                self.calls = 0
                self.observed = bytearray()

            def _os_write(self, fd, data):  # type: ignore[override]
                self.calls += 1
                if self.calls == 1:
                    raise OSError(errno.EINTR, "interrupted")
                chunk = bytes(data[:3])
                self.observed.extend(chunk)
                return os.write(fd, chunk)

        w = ShortWriter(self.adapter)
        payload = b"abcdefghij"
        w.write_bytes(self._root_ref(), "short.bin", payload)
        self.assertEqual(
            self.adapter.read_bytes(self._ref("p/short.bin")), payload
        )
        self.assertEqual(bytes(w.observed), payload)
        self.assertTrue(_no_temp_entries(self.root))

    @unittest.skipUnless(_HAS_PROC_FD, "requires /proc/self/fd")
    def test_seam_write_zero_return_or_midway_oserror_cleans_up(self) -> None:
        class ZeroWriter(LocalWriter):
            def _os_write(self, fd, data):  # type: ignore[override]
                return 0

        fd_before = _fd_count()
        zw = ZeroWriter(self.adapter)
        with self.assertRaises(LocalStorageError):
            zw.write_bytes(self._root_ref(), "z.bin", b"abc")
        self.assertEqual(os.listdir(self.root), [])
        self.assertEqual(_fd_count(), fd_before)

        class MidwayWriter(LocalWriter):
            def __init__(self, *a, **kw) -> None:
                super().__init__(*a, **kw)
                self.n = 0

            def _os_write(self, fd, data):  # type: ignore[override]
                self.n += 1
                if self.n == 1:
                    return os.write(fd, bytes(data[:3]))
                raise OSError(errno.ENOSPC, "no space")

        fd_before = _fd_count()
        mw = MidwayWriter(self.adapter)
        with self.assertRaises(LocalStorageError):
            mw.write_bytes(self._root_ref(), "m.bin", b"abcdef")
        self.assertEqual(os.listdir(self.root), [])
        self.assertEqual(_fd_count(), fd_before)

    @unittest.skipUnless(_HAS_PROC_FD, "requires /proc/self/fd")
    def test_seam_file_fsync_failure_cleans_up(self) -> None:
        class FsyncFailWriter(LocalWriter):
            def _os_fsync(self, fd):  # type: ignore[override]
                st = os.fstat(fd)
                if stat.S_ISREG(st.st_mode):
                    raise OSError(errno.EIO, "simulated fsync failure")
                return os.fsync(fd)

        fd_before = _fd_count()
        w = FsyncFailWriter(self.adapter)
        with self.assertRaises(LocalStorageError):
            w.write_bytes(self._root_ref(), "a.bin", b"x")
        self.assertEqual(os.listdir(self.root), [])
        self.assertEqual(_fd_count(), fd_before)

    @unittest.skipUnless(_HAS_PROC_FD, "requires /proc/self/fd")
    def test_seam_temp_close_failure_before_publish_cleans_up(self) -> None:
        class CloseFailWriter(LocalWriter):
            def _os_close(self, fd):  # type: ignore[override]
                try:
                    os.close(fd)
                except OSError:
                    pass
                raise OSError(errno.EIO, "simulated close failure")

        fd_before = _fd_count()
        w = CloseFailWriter(self.adapter)
        with self.assertRaises(LocalStorageError):
            w.write_bytes(self._root_ref(), "a.bin", b"x")
        self.assertEqual(os.listdir(self.root), [])
        self.assertEqual(_fd_count(), fd_before)

    @unittest.skipUnless(_HAS_PROC_FD, "requires /proc/self/fd")
    def test_seam_link_failures_eexist_and_eperm_clean_up(self) -> None:
        class LinkFailWriter(LocalWriter):
            def __init__(self, *a, exc: OSError | None = None, **kw) -> None:
                super().__init__(*a, **kw)
                self.exc = exc

            def _os_link(  # type: ignore[override]
                self,
                src,
                dst,
                *,
                src_dir_fd,
                dst_dir_fd,
                follow_symlinks=False,
            ):
                assert self.exc is not None
                raise self.exc

        fd_before = _fd_count()
        w1 = LinkFailWriter(self.adapter, exc=OSError(errno.EEXIST, "exists"))
        with self.assertRaises(AlreadyExistsError):
            w1.write_bytes(self._root_ref(), "a.bin", b"x")
        self.assertEqual(os.listdir(self.root), [])
        self.assertEqual(_fd_count(), fd_before)

        w2 = LinkFailWriter(self.adapter, exc=OSError(errno.EPERM, "no link"))
        with self.assertRaises(UnsupportedPlatformError):
            w2.write_bytes(self._root_ref(), "b.bin", b"x")
        self.assertEqual(os.listdir(self.root), [])
        self.assertEqual(_fd_count(), fd_before)

    @unittest.skipUnless(_HAS_PROC_FD, "requires /proc/self/fd")
    def test_seam_rename_failure_cleans_up(self) -> None:
        class RenameFailWriter(LocalWriter):
            def __init__(self, *a, exc: OSError | None = None, **kw) -> None:
                super().__init__(*a, **kw)
                self.exc = exc

            def _os_rename(  # type: ignore[override]
                self, src, dst, *, src_dir_fd, dst_dir_fd
            ):
                assert self.exc is not None
                raise self.exc

        fd_before = _fd_count()
        w1 = RenameFailWriter(self.adapter, exc=OSError(errno.EIO, "io"))
        with self.assertRaises(LocalStorageError):
            w1.write_bytes(
                self._root_ref(), "a.bin", b"x", overwrite=True
            )
        self.assertEqual(os.listdir(self.root), [])
        self.assertEqual(_fd_count(), fd_before)

        w2 = RenameFailWriter(self.adapter, exc=OSError(errno.EISDIR, "dir"))
        with self.assertRaises(IsDirectoryError):
            w2.write_bytes(
                self._root_ref(), "b.bin", b"x", overwrite=True
            )
        self.assertEqual(os.listdir(self.root), [])
        self.assertEqual(_fd_count(), fd_before)

    @unittest.skipUnless(_HAS_PROC_FD, "requires /proc/self/fd")
    def test_seam_dir_fsync_failure_does_not_double_unlink(self) -> None:
        class DirFsyncFailCounting(LocalWriter):
            def __init__(self, *a, **kw) -> None:
                super().__init__(*a, **kw)
                self.unlink_calls: list[str] = []

            def _os_fsync(self, fd):  # type: ignore[override]
                st = os.fstat(fd)
                if stat.S_ISDIR(st.st_mode):
                    raise OSError(errno.EIO, "simulated dir fsync failure")
                return os.fsync(fd)

            def _os_unlink(self, path, *, dir_fd):  # type: ignore[override]
                self.unlink_calls.append(path)
                return os.unlink(path, dir_fd=dir_fd)

        fd_before = _fd_count()

        w1 = DirFsyncFailCounting(self.adapter)
        with self.assertRaises(LocalStorageError):
            w1.write_bytes(self._root_ref(), "a.bin", b"x")
        self.assertEqual(len(w1.unlink_calls), 1)
        self.assertEqual(os.listdir(self.root), [])

        w2 = DirFsyncFailCounting(self.adapter)
        with self.assertRaises(LocalStorageError):
            w2.write_bytes(
                self._root_ref(), "b.bin", b"x", overwrite=True
            )
        self.assertEqual(len(w2.unlink_calls), 0)
        entries = os.listdir(self.root)
        self.assertIn("b.bin", entries)
        self.assertFalse(any(e.startswith(TEMP_PREFIX) for e in entries))

        self.assertEqual(_fd_count(), fd_before)

    def test_mutation_guard_temp_open_flags_and_mode(self) -> None:
        class OpenSpyWriter(LocalWriter):
            def __init__(self, *a, **kw) -> None:
                super().__init__(*a, **kw)
                self.opens: list[tuple[str, int, int]] = []

            def _os_open(  # type: ignore[override]
                self,
                path,
                flags,
                mode=0o777,
                *,
                dir_fd=None,
            ):
                self.opens.append((path, flags, mode))
                return os.open(path, flags, mode, dir_fd=dir_fd)

        w = OpenSpyWriter(self.adapter)
        w.write_bytes(self._root_ref(), "a.bin", b"payload")

        temp_opens = [o for o in w.opens if o[0].startswith(TEMP_PREFIX)]
        self.assertEqual(len(temp_opens), 1)
        _, flags, mode = temp_opens[0]
        self.assertTrue(flags & os.O_WRONLY)
        self.assertTrue(flags & os.O_CREAT)
        self.assertTrue(flags & os.O_EXCL)
        self.assertTrue(flags & os.O_NOFOLLOW)
        self.assertEqual(mode, 0o644)

    def test_mutation_guard_fsync_called_on_file_and_dir_fds(self) -> None:
        class FsyncSpyWriter(LocalWriter):
            def __init__(self, *a, **kw) -> None:
                super().__init__(*a, **kw)
                self.modes: list[int] = []

            def _os_fsync(self, fd):  # type: ignore[override]
                self.modes.append(os.fstat(fd).st_mode)
                return os.fsync(fd)

        w = FsyncSpyWriter(self.adapter)
        w.write_bytes(self._root_ref(), "a.bin", b"x")
        self.assertTrue(stat.S_ISREG(w.modes[0]))
        self.assertTrue(stat.S_ISDIR(w.modes[1]))
        self.assertEqual(len(w.modes), 2)

        w2 = FsyncSpyWriter(self.adapter)
        w2.mkdir(self._root_ref(), "newdir")
        self.assertEqual(len(w2.modes), 1)
        self.assertTrue(stat.S_ISDIR(w2.modes[0]))

class TestRace(BaseLocalWriteTest):
    def test_concurrent_two_writers_race_overwrite_false(self) -> None:
        writer = self.writer
        root_ref = self._root_ref()
        for i in range(20):
            name = f"race_{i}.bin"
            payloads = (b"A" * 64, b"B" * 128)
            barrier = threading.Barrier(2)
            results: list[tuple[str, bytes | None]] = [("pending", None), ("pending", None)]

            def worker(idx: int) -> None:
                barrier.wait()
                try:
                    writer.write_bytes(
                        root_ref, name, payloads[idx], overwrite=False
                    )
                    results[idx] = ("ok", payloads[idx])
                except AlreadyExistsError:
                    results[idx] = ("exists", None)

            t1 = threading.Thread(target=worker, args=(0,))
            t2 = threading.Thread(target=worker, args=(1,))
            t1.start()
            t2.start()
            t1.join()
            t2.join()

            ok = [r for r in results if r[0] == "ok"]
            exists = [r for r in results if r[0] == "exists"]
            self.assertEqual(len(ok), 1)
            self.assertEqual(len(exists), 1)
            with open(os.path.join(self.root, name), "rb") as f:
                self.assertEqual(f.read(), ok[0][1])
        self.assertTrue(_no_temp_entries(self.root))

class TestListingTempFiles(BaseLocalWriteTest):
    def test_list_children_hides_temp_prefix_but_counts_toward_limit(self) -> None:
        with open(
            os.path.join(self.root, TEMP_PREFIX + "stale"), "wb"
        ) as f:
            f.write(b"x")
        with open(os.path.join(self.root, "visible.txt"), "wb") as f:
            f.write(b"y")

        root_ref = self._root_ref()
        children = self.adapter.list_children(root_ref)
        self.assertEqual([c.name for c in children], ["visible.txt"])

        children2 = self.adapter.list_children(root_ref, max_entries=2)
        self.assertEqual([c.name for c in children2], ["visible.txt"])

        with self.assertRaises(EnumerationLimitError):
            self.adapter.list_children(root_ref, max_entries=1)

class TestMkdir(BaseLocalWriteTest):
    def test_mkdir_create_and_exist_ok_matrix(self) -> None:
        writer = self.writer
        root_ref = self._root_ref()

        class FsyncSpy(LocalWriter):
            def __init__(self, *a, **kw) -> None:
                super().__init__(*a, **kw)
                self.fsync_count = 0

            def _os_fsync(self, fd):  # type: ignore[override]
                self.fsync_count += 1
                return os.fsync(fd)

        spy = FsyncSpy(self.adapter)

        # create
        meta = spy.mkdir(root_ref, "subdir")
        self.assertEqual(meta.kind, "directory")
        self.assertEqual(meta.name, "subdir")
        self.assertEqual(meta.ref.file_id, PATH_PREFIX + "subdir")
        self.assertEqual(meta.parent_id, "root")
        self.assertTrue(os.path.isdir(os.path.join(self.root, "subdir")))
        self.assertEqual(spy.fsync_count, 1)

        # exist_ok=False on existing -> AlreadyExistsError
        with self.assertRaises(AlreadyExistsError):
            writer.mkdir(root_ref, "subdir")

        # exist_ok=True on existing directory -> FileMetadata, no fsync
        before = spy.fsync_count
        meta2 = spy.mkdir(root_ref, "subdir", exist_ok=True)
        self.assertEqual(meta2.kind, "directory")
        self.assertEqual(meta2.ref.file_id, PATH_PREFIX + "subdir")
        self.assertEqual(spy.fsync_count, before)

        # exist_ok=True on a regular file -> AlreadyExistsError
        with open(os.path.join(self.root, "afile"), "wb") as f:
            f.write(b"x")
        with self.assertRaises(AlreadyExistsError):
            writer.mkdir(root_ref, "afile", exist_ok=True)
        with self.assertRaises(AlreadyExistsError):
            writer.mkdir(root_ref, "afile")

        # exist_ok on a FIFO -> AlreadyExistsError
        os.mkfifo(os.path.join(self.root, "afifo"), 0o644)
        with self.assertRaises(AlreadyExistsError):
            writer.mkdir(root_ref, "afifo", exist_ok=True)

        # symlink to directory -> UnsafePathError (never accepted)
        os.symlink(
            os.path.join(self.root, "subdir"),
            os.path.join(self.root, "linkdir"),
        )
        with self.assertRaises(UnsafePathError):
            writer.mkdir(root_ref, "linkdir")
        with self.assertRaises(UnsafePathError):
            writer.mkdir(root_ref, "linkdir", exist_ok=True)

        # dangling symlink -> UnsafePathError
        os.symlink(
            os.path.join(self.root, "nowhere"),
            os.path.join(self.root, "dangling"),
        )
        with self.assertRaises(UnsafePathError):
            writer.mkdir(root_ref, "dangling")
        with self.assertRaises(UnsafePathError):
            writer.mkdir(root_ref, "dangling", exist_ok=True)

if __name__ == "__main__":
    unittest.main()
```

Test-catch lines:

- test_storage_exports_new_errors — catches forgetting to export or subclass the new storage error classes.

- test_writer_init_validation — catches accepting a non-LocalAdapter or bool/wrong-type/non-positive max_write_bytes.

- test_write_and_read_back_root_and_nested — catches wrong metadata fields or broken path composition at root and nested parents.

- test_write_empty_and_exact_max_write_bytes — catches an off-by-one in the limit or a broken zero-byte write.

- test_write_exceeds_max_write_bytes_before_disk — catches rejecting oversized data after touching disk.

- test_write_overwrite_false_existing_file — catches using check-then-rename (clobbering) instead of atomic link.

- test_write_overwrite_false_existing_symlink — catches following a symlink on the no-replace link path.

- test_write_overwrite_true_creates_and_replaces — catches a broken overwrite=True create/replace path.

- test_write_overwrite_true_rejects_directory_symlink_fifo — catches missing pre-rename target-type checks for dir/symlink/FIFO.

- test_name_validation_all_invalid_classes — catches a name validator that lets traversal, reserved temp names, oversized or non-UTF-8 names through.

- test_parent_validation_and_containment — catches parent opens that follow symlinks or misclassify missing/file/FIFO/TEMP parents.

- test_precedence_source_mismatch_then_closed_then_args — catches reordering the source/state/argument checks.

- test_seam_write_handles_short_writes_and_eintr — catches a write loop that stops on short writes or doesn't retry EINTR.

- test_seam_write_zero_return_or_midway_oserror_cleans_up — catches a missing zero-return guard or missing temp/fd cleanup on write failure.

- test_seam_file_fsync_failure_cleans_up — catches skipping temp cleanup when the temp-file fsync fails.

- test_seam_temp_close_failure_before_publish_cleans_up — catches publishing after a close failure or double-closing the temp fd.

- test_seam_link_failures_eexist_and_eperm_clean_up — catches a racy fallback to rename or wrong link error mapping.

- test_seam_rename_failure_cleans_up — catches an overwrite=True path that leaks the temp file on rename failure.

- test_seam_dir_fsync_failure_does_not_double_unlink — catches a missing parent fsync or an unconditional unlink in cleanup (double-unlink).

- test_mutation_guard_temp_open_flags_and_mode — catches dropping O_NOFOLLOW/O_EXCL/O_CREAT/O_WRONLY or using the wrong mode on the temp-file open.

- test_mutation_guard_fsync_called_on_file_and_dir_fds — catches skipping the temp-file fsync or the parent-directory fsync in write_bytes/mkdir.

- test_concurrent_two_writers_race_overwrite_false — catches a check-then-create race that lets both writers win or corrupts the file.

- test_list_children_hides_temp_prefix_but_counts_toward_limit — catches forgetting to filter TEMP_PREFIX or filtering before the entry count.

- test_mkdir_create_and_exist_ok_matrix — catches missing EEXIST handling, accepting a symlink with exist_ok, or fsyncing on the exist_ok short-circuit.

STATUS: GENERATED, TESTS_NOT_RUN

Uncertainties: (1) Whether the reviewer prefers _os_stat_nofollow to also be a LocalWriter seam rather than going straight through the adapter — I kept it as an adapter call per Gemini §3, but it can be trivially lifted if a test needs to inject stat failures. (2) The tmp_on_disk = False reset placement on the overwrite=False path is "after successful unlink" rather than Gemini's "immediately when called" — same observable behaviour for tests 19/20/23, but if Sarvam's mutation #2 (skip cleanup) is checked with an unlink failure injection, the difference matters; both variants unlink at most once on the fsync-failure test. (3) os.supports_dir_fd / os.supports_follow_symlinks membership checks are runtime guards; on odd Python builds these sets may be empty even when the calls work, in which case LocalWriter.__init__ would raise UnsupportedPlatformError — Gemini §1 Rule 7 prescribes this fail-closed behaviour. (4) The 10 MiB exact-size test materialises a 10 MiB bytes object; harmless but worth noting for constrained CI.
