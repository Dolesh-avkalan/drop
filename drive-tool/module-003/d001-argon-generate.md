# d001 (gemini)

- status: done
- chat: https://gemini.google.com/app/81d96ca95373b8ae
- model: 4 argon (thinking: high)
- finished: 2026-10-14T13:42:30Z

## Question

You are the implementer for MODULE-003 of the drive-tool project. The input file below is a self-contained bundle: the complete MODULE-003 brief plus the pinned MODULE-001 source you build on (base commit 194d4ad57de6dd895c6eaaf7faf4d08583eab02b). Follow the brief exactly.

Deliver, in this one reply:
1. Each of the three files the brief requires (drive_tool/local.py, tests/test_local.py, docs/evidence/MODULE-003-GEMINI.md), each as a heading with its exact path followed by ONE fenced code block containing the complete file. No ellipses, no "rest unchanged", no truncation.
2. A final status line: GENERATED or BLOCKED, then base commit, tests run or TESTS_NOT_RUN, and limitations.

You cannot push and you may not be able to run code; that is expected. Another worker will assemble your files, run the tests and push them. Do not change MODULE-001 files.

(input files: Dolesh-avkalan/drive-tool:tasks/attachments/MODULE-003-bundle.md@b5424513796834fc8c03a56bee7b0f0f7abc1f74)

## Answer

## drive_tool/local.py

