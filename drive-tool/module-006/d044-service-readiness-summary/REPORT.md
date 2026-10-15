# D044 — cloud Sarvam: service readiness audit (parallel)

**Status: TESTS_NOT_RUN — design/source review only.** No service implementation, no
installs, no credentials, no main/feature source changes, no merge, no deployment.
This report does not accept D040 (range reads) by implication and does not alter or
duplicate the independent D043 range-verification work on another host. The final
contract and integration are the director's to choose.

## 0. Access and pins

GitHub **read and publish access confirmed** in this account for `Dolesh-avkalan/drive-tool`
and `Dolesh-avkalan/drop`. Every input below was retrieved directly from the pinned commit
(not inline relay text), and byte hashes were recorded for the four source files so the
mapping can be re-checked later.

| # | Input | Repo @ commit | Retrieved as | SHA-256 |
| - | ----- | ------------- | ------------ | ------- |
| 1 | D044 brief | `drive-tool` @ `d6d1a8e351d358af6c9c12c0d6bd47076d22e17a` `tasks/d044-service-readiness.md` | brief | `f4ee35501038d8a0cdad935843751e18b781946c85a6e7fc56b63c9cf7edc2c6` |
| 2 | Accepted lib | `drive-tool` @ `03a8250a5d02823812533290356cf375b7d2c33e` `drive_tool/storage.py` | accepted | `422f22fb7e38e9a1dc51e4e3e88868dfc0c77f292dc759801aff93a9c945c6d2` |
| 2 | Accepted lib | `drive-tool` @ `03a8250` `drive_tool/local.py` | accepted | `fd5b7e83ee50d3e3904b03919558c2953fbc4b3288b266ab153e3bcb02aa8c77` |
| 2 | Accepted lib | `drive-tool` @ `03a8250` `drive_tool/local_write.py` | accepted | `8a53c8467f5367d9617fd165cebdb0382adbc1ecdcb7a8568af902f6a20585ca` |
| 2 | Accepted lib | `drive-tool` @ `03a8250` `drive_tool/listing.py` | accepted | `7a125e899124a1e1a3251f1e949d143b7f08fc89d71ff6ea906284abf0456734` |
| 2 | Accepted lib | `drive-tool` @ `03a8250` `drive_tool/search.py` | accepted | `7a03793c05abf58e9f4558d2388ee892715f9ea5fb346e108b9411d0544230b6` |
| 3 | Pending range candidate | `drive-tool` @ `121faf848b2f33f80721239fc7716adba7a9ba62` `drive_tool/local.py` | pending | `8d382347a4d1118440d364c693624de54883d517376779076c753672818ee2b7` |
| 3 | Pending evidence | `drive-tool` @ `121faf84` `docs/evidence/MODULE-005B.md` | pending | `253c833468f2130d30dd3251e512ff518b9aeed13f5ec5a8bf8dfd296fd6aa43` |
| 4 | Director requirements | `drive-tool` @ `994049485885994fe8653d8b4ec7a25fb578816d` `tasks/d041-service-contract-review.md` | requirements | `b32818115d7c8f96dd515b89eb4c2a1e15e09348882b0f1d9be71898f296a067` |
| 5 | DeepSeek proposal | `drop` @ `0f352c7b1e98168126d115a73e46052767a41572` `drive-tool/module-006/d042-deepseek-service-contract.md` | proposal | `3a314a87fcbda301db105563f0a750687e51e821b01ca30cbfba4574727061cb` |

The D042 file is a **proposal**, not an accepted contract. The D039 Gemini design is historical
and not re-read.

## 1. Exact existing public surface (accepted `03a8250`)

All of the following is read directly from the pinned accepted source. No parameter is invented;
where the brief's prose differs from the source, the source wins and the difference is flagged.

