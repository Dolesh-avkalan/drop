# READONLY-CORE-INTEGRATION — d013 assembled read-only core candidate (Sarvam)

Director: Codex. Worker: browser Sarvam. Brief: d013 (assemble and test an
isolated read-only core candidate).
Branch (intended): `feature/readonly-core-candidate`. No merge, no deploy, no
implementation fixes, no dependencies, no adapter/listing/storage edits.

## 0. Status

- **TESTS_RUN** — combined suite passes on Python **3.11.2** and **3.12.13**.
- **PUSH_BLOCKED** — no GitHub write connector is bound to this worker (only the
  read-only public repo fetcher; `gh` unauthenticated). Nothing was written to
  any branch or to `Dolesh-avkalan/drop`. A complete patch/source/evidence bundle
  is delivered as a downloadable zip with a manifest and hashes.
- Assembly verdict: **compatible, no INTEGRATION_BLOCKED**. The MODULE-002 and
  MODULE-003 branches are both additive over the shared MODULE-001 storage
  contract; they combine without any shim.

## 1. Pins and assembled identity

| Item | Value |
| --- | --- |
| Base MODULE-003 candidate | `80bf54885877c475d2ac59ddb3e9f96384600b9e` |
| MODULE-002 source | `bfbae511a538cff22b642fcd771b7a189029f7e8` |
| Shared MODULE-001 base | `194d4ad57de6dd895c6eaaf7faf4d08583eab02b` |

Assembled tree = the MODULE-003 candidate **plus** the three MODULE-002 files
(`drive_tool/listing.py`, `tests/test_listing.py`,
`docs/evidence/MODULE-002.md`), copied byte-for-byte, **plus** two new
integration files (`tests/test_readonly_core.py`,
`docs/evidence/READONLY-CORE-INTEGRATION.md`).

## 2. Compatibility assessment (why not INTEGRATION_BLOCKED)

The shared files are byte-identical across all three pins:

| shared file | blob (all three pins) |
| --- | --- |
| `drive_tool/storage.py` | `28f7b8c0ce7ac56d602d0af3a709c3f31441904b` |
| `drive_tool/__init__.py` | `9be841b5749acb36c5e362c84b986d98292bae8d` |
| `tests/test_storage.py` | `2126dde7f32b7c0cd4d1e737ff990ab10954caf5` |
| `README.md` | `3e23315ec72a68d7b9bb30d2c87b617147e0add6` |

Relative to the MODULE-001 base, each module adds exactly one source file and
touches nothing else: MODULE-003 adds `drive_tool/local.py`; MODULE-002 adds
`drive_tool/listing.py`. `listing.py` imports only
`FileMetadata`, `FileRef`, `StorageAdapter` from `drive_tool.storage` — all
present and unchanged — and `LocalAdapter` satisfies the `StorageAdapter`
protocol (`source_id`, `stat`, `list_children`, `read_bytes`). The two branches
are disjoint additions over a frozen shared contract, so no interface shim was
needed or added.

## 3. Source blob verification (assembled == accepted pins)

Every original source/evidence blob in the assembled tree is byte-identical to
its accepted pin:

| assembled file | blob | pin |
| --- | --- | --- |
| `drive_tool/storage.py` | `28f7b8c0…` | MODULE-001 base |
| `drive_tool/__init__.py` | `9be841b5…` | MODULE-001 base |
| `drive_tool/local.py` | `5da22dd4…` | MODULE-003 candidate |
| `drive_tool/listing.py` | `1ce6f1ab704eeef77de8520a7143b253b532ddf9` | MODULE-002 |
| `tests/test_storage.py` | `2126dde7…` | MODULE-001 base |
| `tests/test_local.py` | `b3319752…` | MODULE-003 candidate |
| `tests/test_listing.py` | `8287db88a4b7ff8d956c082e8150c8d169f0f4f7` | MODULE-002 |
| `docs/evidence/MODULE-002.md` | `84468b790d31f45b8179f14352cfcde85e541028` | MODULE-002 |

A recursive diff of the assembled tree against the MODULE-003 candidate shows
exactly four added files (the three MODULE-002 files and
`tests/test_readonly_core.py`) and no modifications to any existing file. The
original MODULE-002/003 evidence files remain historical; this document
identifies the *assembled* candidate and its new execution.

## 4. Integration tests (`tests/test_readonly_core.py`)