```python
"""Bounded read-only local filesystem storage adapter (MODULE-003).

This module implements :class:`LocalAdapter`, a read-only :class:`StorageAdapter`
backed by an operator-controlled POSIX directory tree.

Security and containment model:
- Configuration traverses from ``/`` to the target root directory component by
  component using ``O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_NONBLOCK`` and
  retains the resulting root directory file descriptor until :meth:`close`.
  Any symlink at the root or in any ancestor component is rejected.
- All subsequent operations (`stat`, `list_children`, `read_bytes`) resolve
  canonical ``p/<relative_posix_path>`` IDs step by step using anchored
  directory descriptors (`dir_fd`) and no-follow semantics (`O_NOFOLLOW` /
  `follow_symlinks=False`). String path prefix checks are never used for
  containment.
- Only regular files and directories are supported. Symbolic links raise
  :class:`UnsafePathError` on direct access or intermediate traversal and are
  omitted from directory listings. FIFOs, sockets, and device nodes raise
  :class:`UnsupportedEntryError` without blocking (`O_NONBLOCK` on open,
  `fstatat` with `AT_SYMLINK_NOFOLLOW` on stat/list) and are omitted from
  directory listings.
- Reads enforce `max_read_bytes` via `fstat` prior to reading and during chunked
  reads by requesting at most `max_read_bytes + 1` total bytes, preventing both
  unbounded memory allocation and bypasses when a file grows concurrently after
  `fstat`.

Documented limitations and threat boundaries:
- Concurrent external writers may modify a file while it is being read; this
  adapter bounds the maximum bytes read but does not provide a coherent
  point-in-time snapshot or cryptographic checksum guarantee.
- Concurrent calls to `stat`/`list_children`/`read_bytes` racing with
  :meth:`close` on the same adapter instance are not supported; callers must
  synchronize lifecycle teardown externally if sharing an instance across
  threads.
- Hard links to outside files, bind mounts, submounts, procfs/sysfs mounts, and
  adversarial provisioning of the root directory itself are outside the scope of
  user-space descriptor traversal and must be controlled by the operator.
"""

from __future__ import annotations

import errno
import os
import stat
from types import TracebackType

from drive_tool.storage import (
    ROOT_ID,
    FileMetadata,
    FileRef,
    IsDirectoryError,
    NotDirectoryError,
    NotFoundError,
    SourceMismatchError,
    StorageError,
)

__all__ = [
    "DEFAULT_MAX_READ_BYTES",
    "PATH_PREFIX",
    "LocalStorageError",
    "UnsafePathError",
    "UnsupportedEntryError",
    "ReadLimitExceededError",
    "AdapterClosedError",
    "UnsupportedPlatformError",
    "LocalAdapter",
]

#: Default upper bound (1 MiB) for ``LocalAdapter.read_bytes``.
DEFAULT_MAX_READ_BYTES = 1_048_576

#: Mandatory prefix for all non-root entry IDs in ``LocalAdapter``.
PATH_PREFIX = "p/"

#: Maximum size of a single ``os.read`` chunk during bounded file reads.
_READ_CHUNK_SIZE = 65_536

class LocalStorageError(StorageError):
    """Base error for local filesystem adapter failures and OS errors."""

class UnsafePathError(LocalStorageError, ValueError):
    """Raised when a path or file_id violates containment or symlink policy."""

class UnsupportedEntryError(LocalStorageError):
    """Raised when an entry is neither a regular file nor a directory."""

class ReadLimitExceededError(LocalStorageError):
    """Raised when a file exceeds the configured ``max_read_bytes`` limit."""

class AdapterClosedError(LocalStorageError):
    """Raised when a storage operation is attempted on a closed adapter."""

class UnsupportedPlatformError(LocalStorageError):
    """Raised when required POSIX descriptor and no-follow features are absent."""

def _check_platform_capabilities() -> None:
    """Verify that the runtime platform supports anchored no-follow I/O.

    Raises :class:`UnsupportedPlatformError` if any required POSIX feature is
    unavailable. Weaker path-string fallbacks are never emulated.
    """
    if os.name != "posix":
        raise UnsupportedPlatformError(
            f"LocalAdapter requires a POSIX platform, got os.name={os.name!r}"
        )

    required_flags = ("O_RDONLY", "O_NOFOLLOW", "O_DIRECTORY", "O_NONBLOCK")
    for flag_name in required_flags:
        flag_val = getattr(os, flag_name, None)
        if not isinstance(flag_val, int) or (
            flag_name != "O_RDONLY" and flag_val == 0
        ):
            raise UnsupportedPlatformError(
                f"LocalAdapter requires os.{flag_name} support on this platform"
            )

    for func_name in ("open", "close", "fstat", "stat", "scandir", "read"):
        if not hasattr(os, func_name):
            raise UnsupportedPlatformError(
                f"LocalAdapter requires os.{func_name} support on this platform"
            )

    supports_dir_fd = getattr(os, "supports_dir_fd", set())
    if os.open not in supports_dir_fd or os.stat not in supports_dir_fd:
        raise UnsupportedPlatformError(
            "LocalAdapter requires dir_fd support for os.open and os.stat"
        )

    supports_follow_symlinks = getattr(os, "supports_follow_symlinks", set())
    if os.stat not in supports_follow_symlinks:
        raise UnsupportedPlatformError(
            "LocalAdapter requires follow_symlinks=False support for os.stat"
        )

    supports_fd = getattr(os, "supports_fd", set())
    if os.scandir not in supports_fd:
        raise UnsupportedPlatformError(
            "LocalAdapter requires file descriptor support for os.scandir"
        )

def _dir_open_flags() -> int:
    """Return flags for non-blocking, no-follow directory opens."""
    return (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | os.O_NONBLOCK
        | getattr(os, "O_CLOEXEC", 0)
    )

def _file_open_flags() -> int:
    """Return flags for non-blocking, no-follow file opens."""
    return (
        os.O_RDONLY
        | os.O_NOFOLLOW
        | os.O_NONBLOCK
        | getattr(os, "O_CLOEXEC", 0)
    )

def _parse_file_id(file_id: object) -> tuple[str, ...]:
    """Validate and decompose ``file_id`` into canonical relative path parts.

    Returns ``()`` for the synthetic ``"root"`` ID, or a non-empty tuple of
    validated path components for ``"p/..."`` IDs. Raises
    :class:`UnsafePathError` on any malformed ID.
    """
    if not isinstance(file_id, str):
        raise UnsafePathError(
            f"file_id must be a str, got {type(file_id).__name__}"
        )
    if file_id == ROOT_ID:
        return ()
    if "\x00" in file_id:
        raise UnsafePathError(f"file_id {file_id!r} must not contain NUL")
    if "\\" in file_id:
        raise UnsafePathError(
            f"file_id {file_id!r} must not contain backslash"
        )
    if file_id.startswith("/"):
        raise UnsafePathError(
            f"file_id {file_id!r} must not be an absolute path"
        )
    if not file_id.startswith(PATH_PREFIX):
        raise UnsafePathError(
            f"file_id {file_id!r} must be {ROOT_ID!r} or start with {PATH_PREFIX!r}"
        )

    rel_path = file_id[len(PATH_PREFIX) :]
    if rel_path == "":
        raise UnsafePathError(
            f"file_id {file_id!r} must have a non-empty relative path"
        )
    if rel_path.endswith("/"):
        raise UnsafePathError(
            f"file_id {file_id!r} must not have a trailing slash"
        )

    parts = rel_path.split("/")
    for part in parts:
        if part == "":
            raise UnsafePathError(
                f"file_id {file_id!r} contains an empty path component"
            )
        if part in (".", ".."):
            raise UnsafePathError(
                f"file_id {file_id!r} contains disallowed component {part!r}"
            )

    return tuple(parts)

def _validate_root_path_string(root: str | os.PathLike[str]) -> tuple[str, list[str]]:
    """Validate the configured root path and split it into traversal parts."""
    if not isinstance(root, (str, os.PathLike)):
        raise ValueError(
            f"root must be a str or os.PathLike, got {type(root).__name__}"
        )
    try:
        raw_root = os.fspath(root)
    except TypeError as exc:
        raise ValueError(f"root must be a valid path: {exc}") from exc

    if not isinstance(raw_root, str) or raw_root == "":
        raise ValueError("root must be a non-empty string path")
    if "\x00" in raw_root:
        raise UnsafePathError("root path must not contain NUL bytes")
    if "\\" in raw_root:
        raise UnsafePathError("root path must not contain backslashes")
    if not raw_root.startswith("/"):
        raise UnsafePathError(f"root path must be absolute, got {raw_root!r}")

    if raw_root == "/":
        return raw_root, []

    parts = raw_root[1:].split("/")
    for part in parts:
        if part == "":
            raise UnsafePathError(
                f"root path {raw_root!r} must not contain empty components or trailing slash"
            )
        if part in (".", ".."):
            raise UnsafePathError(
                f"root path {raw_root!r} must not contain {part!r} components"
            )
    return raw_root, parts

class LocalAdapter:
    """Bounded read-only storage adapter anchored to a POSIX directory descriptor.

    Parameters
    ----------
    source_id:
        Non-empty string identifying this storage source.
    root:
        Canonical absolute path to an existing directory with no symbolic link
        in any path component.
    max_read_bytes:
        Maximum file size in bytes permitted by :meth:`read_bytes` (default
        1,048,576). Must be a positive ``int`` (``bool`` is rejected).
    """

    def __init__(
        self,
        source_id: str,
        root: str | os.PathLike[str],
        *,
        max_read_bytes: int = DEFAULT_MAX_READ_BYTES,
    ) -> None:
        if not isinstance(source_id, str) or source_id == "":
            raise ValueError("source_id must be a non-empty string")
        if (
            isinstance(max_read_bytes, bool)
            or not isinstance(max_read_bytes, int)
            or max_read_bytes <= 0
        ):
            raise ValueError("max_read_bytes must be a positive integer")

        _check_platform_capabilities()
        raw_root, root_parts = _validate_root_path_string(root)

        self._source_id = source_id
        self._max_read_bytes = max_read_bytes
        self._closed = False
        self._root_fd: int | None = None
        self._root_fd = self._open_anchored_root(raw_root, root_parts)

    @property
    def source_id(self) -> str:
        """The source identifier exposed by this adapter."""
        return self._source_id

    @property
    def max_read_bytes(self) -> int:
        """The maximum number of bytes permitted for :meth:`read_bytes`."""
        return self._max_read_bytes

    def close(self) -> None:
        """Close the retained root directory descriptor.

        Idempotent: subsequent calls to :meth:`close` are no-ops. Storage
        operations invoked after :meth:`close` raise :class:`AdapterClosedError`
        (after checking for :class:`SourceMismatchError`).
        """
        if not self._closed:
            self._closed = True
            fd = self._root_fd
            self._root_fd = None
            if fd is not None:
                try:
                    self._os_close(fd)
                except OSError as exc:
                    raise LocalStorageError(
                        f"failed to close root descriptor for {self._source_id!r}: {exc}"
                    ) from exc

    def __enter__(self) -> LocalAdapter:
        if self._closed or self._root_fd is None:
            raise AdapterClosedError(
                f"LocalAdapter for source {self._source_id!r} is closed"
            )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    def __del__(self) -> None:
        # Best-effort descriptor cleanup if the caller forgot to close the adapter.
        try:
            self.close()
        except Exception:
            pass

    # -- low-level OS seams (facilitate deterministic unit/adversarial tests) --

    def _os_open(
        self, path: str, flags: int, *, dir_fd: int | None = None
    ) -> int:
        return os.open(path, flags, dir_fd=dir_fd)

    def _os_close(self, fd: int) -> None:
        os.close(fd)

    def _os_fstat(self, fd: int) -> os.stat_result:
        return os.fstat(fd)

    def _os_stat_nofollow(self, path: str, *, dir_fd: int) -> os.stat_result:
        return os.stat(path, dir_fd=dir_fd, follow_symlinks=False)

    def _os_scandir(self, fd: int):
        return os.scandir(fd)

    def _os_read(self, fd: int, length: int) -> bytes:
        return os.read(fd, length)

    # -- root initialization ---------------------------------------------------

    def _open_anchored_root(self, raw_root: str, parts: list[str]) -> int:
        """Traverse from ``/`` without following symlinks and return root fd."""
        dir_flags = _dir_open_flags()
        try:
            current_fd = self._os_open("/", dir_flags)
        except OSError as exc:
            raise self._classify_root_error("/", None, exc, raw_root) from exc

        try:
            root_st = self._os_fstat(current_fd)
            if not stat.S_ISDIR(root_st.st_mode):
                raise ValueError("filesystem '/' is not a directory")

            for part in parts:
                try:
                    next_fd = self._os_open(part, dir_flags, dir_fd=current_fd)
                except OSError as exc:
                    raise self._classify_root_error(
                        part, current_fd, exc, raw_root
                    ) from exc

                try:
                    part_st = self._os_fstat(next_fd)
                    if not stat.S_ISDIR(part_st.st_mode):
                        raise ValueError(
                            f"root component {part!r} in {raw_root!r} is not a directory"
                        )
                except BaseException:
                    self._os_close(next_fd)
                    raise

                self._os_close(current_fd)
                current_fd = next_fd

            return current_fd
        except BaseException:
            self._os_close(current_fd)
            raise

    def _classify_root_error(
        self,
        part: str,
        parent_fd: int | None,
        exc: OSError,
        raw_root: str,
    ) -> Exception:
        """Translate an ``OSError`` during root setup into a contract error."""
        if exc.errno in (errno.ELOOP, getattr(errno, "EMLINK", -1)):
            return UnsafePathError(
                f"symlink rejected at component {part!r} in root {raw_root!r}"
            )
        if parent_fd is not None:
            try:
                st = self._os_stat_nofollow(part, dir_fd=parent_fd)
            except OSError:
                st = None
            if st is not None:
                if stat.S_ISLNK(st.st_mode):
                    return UnsafePathError(
                        f"symlink rejected at component {part!r} in root {raw_root!r}"
                    )
                if not stat.S_ISDIR(st.st_mode):
                    return ValueError(
                        f"root component {part!r} in {raw_root!r} is not a directory"
                    )
        if exc.errno in (errno.ENOENT, errno.ENOTDIR):
            return ValueError(
                f"root {raw_root!r} must be an existing directory: {exc}"
            )
        return LocalStorageError(
            f"failed to open root {raw_root!r} at component {part!r}: {exc}"
        )

    # -- internal helpers ------------------------------------------------------

    def _check_source_and_state(self, ref: FileRef) -> int:
        """Enforce source mismatch first, then adapter open state.

        Returns the active root directory descriptor.
        """
        if not isinstance(ref, FileRef):
            raise TypeError(f"expected FileRef, got {type(ref).__name__}")
        if ref.source_id != self._source_id:
            raise SourceMismatchError(
                f"ref source_id {ref.source_id!r} does not match "
                f"adapter source_id {self._source_id!r}"
            )
        if self._closed or self._root_fd is None:
            raise AdapterClosedError(
                f"LocalAdapter for source {self._source_id!r} is closed"
            )
        return self._root_fd

    def _root_metadata(self) -> FileMetadata:
        return FileMetadata(
            ref=FileRef(self._source_id, ROOT_ID),
            name="",
            parent_id=None,
            kind="directory",
            size_bytes=None,
        )

    def _build_metadata(
        self,
        parts: tuple[str, ...],
        *,
        kind: str,
        size_bytes: int | None,
    ) -> FileMetadata:
        if not parts:
            return self._root_metadata()
        file_id = PATH_PREFIX + "/".join(parts)
        parent_id = (
            ROOT_ID
            if len(parts) == 1
            else PATH_PREFIX + "/".join(parts[:-1])
        )
        return FileMetadata(
            ref=FileRef(self._source_id, file_id),
            name=parts[-1],
            parent_id=parent_id,
            kind=kind,
            size_bytes=size_bytes if kind == "file" else None,
        )

    def _classify_component_open_error(
        self,
        part: str,
        parent_fd: int,
        exc: OSError,
        file_id: str,
        *,
        is_intermediate: bool,
        for_directory_op: bool,
    ) -> Exception:
        """Classify an ``OSError`` from a no-follow ``openat`` on ``part``."""
        if exc.errno == errno.ENOENT:
            return NotFoundError(f"entry {file_id!r} not found")
        if exc.errno in (errno.ELOOP, getattr(errno, "EMLINK", -1)):
            return UnsafePathError(
                f"symlink encountered at {part!r} for {file_id!r}"
            )
        if exc.errno == errno.EISDIR and not for_directory_op and not is_intermediate:
            return IsDirectoryError(f"{file_id!r} is a directory, not a file")

        try:
            st = self._os_stat_nofollow(part, dir_fd=parent_fd)
        except OSError as stat_exc:
            if stat_exc.errno == errno.ENOENT:
                return NotFoundError(f"entry {file_id!r} not found")
            if stat_exc.errno in (errno.ELOOP, getattr(errno, "EMLINK", -1)):
                return UnsafePathError(
                    f"symlink encountered at {part!r} for {file_id!r}"
                )
            st = None

        if st is not None:
            if stat.S_ISLNK(st.st_mode):
                return UnsafePathError(
                    f"symlink encountered at {part!r} for {file_id!r}"
                )
            if stat.S_ISDIR(st.st_mode):
                if not for_directory_op and not is_intermediate:
                    return IsDirectoryError(
                        f"{file_id!r} is a directory, not a file"
                    )
            elif stat.S_ISREG(st.st_mode):
                if is_intermediate or for_directory_op:
                    return NotDirectoryError(
                        f"component {part!r} in {file_id!r} is not a directory"
                    )
            else:
                return UnsupportedEntryError(
                    f"unsupported special filesystem entry at {part!r} for {file_id!r}"
                )

        if exc.errno == errno.ENOTDIR:
            return NotDirectoryError(
                f"component {part!r} in {file_id!r} is not a directory"
            )
        return LocalStorageError(
            f"OS failure accessing {part!r} for {file_id!r}: {exc}"
        )

    def _traverse_parent_dir(
        self, root_fd: int, dir_parts: tuple[str, ...], file_id: str
    ) -> int:
        """Traverse intermediate directory components from ``root_fd``.

        Returns ``root_fd`` when ``dir_parts`` is empty, or a newly opened
        directory descriptor for the final intermediate directory. Intermediate
        descriptors opened along the way are always closed before returning or
        raising.
        """
        if not dir_parts:
            return root_fd

        dir_flags = _dir_open_flags()
        current_fd = root_fd
        try:
            for part in dir_parts:
                try:
                    next_fd = self._os_open(part, dir_flags, dir_fd=current_fd)
                except OSError as exc:
                    raise self._classify_component_open_error(
                        part,
                        current_fd,
                        exc,
                        file_id,
                        is_intermediate=True,
                        for_directory_op= True,
                    ) from exc

                try:
                    st = self._os_fstat(next_fd)
                    if not stat.S_ISDIR(st.st_mode):
                        if stat.S_ISLNK(st.st_mode):
                            raise UnsafePathError(
                                f"symlink encountered at {part!r} for {file_id!r}"
                            )
                        if stat.S_ISREG(st.st_mode):
                            raise NotDirectoryError(
                                f"component {part!r} in {file_id!r} is not a directory"
                            )
                        raise UnsupportedEntryError(
                            f"unsupported entry at {part!r} for {file_id!r}"
                        )
                except BaseException:
                    self._os_close(next_fd)
                    raise

                if current_fd != root_fd:
                    self._os_close(current_fd)
                current_fd = next_fd

            return current_fd
        except BaseException:
            if current_fd != root_fd:
                self._os_close(current_fd)
            raise

    # -- public StorageAdapter contract ----------------------------------------

    def stat(self, ref: FileRef) -> FileMetadata:
        """Return metadata for ``ref`` without following symbolic links."""
        root_fd = self._check_source_and_state(ref)
        parts = _parse_file_id(ref.file_id)

        if not parts:
            try:
                st = self._os_fstat(root_fd)
            except OSError as exc:
                raise LocalStorageError(
                    f"failed to stat anchored root for {self._source_id!r}: {exc}"
                ) from exc
            if not stat.S_ISDIR(st.st_mode):
                raise LocalStorageError(
                    f"anchored root for {self._source_id!r} is not a directory"
                )
            return self._root_metadata()

        parent_fd = self._traverse_parent_dir(root_fd, parts[:-1], ref.file_id)
        try:
            target_name = parts[-1]
            try:
                st = self._os_stat_nofollow(target_name, dir_fd=parent_fd)
            except OSError as exc:
                if exc.errno == errno.ENOENT:
                    raise NotFoundError(
                        f"entry {ref.file_id!r} not found"
                    ) from exc
                if exc.errno == errno.ENOTDIR:
                    raise NotDirectoryError(
                        f"parent of {ref.file_id!r} is not a directory"
                    ) from exc
                if exc.errno in (errno.ELOOP, getattr(errno, "EMLINK", -1)):
                    raise UnsafePathError(
                        f"symlink encountered for {ref.file_id!r}"
                    ) from exc
                raise LocalStorageError(
                    f"failed to stat {ref.file_id!r}: {exc}"
                ) from exc

            if stat.S_ISLNK(st.st_mode):
                raise UnsafePathError(
                    f"entry {ref.file_id!r} is a symbolic link"
                )
            if stat.S_ISDIR(st.st_mode):
                return self._build_metadata(
                    parts, kind="directory", size_bytes=None
                )
            if stat.S_ISREG(st.st_mode):
                return self._build_metadata(
                    parts, kind="file", size_bytes=st.st_size
                )
            raise UnsupportedEntryError(
                f"entry {ref.file_id!r} has unsupported file mode {oct(st.st_mode)}"
            )
        finally:
            if parent_fd != root_fd:
                self._os_close(parent_fd)

    def list_children(self, parent: FileRef) -> list[FileMetadata]:
        """Return sorted metadata for supported direct children of ``parent``."""
        root_fd = self._check_source_and_state(parent)
        parts = _parse_file_id(parent.file_id)
        dir_flags = _dir_open_flags()

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
            try:
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
            finally:
                if parent_fd != root_fd:
                    self._os_close(parent_fd)

        try:
            dir_st = self._os_fstat(scan_fd)
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
            scandir_it = self._os_scandir(scan_fd)
        except BaseException as exc:
            self._os_close(scan_fd)
            if isinstance(exc, StorageError):
                raise
            if isinstance(exc, OSError):
                raise LocalStorageError(
                    f"failed to scan directory {parent.file_id!r}: {exc}"
                ) from exc
            raise

        # Note: once os.scandir(scan_fd) succeeds, exiting the context manager
        # calls closedir() in C, which closes scan_fd automatically.
        children: list[FileMetadata] = []
        with scandir_it as entries:
            for entry in entries:
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
                        f"failed to inspect child {name!r} in {parent.file_id!r}: {exc}"
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

        children.sort(key=lambda meta: meta.name)
        return children

    def read_bytes(self, ref: FileRef) -> bytes:
        """Read and return the bytes of regular file ``ref`` within bounds."""
        root_fd = self._check_source_and_state(ref)
        parts = _parse_file_id(ref.file_id)

        if not parts:
            raise IsDirectoryError(f"{ROOT_ID!r} is a directory, not a file")

        parent_fd = self._traverse_parent_dir(root_fd, parts[:-1], ref.file_id)
        try:
            target_name = parts[-1]
            try:
                file_fd = self._os_open(
                    target_name, _file_open_flags(), dir_fd=parent_fd
                )
            except OSError as exc:
                raise self._classify_component_open_error(
                    target_name,
                    parent_fd,
                    exc,
                    ref.file_id,
                    is_intermediate=False,
                    for_directory_op=False,
                ) from exc
        finally:
            if parent_fd != root_fd:
                self._os_close(parent_fd)

        try:
            return self._read_open_file_bounded(file_fd, ref.file_id)
        finally:
            self._os_close(file_fd)

    def _read_open_file_bounded(self, file_fd: int, file_id: str) -> bytes:
        """Verify ``file_fd`` is a regular file and read up to ``max_read_bytes``."""
        try:
            st = self._os_fstat(file_fd)
        except OSError as exc:
            raise LocalStorageError(
                f"failed to fstat opened file {file_id!r}: {exc}"
            ) from exc

        if stat.S_ISDIR(st.st_mode):
            raise IsDirectoryError(f"{file_id!r} is a directory, not a file")
        if stat.S_ISLNK(st.st_mode):
            raise UnsafePathError(f"{file_id!r} is a symbolic link")
        if not stat.S_ISREG(st.st_mode):
            raise UnsupportedEntryError(
                f"{file_id!r} is not a regular file (mode {oct(st.st_mode)})"
            )

        if st.st_size > self._max_read_bytes:
            raise ReadLimitExceededError(
                f"file {file_id!r} size ({st.st_size} bytes) exceeds "
                f"max_read_bytes ({self._max_read_bytes} bytes)"
            )

        chunks: list[bytes] = []
        total_read = 0
        max_allowed = self._max_read_bytes
        read_cap = max_allowed + 1

        while True:
            remaining_cap = read_cap - total_read
            if remaining_cap <= 0:
                raise ReadLimitExceededError(
                    f"file {file_id!r} exceeded max_read_bytes "
                    f"({max_allowed} bytes) while reading"
                )
            request_size = min(_READ_CHUNK_SIZE, remaining_cap)
            try:
                chunk = self._os_read(file_fd, request_size)
            except OSError as exc:
                if exc.errno == errno.EINTR:
                    continue
                raise LocalStorageError(
                    f"failed while reading {file_id!r}: {exc}"
                ) from exc

            if not chunk:
                break

            total_read += len(chunk)
            if total_read > max_allowed:
                raise ReadLimitExceededError(
                    f"file {file_id!r} exceeded max_read_bytes "
                    f"({max_allowed} bytes) while reading"
                )
            chunks.append(chunk)

        return b"".join(chunks)
```