**`storage.py`**
- `FileRef(source_id: str, file_id: str)` — frozen dataclass. `ROOT_ID = "root"`.
- `FileMetadata(ref: FileRef, name: str, parent_id: str | None, kind: str, size_bytes: int | None)`
  — frozen. **No `mtime` field exists**, and neither `list_children` nor `find` performs a per-result
  `stat`; metadata is built from the scan/stat already taken. `parent_id`/`size_bytes` are `None` for
  the synthetic root.
- `ScanBatch(items: tuple[FileMetadata, ...], inspected: int, complete: bool)` — frozen. `items` is
  always a tuple; `0 <= len(items) <= inspected`; `complete=True` only when end-of-directory was
  observed within budget.
- Error hierarchy (all subclass `StorageError`): `ScanFailure(inspected, error)` (preserves the
  original as `.error` and `__cause__`), `ScanUnsupportedError`, `SourceMismatchError`,
  `NotFoundError`, `NotDirectoryError`, `IsDirectoryError`, `EnumerationLimitError(limit)`,
  `AlreadyExistsError`, `ReadOnlyError`. `MAX_SCAN_ENTRIES = 100_000`.
- `StorageAdapter` (runtime-checkable Protocol): `source_id`; `stat(ref) -> FileMetadata`;
  `list_children(parent, *, max_entries=None) -> list[FileMetadata]`; `read_bytes(ref) -> bytes`.

**`local.py`** (`LocalAdapter` is the anchored POSIX adapter)
- `LocalAdapter(source_id, root, *, max_read_bytes=1_048_576, max_list_entries=10_000)`.
  `root` must be an absolute path with no symlink in any component; the constructor walks each
  component from `/` with `O_NOFOLLOW` and holds the resulting **anchored root directory fd**.
  Properties `source_id`, `max_read_bytes`. `PATH_PREFIX = "p/"`; canonical non-root ids are `p/a/b.txt`.
- Methods: `stat(ref)`, `list_children(parent, *, max_entries=None)`, `scan_children(parent, *, max_entries) -> ScanBatch`
  (mandatory budget, `1..MAX_SCAN_ENTRIES`), `read_bytes(ref) -> bytes` (whole file; raises
  `ReadLimitExceededError` when `st_size > max_read_bytes`).
- Errors: `LocalStorageError` (base), `UnsafePathError` (`LocalStorageError, ValueError`),
  `UnsupportedEntryError`, `ReadLimitExceededError`, `AdapterClosedError`, `UnsupportedPlatformError`.
- Lifecycle: `close()` closes the retained root fd and is idempotent; context-manager support;
  `__del__` best-effort. Operations after `close()` raise `AdapterClosedError` (after the
  source-mismatch check). **Close racing an active operation is UNSUPPORTED.**

**`listing.py`**
- `ListingService(adapter).list_page(parent, *, limit=50, offset=0, name_contains=None, max_entries=None) -> ListingPage`.
- `ListingPage(items: tuple[FileMetadata, ...], next_offset: int | None)`. `MIN_LIMIT=1`, `MAX_LIMIT=100`.
  Ordering `(name, source_id, file_id)`; offset windows are **per-call observations, not a snapshot**.

**`search.py`**
- `find(adapter, parent, name_contains, *, max_results=20, max_entries=5000, max_depth=4, case_sensitive=False) -> FindResult`.
  **It is a module function, not `LocalAdapter.find`.** The search key parameter is `name_contains` —
  the D041 prose says `query`, which is **not** a real parameter name and must not be used in the wire schema.
- `FindResult(items: tuple[FileMetadata, ...], truncated: bool, reason: str | None, inspected: int, skipped: tuple[str, ...])`.
  `reason ∈ {"max_results","max_entries","max_depth","skipped",None}`. Exhaustive coverage only when
  `truncated is False and skipped == ()`. No cursor, no continuation. Requires a callable
  `scan_children`, else `ScanUnsupportedError` (no fallback).

