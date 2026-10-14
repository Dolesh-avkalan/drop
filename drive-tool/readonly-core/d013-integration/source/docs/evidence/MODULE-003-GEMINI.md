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