## tests/test_local.py

```python
"""Unit and containment tests for MODULE-003 (drive_tool.local)."""

from __future__ import annotations

import errno
import os
import shutil
import socket
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

def _is_supported_posix() -> bool:
    """Return True when the current platform supports LocalAdapter."""
    return (
        os.name == "posix"
        and hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NONBLOCK")
        and os.open in getattr(os, "supports_dir_fd", set())
        and os.stat in getattr(os, "supports_dir_fd", set())
        and os.stat in getattr(os, "supports_follow_symlinks", set())
        and os.scandir in getattr(os, "supports_fd", set())
    )

class _PosixTempRootTestCase(unittest.TestCase):
    """Base test case providing a canonical symlink-free temporary directory."""

    def setUp(self) -> None:
        if not _is_supported_posix():
            self.skipTest("POSIX dir_fd/O_NOFOLLOW capabilities required")
        # Resolve any OS-level symlinks in the system temp root (e.g. /tmp -> /private/tmp)
        # so the base fixture path has zero symlinks in its ancestor chain from /.
        raw_base = tempfile.mkdtemp(prefix="drive_tool_mod003_")
        self.base_dir = Path(os.path.realpath(raw_base))
        self.root_dir = self.base_dir / "root"
        self.outside_dir = self.base_dir / "outside"
        self.root_dir.mkdir()
        self.outside_dir.mkdir()

    def tearDown(self) -> None:
        if hasattr(self, "base_dir") and self.base_dir.exists():
            shutil.rmtree(self.base_dir, ignore_errors=True)

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

        active_fds: set[int] = set()
        orig_open = os.open
        orig_close = os.close
        orig_scandir = os.scandir

        class _TrackedScandirWrapper:
            def __init__(self, fd: int) -> None:
                self._fd = fd
                self._inner = orig_scandir(fd)

            def __enter__(self):
                return self._inner.__enter__()

            def __exit__(self, exc_type, exc_val, exc_tb):
                try:
                    return self._inner.__exit__(exc_type, exc_val, exc_tb)
                finally:
                    active_fds.discard(self._fd)

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

if __name__ == "__main__":
    unittest.main()
```