**`local_write.py`**
- `LocalWriter(adapter, *, max_write_bytes=10_485_760) -> ...`; properties/method `max_write_bytes`.
- `write_bytes(parent, name, data: bytes, *, overwrite=False) -> FileMetadata`.
  Publish is an atomic no-replace `link` by default; `overwrite=True` uses an atomic `rename` after a
  no-follow target check. Ordering: create temp → write all → `fsync(tmp)` → close → link/rename →
  `fsync(parent)`. **The parent `fsync` happens *after* the name may already exist**, so a failing
  parent-fsync leaves the file published. `data > max_write_bytes` raises `WriteLimitExceededError`.
- `mkdir(parent, name, *, exist_ok=False) -> FileMetadata`. Single component; `exist_ok=True` returns
  metadata for an existing real directory; a symlink occupying the name is never accepted.
- `DEFAULT_MAX_WRITE_BYTES = 10_485_760` (10 MiB) — the service will set `max_write_bytes = 1 MiB`.

**Accepted vs pending read_range.** The accepted `local.py` (`03a8250`) has **no** `read_range` and
**no** `RangeReadResult`; only `read_bytes` exists. The pending candidate (`121faf84`) adds a frozen
`RangeReadResult(data, offset, observed_size, observed_mtime_ns, eof_observed)` and
`read_range(ref, *, offset=0, length=None)`, plus `_validate_range_options`, `_DEFAULT_RANGE_LENGTH=262_144`,
`_RANGE_MAX_BOUND=2**63-1`, and the `os.pread` seam. Per `MODULE-005B.md` it is the builder's own run
with **no independent-acceptance claim**, 7/7 mutations caught on 3.11.2 and 3.12.13, not merged.
**The service range-read path is deferred until an accepted exact source pin exists**; the service must
consume only the accepted API and must not re-implement pread logic.

## 2. Mapping: four service client methods

| Service method | Maps to (accepted) | Notes / exact call |
| -------------- | ------------------ | ------------------ |
| `find` | `search.find(adapter, parent, name_contains, max_results=…, max_entries=…, max_depth=…)` | module function; pass `name_contains` (not `query`). Return `items/inspected/skipped/truncated/reason`. Short replies still carry incomplete coverage. |
| `list` | `ListingService(adapter).list_page(parent, limit=…, offset=…, name_contains=…)` | default limit 20, hard cap 100 (`MAX_LIMIT`). `next_offset=None` means exhausted; windows are not snapshots. |
| `read` | `LocalAdapter.read_bytes(ref)` (accepted) → `read_range(ref, offset, length)` (pending) | whole-file read bounded by `max_read_bytes=1 MiB`; range path **deferred** until the pending pin is accepted. Never invent mtime; `RangeReadResult` is observed-only. |
| `save` | `LocalWriter.write_bytes(parent, name, data, overwrite=False)` + `LocalWriter.mkdir(...)` for missing parents | default no-overwrite (`link`); `max_write_bytes=1 MiB`. Parent creation is `mkdir` per component, grant-contained. |

Read/save carry raw bytes (`application/octet-stream`); find/list are JSON control + JSON results.
`size_bytes` is the only file size signal available — do not synthesise mtime.

## 3. Policy: minimal safe grant anchoring

**Finding (source-confirmed).** The constructor already opens an **anchored root fd at any existing
directory** (`_open_anchored_root` walks each component from `/` with `O_NOFOLLOW`, `fstat`s it, and
requires a directory). All id resolution is relative to that fd. Therefore a **per-grant anchored
adapter is just a second `LocalAdapter` whose `root` is the grant directory**; the service remaps the
grant-relative ids (`p/…`) into its own grant-scoped namespace. **No new resolver is required** — the
anchoring already exists.

**Why the anchor, not a lexical prefix.** The root is a held **descriptor (inode)**, not a path string.
An ancestor rename (or a rename of the grant directory itself) does not change which directory the fd
refers to, so the grant boundary survives rename. A **string prefix is not a security boundary**: it
can be defeated by rename, by `..`/symlink games, and it cannot express "this inode and its descendants".
Nested grants must not leak ancestor/sibling metadata, search results, or closest-name hints — an
anchored adapter for the grant root naturally cannot see above it.