Provenance: written for d013. They drive the **real** `LocalAdapter` through the
**real** `ListingService` over tiny synthetic directories; they do not re-test
either module in isolation (MODULE-002's own tests already exercise the helper
over in-memory/fake adapters, and MODULE-003's tests cover the adapter).

Covered observable cross-module behaviour:

- **Multi-page nested listings** — root pages (`limit=2`) with exact
  `next_offset`; a subdirectory paginated one item at a time
  (`["a.txt","b.txt","deep"]`); a deeper directory; and a full page-size-1 walk
  that reconstructs the same listing as a single large page.
- **Filtering / sorted metadata and refs** — sorted by name; correct
  `ref.source_id`, `ref.file_id` (e.g. `p/sub/a.txt`), `parent_id` (`root` or
  `p/sub`), `kind`, and file `size_bytes`; `name_contains` filtering over the
  real adapter; `ListingPage.items` is a tuple.
- **Omitted symlinks / special entries** — a symlink to an outside file and a
  FIFO are omitted from the real listing (root lists exactly
  `["m.txt","sub","z.txt"]`).
- **Wrong-source propagation** — `SourceMismatchError` from the adapter reaches
  the caller through the service unchanged, including when a filter is also
  supplied.
- **Invalid options avoid adapter work** — with a counting `LocalAdapter`
  subclass, invalid `limit`/`offset`/`name_contains` raise `ValueError` with
  `list_children` call count still 0; a valid call consults the adapter once.
- **Real adapter listing cleanup failure surfaces unchanged** — a `LocalAdapter`
  subclass that fails the close of the listed directory's scan descriptor (real
  close, then injected `OSError`) makes `list_children` raise
  `LocalStorageError`; the service propagates that same error type, not wrapped
  as `ValueError`, with its `OSError` `__cause__` preserved.

Integration file blob: `tests/test_readonly_core.py` =
`1b0f746fd8162a9d27691abf7f5a90492548c4d8` (16 tests).

## 5. Combined suite results (independently established)

Command: `python3.X -m unittest discover -s tests -v` in the assembled tree.

| Interpreter | Result | Exit | Skips |
| --- | --- | --- | --- |
| 3.11.2 | `Ran 140 tests … OK` | 0 | 0 |
| 3.12.13 | `Ran 140 tests … OK` | 0 | 0 |

Per-file counts (identical on both interpreters): `test_storage` 36,
`test_local` 53, `test_listing` 35, `test_readonly_core` 16 — sum **140**. The
count was obtained by running the assembled suite directly, not by adding prior
reports. Full stdout/stderr and exit codes: `logs/suite_python3.11.txt`,
`logs/suite_python3.12.txt`, `logs/00_env.log`.

## 6. Environment

- Kernel `Linux 4.19.0-gvisor x86_64` (gVisor); Debian GNU/Linux 12 (bookworm).
- Filesystems: `/` overlay; `/tmp` and `/scratch` 9p (v9fs),
  `cache=remote_revalidating,disable_fifo_open,directfs`; `TMPDIR=/scratch/tmp`.
- Interpreters: Python 3.11.2 and 3.12.13 (both present and used).

## 7. Current resource and feature boundaries (unchanged by this assembly)

- `read_bytes` is **bounded** (`max_read_bytes`, enforced via `fstat` and a
  `max_read_bytes + 1` read cap).
- **Listing still materialises the whole direct directory**: `ListingService`
  calls `adapter.list_children(parent)` once per page, which reads the entire
  direct directory; **page size is not an enumeration bound** and the adapter
  does not expose a streaming/partial enumeration. Offset pagination is over a
  *fresh* listing, not a consistent snapshot (documented in `listing.py`).
- The local adapter is **POSIX capability-gated** (runtime no-follow probe,
  fail-closed with `UnsupportedPlatformError`); **no native Windows filesystem
  support**.
- No Google Drive connector, no writes, no REST/MCP surface, no jobs, no
  deployment; no production-release or full Drive Tool completeness claim.
- Conformant cloud-box / cloud-kernel tests and integrated MODULE-002 behaviour
  on a conformant kernel remain later gates; the environment here is gVisor/9p.

## 8. Deliverables (manifest)

Intended `Dolesh-avkalan/drop` layout: `drive-tool/readonly-core/d013-integration/`
(not pushed — see §0). The bundle contains:

- `readonly-core.patch` — the assembly delta from the MODULE-003 candidate
  (adds the three MODULE-002 files and the two integration files; no edits).
- `source/` — the assembled `drive_tool/`, `tests/`, `docs/evidence/` and
  `README.md`.
- `logs/` — environment and both combined-suite runs (stdout/stderr/exits).
- `MANIFEST.md` — every file with size and sha256.
- this document.