## docs/evidence/MODULE-003-GEMINI.md

```markdown
# MODULE-003 Evidence Report — Bounded Read-Only Local Adapter (Gemini)

- **Module:** MODULE-003 (`drive_tool/local.py`, `tests/test_local.py`)
- **Base commit:** `194d4ad57de6dd895c6eaaf7faf4d08583eab02b` (MODULE-001)
- **Target branch for later submission:** `feature/module-003-local-readonly`
- **Implementer:** Gemini (Gemini 3.1 Pro web worker)
- **Execution status in this environment:** `TESTS_NOT_RUN` (offline generation environment; browser Sarvam will assemble files, execute the test suite in its sandbox, and record live runtime provenance in `docs/evidence/MODULE-003.md`).

---

## 1. Design Rationale

### 1.1 Capability Gating
`LocalAdapter` is gated on POSIX descriptor and no-follow primitives (`os.name == "posix"`, `O_RDONLY`, `O_NOFOLLOW`, `O_DIRECTORY`, `O_NONBLOCK`, `os.open` and `os.stat` in `os.supports_dir_fd`, `os.stat` in `os.supports_follow_symlinks`, and `os.scandir` in `os.supports_fd`). If any capability is missing, `_check_platform_capabilities()` immediately raises `UnsupportedPlatformError` without falling back to string-based path checks.

### 1.2 Anchored Root Descriptor and Component-Wise No-Follow Traversal
String `Path.resolve()` + `startswith()` checks are vulnerable to time-of-check to time-of-use (TOCTOU) symlink swaps and root directory renames. Instead:
1. **Root anchoring (`_open_anchored_root`):** During `__init__`, `LocalAdapter` validates that `root` is an canonical absolute POSIX path without empty, `.`, or `..` segments, opens `"/"` with `O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC`, and steps through each path component via `os.open(part, dir_flags, dir_fd=current_fd)`. Each intermediate descriptor is closed immediately after advancing. Any symbolic link at the root or any ancestor component fails with `ELOOP` (or is detected via no-follow `fstatat`) and raises `UnsafePathError`. Only the final root descriptor (`_root_fd`) is retained until `close()`.
2. **Relative traversal (`_traverse_parent_dir`):** Every storage operation parses `ref.file_id` into validated canonical path components under the `"p/"` prefix (or `()` for `"root"`), then steps from `_root_fd` through `parts[:-1]` using `dir_fd`-anchored `os.open` calls with `O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC`.

### 1.3 Non-Blocking Special-Entry Rejection Strategy
Opening a POSIX FIFO (named pipe) with `O_RDONLY` without `O_NONBLOCK` blocks inside the kernel `openat` syscall when no writer is present. To prevent hangs while preserving race-free inode inspection:
- **`stat`:** Uses `os.stat(target, dir_fd=parent_fd, follow_symlinks=False)` (`fstatat` with `AT_SYMLINK_NOFOLLOW`). It never opens the target entry, rejects `S_ISLNK` with `UnsafePathError`, accepts `S_ISREG` and `S_ISDIR`, and rejects FIFOs/sockets/devices with `UnsupportedEntryError`.
- **`list_children`:** Opens a fresh directory descriptor (`"."` relative to `_root_fd` for root, or `target` relative to `parent_fd` with `O_DIRECTORY | O_NOFOLLOW | O_NONBLOCK`), hands it to `with os.scandir(scan_fd):`, and inspects each child with `entry.stat(follow_symlinks=False)`. Entries disappearing mid-scan (`ENOENT`) are skipped; symlinks and special entries are omitted without ever being opened or followed; supported regular files and directories are returned sorted by `name`.
- **`read_bytes`:** Opens the final component with `O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC` relative to `parent_fd` and immediately inspects the opened descriptor via `os.fstat(file_fd)`. If the target is a FIFO without a writer, `O_NONBLOCK` ensures `openat` returns immediately instead of hanging, and `os.fstat(file_fd)` reveals `S_ISFIFO`, closes `file_fd`, and raises `UnsupportedEntryError`. If `openat` itself fails (e.g. `ELOOP` on a symlink, `ENXIO`/`EOPNOTSUPP` on a Unix domain socket), `_classify_component_open_error` inspects the entry via no-follow `fstatat` and raises `UnsafePathError` for symlinks, `IsDirectoryError` for directories, `UnsupportedEntryError` for sockets/devices/FIFOs, or `NotFoundError` when missing.

### 1.4 Bounded Reads and Growth Protection
`_read_open_file_bounded` enforces `max_read_bytes` in two layers:
1. **Upfront `fstat` gate:** If `st.st_size > self._max_read_bytes`, `ReadLimitExceededError` is raised before any read buffer is allocated or `os.read` is called.
2. **Streaming cap (`max_read_bytes + 1`):** Reads proceed in chunks of at most `min(65536, (max_read_bytes + 1) - total_read)` bytes. If the file grows concurrently after `fstat`, at most `max_read_bytes + 1` total bytes are ever read before `total_read > max_read_bytes` triggers `ReadLimitExceededError`. Memory allocation is never proportional to an untrusted `st_size`.

### 1.5 Error Hierarchy and Check Precedence
Every public method (`stat`, `list_children`, `read_bytes`) enforces checks in strict order:
1. `isinstance(ref, FileRef)` -> `TypeError`
2. `ref.source_id != self._source_id` -> `SourceMismatchError` (checked before closed-state and before `file_id` validation)
3. `self._closed` -> `AdapterClosedError`
4. `_parse_file_id(ref.file_id)` -> `UnsafePathError`
5. Anchored descriptor traversal and operation execution -> `NotFoundError`, `NotDirectoryError`, `IsDirectoryError`, `UnsafePathError`, `UnsupportedEntryError`, `ReadLimitExceededError`, or `LocalStorageError` (with preserved `__cause__`).

---

## 2. Threat Boundaries and Limitations

1. **No Snapshot Isolation Against Concurrent External Writers:** If an external process modifies or truncates a regular file while `read_bytes` is reading it, the returned bytes may reflect a torn read across chunks. `LocalAdapter` guarantees only that at most `max_read_bytes` bytes are returned (and at most `max_read_bytes + 1` bytes are read), not a coherent point-in-time snapshot or checksum.
2. **Single-Threaded Close Lifecycle:** Concurrent calls to storage operations racing with `adapter.close()` on the same instance are not supported. Callers sharing an adapter across threads must synchronize `close()` externally.
3. **Hard Links, Mount Policy, and Operator Root Control:** User-space `openat(..., O_NOFOLLOW)` prevents symbolic link traversal, but hard links to outside inodes within the same filesystem, bind mounts, submounts, or procfs/sysfs exposures inside the configured root cannot be distinguished from regular files/directories by `O_NOFOLLOW` alone. Configured roots must be provisioned and controlled by a trusted operator. This module does not claim full OS sandbox completeness.

---

## 3. Tests Written (`tests/test_local.py`)

- `TestPlatformCapabilityGate`: Verifies error hierarchy inheritance and deterministic `UnsupportedPlatformError` when `os.name`, `O_NOFOLLOW`, `supports_dir_fd`, `supports_follow_symlinks`, or `supports_fd` are absent.
- `TestConfigurationAndRootValidation`: Verifies `ValueError` on invalid `source_id`, boolean/non-positive `max_read_bytes`, non-absolute or non-canonical root paths, missing roots, and file roots; verifies `UnsafePathError` on symlink root and symlink ancestor components.
- `TestBasicOperationsAndMetadata`: Verifies `StorageAdapter` protocol compliance, synthetic `"root"` vs real top-level file `"p/root"`, empty files, exact binary payloads, nested directories, `parent_id` chains, repeatable sorted directory listings, and empty directory listings.
- `TestPrecedenceAndMalformedIds`: Verifies `SourceMismatchError` precedence across `stat`, `list_children`, and `read_bytes` (including malformed IDs and after `close()`), `NotFoundError`, `IsDirectoryError`, `NotDirectoryError` (including intermediate regular file traversal), and all malformed ID classes (empty, missing `p/`, absolute, repeated/trailing slashes, `.`, `..`, backslash, NUL).
- `TestContainmentSymlinksAndAnchoredRoot`: Verifies rejection of final and intermediate symlinks (pointing outside root, inside root, and broken), omission of symlinks and disappearing entries during `list_children`, root directory rename + outside symlink replacement staying anchored to the original directory descriptor, and deterministic adversarial symlink swaps between `stat` and `read_bytes` as well as mid-traversal.
- `TestBoundedReads`: Verifies reads below (`15`), at (`16`), and above (`17`) `max_read_bytes=16`, plus deterministic file growth after `fstat` and multi-chunk streaming growth proving at most `max_read_bytes + 1` bytes are ever read.
- `TestSpecialEntriesAndNonblockingFifo`: Verifies inside a timeout-bounded child process (`timeout=5.0`) that a writerless FIFO (`os.mkfifo`) raises `UnsupportedEntryError` on `stat`, `read_bytes`, and `list_children` without blocking and is omitted from parent listing; also tests `AF_UNIX` socket nodes.
- `TestDescriptorLifetimeAndClose`: Verifies `close()` idempotency, `AdapterClosedError` after close, deterministic `_os_open`/`_os_close`/`_os_scandir` descriptor accounting across successful and failing paths, and bounded `/proc/self/fd` descriptor count on Linux.

---

## 4. Execution Log and Unresolved Risks

- **Execution command for Sarvam sandbox:** `python3 -m unittest discover -s tests -v`
- **Execution status:** `TESTS_NOT_RUN` (generated in code-only environment without local shell execution).
- **Unresolved risks:** Kernel/filesystem behavior under extreme concurrent rename stress (`EAGAIN`/dcache races on exotic network filesystems) and operator misconfiguration of hard links or bind mounts inside the root directory remain outside unit-test proof and require director security review and VPS integration gating.
```

GENERATED | base commit: 194d4ad57de6dd895c6eaaf7faf4d08583eab02b | sources: drive_tool/local.py, tests/test_local.py, docs/evidence/MODULE-003-GEMINI.md | tests: TESTS_NOT_RUN | limitations: no code execution or git push in this environment; concurrent external file mutations during read_bytes, concurrent close() races, hard links, and mount policy remain documented threat boundaries.