**Recommended minimal choice:** grant-specific anchored adapters with service-side id remapping as the
primary policy; if any grant anchor cannot be provisioned as a real directory at startup, fall back to
**whole-source-root grants only** for the first release. Source-confirmation prerequisites: (a) every
grant anchor is an existing directory with no symlink component at startup; (b) request paths carry
source aliases and canonical ids, never host roots; (c) replacement/detachment of a grant directory
mid-run is an operator external-mutation boundary, not a security promise.

**Where source confirms / contradicts:** confirms the anchored-fd constructor and grant-relative id
space (supports anchored sub-grants without a resolver). Contradicts any claim that a lexical
sub-prefix is sufficient, and gives no evidence for a "closest-name" style hint being safe.

## 4. Consistent small resource budget (6 agents)

Static config; every value is a fixed cap, nothing unbounded.

| Knob | Value | Rationale |
| ---- | ----- | --------- |
| `max_connections` | 64 | hard cap on accepted TCP sockets (incl. ones still framing) |
| `max_workers` | 16 | bounded thread pool; **no unbounded executor queue** |
| `work_queue` | 64 | bounded; overflow → `busy` (429) |
| global active ops | 16 (= workers) | = `max_workers` |
| per-agent active | 4 | 6 agents × 4 = 24 > 16, so the **global cap binds** |
| per-source active | 8 | bounded source slots |
| read cap | 1 MiB | `max_read_bytes=1_048_576` (accepted default) |
| write cap | 1 MiB | `max_write_bytes=1_048_576` (overrides 10 MiB default) |
| request-line | 8 KiB | reject before parse |
| header bytes | 16 KiB | reject before body |
| JSON control body | 64 KiB | find/list |
| binary save body | 1 MiB | raw save |
| response bytes | 1 MiB | read payload / JSON result |
| global buffered request | 32 MiB | **hard cap incl. queued bodies** |
| global buffered response | 32 MiB | hard cap incl. undelivered responses |
| `control_deadline_ms` | 5000 | absolute accept→final-write (control ops) |
| `io_deadline_ms` | 15000 | absolute for read/save incl. body + fs |
| `response_wait_ms` | 2000 | budget to deliver a computed response |
| `shutdown_grace_ms` | 10000 | bounded graceful wait |
| `audit_ring` | 1024 | bounded audit entries |

**Framing.** Require **exactly one** `Content-Length`; reject duplicate `Content-Length`, any
`Transfer-Encoding`, `chunked`, conflicting framing, pipelining and keepalive with `invalid` (400)
**before** reading the body. Respond `Connection: close` and close the socket; no keepalive, no
pipelining. Stdlib parser limits are **explicitly implemented**, not assumed.

**Deadlines.** Absolute **accept-to-final-write** deadlines (`control_deadline_ms`, `io_deadline_ms`),
not socket-inactivity timeouts — inactivity alone lets a one-byte-at-a-time trickle run forever. A
trickle past the absolute deadline is closed. `response_wait_ms` is only the budget to deliver an
already-computed response; it does **not** cancel a filesystem syscall.

**Aggregate-memory arithmetic (estimate, not a measured figure).** Worst case concurrently buffered
request bodies = `min(global_buffered_request, max_connections × binary_body)`; the 32 MiB hard cap
admits at most 32 single-MiB bodies at once, and a request whose body would exceed the cap is rejected
`busy` **before** buffering, so buffered request memory is bounded at **32 MiB** regardless of the
64-connection / 64-queue depth. Responses are bounded at **32 MiB** (16 workers × ≤1 MiB, capped).
**Completed-but-timed-out work counts**: a worker that finished compute but whose response could not be
delivered (`response_wait_ms` exceeded, or client gone) still holds its agent/source/global slot, its
adapter lease, and up to 1 MiB of response **until the thread returns** — those are included in the
16-worker and 32 MiB response arithmetic. Steady-state resident ≈ interpreter baseline + 32 MiB request
+ 32 MiB response + connection/stack overhead, i.e. comfortably under ~150 MiB resident; this is an
engineering estimate to be confirmed by the soak, not a guarantee.

