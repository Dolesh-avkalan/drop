"""Bounded read-only local filesystem storage adapter (MODULE-003).

This module implements :class:`LocalAdapter`, a read-only :class:`StorageAdapter`
backed by an operator-controlled POSIX directory tree.

Security and containment model:
- Configuration traverses from ``/`` to the target root directory component by
  component using ``O_RDONLY | O_NOFOLLOW | O_NONBLOCK`` opens anchored with
  ``dir_fd`` (deliberately WITHOUT ``O_DIRECTORY``). Each returned descriptor is
  immediately ``fstat``ed and required to be a directory (``S_ISDIR``). The
  ``O_NOFOLLOW`` alone is the atomic guard: a symlink component (final or
  intermediate) makes ``openat`` fail with ``ELOOP``, so a directory swapped for
  a symlink immediately before its open cannot redirect access outside the root.
  ``O_DIRECTORY`` is intentionally omitted because on some kernels (notably the
  gVisor sandbox used for acceptance) ``O_NOFOLLOW`` is ignored when combined
  with ``O_DIRECTORY``, which would silently follow a symlink. Because real
  no-follow semantics are required and a constant being defined is not trusted,
  the adapter probes the running kernel at construction time and fails closed
  with :class:`UnsupportedPlatformError` when ``O_NOFOLLOW`` is not actually
  enforced. The resulting root directory file descriptor is retained until
  :meth:`close`.
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
import shutil
import stat
import sys
import tempfile
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


def _no_follow_semantics_available() -> bool:
    """Actively probe the running kernel for real ``O_NOFOLLOW`` semantics.

    A defined constant is not evidence: some sandboxes (e.g. gVisor) expose
    ``O_NOFOLLOW`` yet ignore it in certain combinations. This creates a tiny
    throwaway directory containing a symlink and confirms that opening the
    symlink with the *exact* flags used for directory components
    (``O_RDONLY | O_NOFOLLOW | O_NONBLOCK``, no ``O_DIRECTORY``) is refused with
    ``ELOOP``/``EMLINK``, while a real directory opens and ``fstat`` reports
    ``S_ISDIR``. Any deviation, including an inability to run the probe, returns
    ``False`` so the caller can fail closed.
    """
    try:
        base = tempfile.mkdtemp(prefix="drive_tool_nofollow_probe_")
    except OSError:
        return False
    try:
        target = os.path.join(base, "target")
        link = os.path.join(base, "link")
        try:
            os.mkdir(target)
            os.symlink(target, link)
        except OSError:
            return False

        # Use the production directory-component flag helper itself, so the
        # probe can never drift from real adapter behaviour: the helper is the
        # single source of truth, resolved at call time (never cached).
        flags = _dir_open_flags()
        try:
            fd = os.open(link, flags)
        except OSError as exc:
            if exc.errno not in (errno.ELOOP, getattr(errno, "EMLINK", -1)):
                return False
        else:
            # The symlink was followed: O_NOFOLLOW is not enforced.
            os.close(fd)
            return False

        try:
            dir_fd = os.open(target, flags)
        except OSError:
            return False
        try:
            if not stat.S_ISDIR(os.fstat(dir_fd).st_mode):
                return False
        finally:
            os.close(dir_fd)
        return True
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _check_platform_capabilities() -> None:
    """Verify that the runtime platform supports anchored no-follow I/O.

    Raises :class:`UnsupportedPlatformError` if any required POSIX feature is
    unavailable, or if a runtime probe shows that ``O_NOFOLLOW`` is not
    actually enforced. Weaker path-string fallbacks are never emulated.
    """
    if os.name != "posix":
        raise UnsupportedPlatformError(
            f"LocalAdapter requires a POSIX platform, got os.name={os.name!r}"
        )

    required_flags = ("O_RDONLY", "O_NOFOLLOW", "O_NONBLOCK")
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

    if not _no_follow_semantics_available():
        raise UnsupportedPlatformError(
            "LocalAdapter requires O_NOFOLLOW to actually reject symbolic links "
            "on this platform (verified by a runtime probe, not merely present "
            "as a constant)"
        )


def _dir_open_flags() -> int:
    """Return flags for a no-follow, non-blocking directory-component open.

    Deliberately excludes ``O_DIRECTORY``: on some kernels ``O_NOFOLLOW`` is
    ignored when combined with ``O_DIRECTORY``, which would silently follow a
    symlink. ``O_NOFOLLOW`` alone is honoured there, so it is the atomic guard;
    the caller verifies the returned descriptor's type with ``fstat``.
    """
    return (
        os.O_RDONLY
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

    # -- descriptor lifetime helpers ------------------------------------------

    def _close_owned_fd(self, fd: int, *, context: str) -> None:
        """Close an owned descriptor on the success path, wrapping OS errors.

        Used where closing the descriptor is part of normal control flow (a
        traversal step succeeded and the previous descriptor is no longer
        needed). Linux releases the descriptor even when ``close`` reports an
        error, so the caller must never retry the close on the same fd.
        """
        try:
            self._os_close(fd)
        except OSError as exc:
            raise LocalStorageError(
                f"failed to close descriptor for {context}: {exc}"
            ) from exc

    def _close_traversal_fd(self, fd: int, *, context: str) -> None:
        """Close a transient descriptor from a ``finally`` block.

        On the normal path a close failure is wrapped in
        :class:`LocalStorageError`. While another exception is already
        propagating the close failure is suppressed, so cleanup can never mask
        the primary storage error (the kernel releases the descriptor
        regardless of the reported error).
        """
        primary = sys.exc_info()[0]
        try:
            self._os_close(fd)
        except OSError as exc:
            if primary is not None:
                return
            raise LocalStorageError(
                f"failed to close descriptor for {context}: {exc}"
            ) from exc

    def _close_quietly(self, fd: int) -> None:
        """Best-effort close used only while unwinding an existing exception."""
        try:
            self._os_close(fd)
        except OSError:
            pass

    def _release_owned(self, owned: list[tuple[int, str]]) -> None:
        """Release each owned descriptor exactly once, in the given order.

        A descriptor is "owned" the moment it is acquired, and is closed exactly
        once here. A failing ``close`` is never retried: Linux releases the
        descriptor even when ``close`` reports an error, and a truly ambiguous
        close cannot be verified from user space, so it must not be retried.
        While another exception is already propagating, close failures are
        suppressed so the primary storage error is never masked; on the success
        path the first close failure is raised as :class:`LocalStorageError`
        with its ``OSError`` cause preserved.
        """
        primary = sys.exc_info()[0]
        first_failure: tuple[str, OSError] | None = None
        for fd, context in owned:
            try:
                self._os_close(fd)
            except OSError as exc:
                if first_failure is None:
                    first_failure = (context, exc)
        if first_failure is not None and primary is None:
            context, exc = first_failure
            raise LocalStorageError(
                f"failed to close descriptor for {context}: {exc}"
            ) from exc

    # -- root initialization ---------------------------------------------------

    def _open_anchored_root(self, raw_root: str, parts: list[str]) -> int:
        """Traverse from ``/`` without following symlinks and return root fd.

        Each component is opened atomically with ``O_NOFOLLOW`` (no
        ``O_DIRECTORY``) and the returned descriptor is ``fstat``ed and required
        to be a directory. A component swapped for a symlink immediately before
        its open is rejected by the kernel with ``ELOOP`` (mapped to
        :class:`UnsafePathError`); there is no separate ``lstat`` and therefore
        no check-to-use window.
        """
        dir_flags = _dir_open_flags()
        try:
            current_fd = self._os_open("/", dir_flags)
        except OSError as exc:
            raise self._classify_root_error("/", None, exc, raw_root) from exc

        try:
            try:
                root_st = self._os_fstat(current_fd)
            except OSError as exc:
                raise LocalStorageError(
                    f"failed to fstat '/' while resolving root {raw_root!r}: {exc}"
                ) from exc
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
                    try:
                        part_st = self._os_fstat(next_fd)
                    except OSError as exc:
                        raise LocalStorageError(
                            f"failed to fstat component {part!r} while "
                            f"resolving root {raw_root!r}: {exc}"
                        ) from exc
                    if not stat.S_ISDIR(part_st.st_mode):
                        raise ValueError(
                            f"root component {part!r} in {raw_root!r} is not a directory"
                        )
                except BaseException:
                    self._close_quietly(next_fd)
                    raise

                # Take ownership of the new descriptor *before* releasing the
                # old one, so a failing close cannot leave the new fd orphaned
                # or cause the old one to be closed twice.
                prev_fd = current_fd
                current_fd = next_fd
                self._close_owned_fd(
                    prev_fd,
                    context=f"root component {part!r} of {raw_root!r}",
                )

            return current_fd
        except BaseException:
            self._close_quietly(current_fd)
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
        directory descriptor for the final intermediate directory. Each
        component is opened atomically with ``O_NOFOLLOW`` (no ``O_DIRECTORY``)
        and the returned descriptor is ``fstat``ed and required to be a
        directory, so a component swapped for a symlink immediately before its
        open is rejected with ``ELOOP``. Intermediate descriptors opened along
        the way are always closed before returning or raising.
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
                        for_directory_op=True,
                    ) from exc

                try:
                    try:
                        st = self._os_fstat(next_fd)
                    except OSError as exc:
                        raise LocalStorageError(
                            f"failed to fstat component {part!r} for "
                            f"{file_id!r}: {exc}"
                        ) from exc
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
                    self._close_quietly(next_fd)
                    raise

                # Take ownership of the new descriptor before releasing the old
                # one (see _open_anchored_root).
                prev_fd = current_fd
                current_fd = next_fd
                if prev_fd != root_fd:
                    self._close_owned_fd(
                        prev_fd, context=f"component {part!r} of {file_id!r}"
                    )

            return current_fd
        except BaseException:
            if current_fd != root_fd:
                self._close_quietly(current_fd)
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
                self._close_traversal_fd(
                    parent_fd, context=f"parent directory of {ref.file_id!r}"
                )

    def list_children(self, parent: FileRef) -> list[FileMetadata]:
        """Return sorted metadata for supported direct children of ``parent``."""
        root_fd = self._check_source_and_state(parent)
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

    def read_bytes(self, ref: FileRef) -> bytes:
        """Read and return the bytes of regular file ``ref`` within bounds."""
        root_fd = self._check_source_and_state(ref)
        parts = _parse_file_id(ref.file_id)

        if not parts:
            raise IsDirectoryError(f"{ROOT_ID!r} is a directory, not a file")

        parent_fd = self._traverse_parent_dir(root_fd, parts[:-1], ref.file_id)
        # A descriptor is owned the moment it is acquired. Once the child file
        # descriptor is opened it is released exactly once by the single
        # ``finally`` below, which also covers the parent-close handoff, so a
        # failing parent close cannot skip the child's cleanup scope.
        owned: list[tuple[int, str]] = []
        if parent_fd != root_fd:
            owned.append((parent_fd, f"parent directory of {ref.file_id!r}"))
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
            owned.append((file_fd, f"file descriptor for {ref.file_id!r}"))
            return self._read_open_file_bounded(file_fd, ref.file_id)
        finally:
            self._release_owned(owned)

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