**Saturation honesty.** A saturated source or agent can affect unrelated callers under the finite global
cap; no caller is promised immunity. Over-cap admission returns `busy`; a shutting-down service returns
`unavailable`. Held workers retain **all** quotas and adapter leases until the syscall actually returns.

## 5. Shutdown / uncertain-write semantics (critique of D042)

**D042's paragraph says:** stop accepting; let active workers finish until `shutdown_grace_ms`; "then
process exits"; no descriptor close/reuse; operator fallback kill/restart; in-flight saves after grace
may be uncertain.

**Critique.** "Then process exits" is not achievable as written. Python **non-daemon** threads prevent
interpreter exit: a worker wedged in an **uninterruptible local-filesystem syscall** keeps the process
alive past the grace deadline, and the stdlib cannot cancel a local fs syscall. So the main thread can
stop accepting and *report*, but it cannot promise the process terminates at the deadline. Closing active
descriptors or rebinding them is correctly excluded, and no supervisor framework is warranted for the
first scope.

**Chosen honest minimal lifecycle rule (one rule):** on shutdown, (1) stop accepting new connections and
set a shutting-down flag; (2) **drain the queue** — not-yet-dispatched requests are rejected `unavailable`
(503) with `retry_safe=true`; (3) let already-dispatched workers run; the main thread waits up to
`shutdown_grace_ms` and then emits a **graceful-timeout report** naming which workers finished and which
were still active; (4) the process exits **when all worker threads have actually returned** — the report
does not claim exit at the deadline. **Operator fallback** is an external `kill`/restart (SIGKILL).
Distinguish clearly:

- **Graceful timeout report** — "N workers still active at grace expiry"; any save among them has an
  **uncertain** outcome.
- **Forced termination** — operator SIGKILL; an in-flight save may or may not have published.
- No claim of cancellable kernel I/O; no closing/reusing active descriptors; no descriptor rebind.

(An alternative — daemon threads so the interpreter can exit — is rejected for the first scope because a
mid-syscall daemon thread is killed abruptly at exit, which makes writes *more* uncertain, not less. The
trade-off is stated, not hidden.)

**Uncertain-write semantics (save).** Default no-overwrite. Missing parents may be created in one call,
**only within the grant anchor**; a `mkdir` side effect **persists** on a later failure (no shared-dir
rollback). A post-publish durability error (`fsync(parent)` failure after the name exists) → `unavailable`
(503), `retry_safe=false`, `side_effects.file_may_exist=true`. A lost/timed-out save completion after
dispatch → `timeout` (504), `retry_safe=false`, **no known-not-committed claim**. Durable idempotency is
explicitly **deferred**; verify-before-retry is guidance only and does not protect against a still-active
save racing the verification.

## 6. Pre-implementation acceptance matrix

Test **specifications**, not executed results. "Correctness" rows are pass/fail gates; "benchmark" rows
are hardware-sensitive observations and are **not** correctness gates.

| ID | Area | Measurable assertion | Class |
| -- | ---- | -------------------- | ----- |
| A1 | Auth non-leakage | Requests with absent/invalid/duplicate credentials are rejected (401/403) **before** any adapter call; an injected adapter spy records zero filesystem seams. | Correctness |
| A2 | Policy non-leakage | An agent with no grant on a source/ancestor gets `not_found`/`denied` with **no** ancestor/sibling metadata, search result, or closest-name hint; the response body is byte-identical whether the denied target exists or not. | Correctness |
| A3 | Framing | Duplicate `Content-Length`, `Transfer-Encoding`, `chunked`, conflicting framing, pipelining and keepalive are each rejected `invalid` (400) **before** the body is read; exactly-one-`Content-Length` enforced. | Correctness |
| A4 | Trickle | A request sending header+body one byte at a time past the absolute deadline is closed (`timeout` 504 / `invalid`); the deadline is accept→final-write, not socket-inactivity. | Correctness |
| A5 | Saturation | With a controlled blocked adapter holding all workers, further requests get `busy` (429) or `unavailable` (503); queue never exceeds its cap; no unbounded executor queue; unrelated callers are **not** promised immunity. | Correctness |
| A6 | Retained quotas on timeout | A worker whose `response_wait_ms` expires while an fs syscall is still running keeps its agent/source/global slot and adapter lease until the syscall returns; observed active count does not drop early. | Correctness |
| A7 | Delayed / post-publish save | Parent-fsync failure after publish → `unavailable` (503), `retry_safe=false`, `file_may_exist=true`; lost/timed-out completion → `timeout` (504), `retry_safe=false`, no known-not-committed claim. | Correctness |
| A8 | Missing-parent side effects | A save that creates a missing parent leaves that parent on disk after a later failure (no rollback); parent creation cannot cross the grant anchor (denied/not_found, no host path in the message). | Correctness |
| A9 | Observed EOF (pending) | `eof_observed=true` only from an empty `pread` **inside** the window; an exact-fill window reports `false`; a window past EOF reports empty data + `true`; no final-EOF or snapshot claim. | Correctness (gated on accepted pin) |
| A10 | Redaction | Audit logs, health, and error bodies contain no host roots, tokens, or raw file bytes — only bounded redacted fields; the audit ring stays within its configured size. | Correctness |
| A11 | Drain | On shutdown, new connections are refused and queued requests rejected `unavailable`; dispatched workers finish or are reported still-active at grace; **no** active descriptor closed/reused; process-exit-at-deadline is **not** asserted. | Correctness |
| A12 | Smoke 600 → soak 10000 | The 600-call smoke passes all correctness rows **first**; then a 10000-call soak with fd/temp/RSS stability within predeclared bounds. | Benchmark (stability numbers) |

## 7. Blockers and minimal scope alternatives

1. **read_range not accepted** → the service range path is **deferred**; first release uses accepted
   `read_bytes` (whole file, 1 MiB cap). Minimal alternative: ship read-only-whole-file now, add range
   only after the exact pin is accepted. Do not re-implement pread.
2. **Grant anchors unprovisioned** → if any per-grant anchor is not an existing symlink-free directory at
   startup, restrict to **whole-source-root grants only**. No new resolver is needed either way.
3. **Stdlib HTTP framing** → parser limits must be explicitly implemented; reject keepalive/pipelining/
   chunked to keep framing unambiguous. Confirm exact Python 3.11 `http.server`/`http.client` behaviour
   before coding.
4. **No cancellable syscall** → deadlines are **response budgets**, not syscall deadlines; workers hold
   quotas until the syscall returns. State this in the contract, do not promise cancellation.
5. **Parameter-name trap** → the search key is `name_contains`, **not** `query`. Wire schema must use the
   real name.
6. **Lifecycle** → `close()` racing an active operation is unsupported; the service must open adapters at
   startup and never close one while a worker holds it (close only during drain, after workers return).

## 8. Deferred limitations (truthful)

No MCP, no public remote transport, no Google OAuth, no real roots, no durable jobs/idempotency, no
indexing, no remote browser transport, no snapshot list/find, no syscall cancellation, no lifecycle-close
racing. External mutation, hard links, mounts and operator-provisioned roots remain documented boundaries.
`eof_observed`/`observed_size`/`observed_mtime_ns` are per-call observations, never a coherent version.
No production security guarantee beyond the confirmed design; no D040 acceptance implied.

**TESTS_NOT_RUN.**
