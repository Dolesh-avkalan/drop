# D059 — Bounded HTTP adapter contract (DESIGN ONLY)

**Status:** design only. No implementation, no source/test files, no branches, no merge/deploy, no real roots or tokens, no tests executed. The director owns the final contract and settles the open decisions in §14.

**Task:** connect the *existing, accepted* client wire format to the *pinned* backend operation layer through one new, bounded HTTP adapter. No protocol redesign on either side.

## 0. Pins (retrieved and verified)

| Artefact | Repository @ commit | Path(s) used |
|---|---|---|
| Accepted client (merged, 490 tests, fake-server only) | `Dolesh-avkalan/drive-tool` @ `cbf60867a0ca6e10206d540aed93f40e24b44a5d` | `drive_tool/service_client.py`, `tasks/d047-agent-client.md`, `drive_tool/local.py` (`RangeReadResult`) |
| Backend contract | `Dolesh-avkalan/drive-tool` @ `8eac68b98481b86e7ae164a5835063584c15fdcb` | `tasks/d050-file-service-implementation.md` |
| Backend drop (generated/tested; independent **D058 in progress elsewhere — not implemented or modified here**) | `Dolesh-avkalan/drop` @ `8da43959e93d36649add7422a256b7688d70c84e` | `drive-tool/module-006/d054-file-service-assembly-summary/drive_tool/file_service.py` |
| Module design brief | `Dolesh-avkalan/drive-tool` @ `cbf60867…` | `tasks/MODULE-006-DESIGN.md` |
| Independent-backend brief (context only) | `Dolesh-avkalan/drive-tool` @ `cbf60867…` | `tasks/d058-independent-backend.md` |

Retrieval: public pinned `raw.githubusercontent.com` at the exact commit SHAs (verified HTTP 200, byte counts recorded). The GitHub connector was used for repository discovery; no authenticated write was needed for reads.

**Proposed new module (this design defines it, does not create it):** `drive_tool/http_adapter.py` — the only new production path. It imports the frozen `drive_tool.file_service.LocalFileService` and exposes the frozen client wire contract. The client (`drive_tool/service_client.py`) and the service (`drive_tool/file_service.py`) are **unchanged**.

---

## 1. Topology and ownership

- One process binds one loopback IPv4 listener on `127.0.0.1:<port>` (plain HTTP, no TLS, no public exposure — MODULE-006 §6). Port is chosen at start; ephemeral (`:0`) is allowed for synthetic tests.
- The adapter **owns**: the listening socket, the accept loop, a fixed worker set, per-connection socket deadlines, and the process shutdown sequence.
- The service **owns**: the per-`(agent_id, alias)` `LocalAdapter`/`LocalWriter` pairs, the policy table, leases, and drain. The adapter never touches adapters, roots, or the filesystem directly; it only calls the four `LocalFileService` operations and `close`.
- The adapter holds **no** policy, no token store, no path resolution. `source_id`/`file_id` are opaque wire strings forwarded verbatim (the service owns containment; the client already documents that its `source_id` check is "a convenience, not an authorization boundary").

---

## 2. Endpoint / body / query / header contract (must match the client byte-for-byte in shape)

The client emits exactly four operations. The adapter accepts exactly these and nothing else; any other path or method → `invalid` (§3).

### 2.1 JSON operations — `POST /v1/list`, `POST /v1/find`, `POST /v1/read`

- Request headers (exactly these are sent by the client): `Content-Type: application/json`, `Content-Length: <exact decimal byte length>`, `Authorization: Bearer <token>`, `Connection: close`, plus `Host` added by `http.client`.
- Body = one UTF-8 JSON object (`ensure_ascii=False`, compact separators) with these exact keys:
  - `/v1/list` → `{source_id, file_id, limit, offset}` and `name_contains` **only when not None**.
  - `/v1/find` → `{source_id, file_id, name_contains, limit, max_entries, max_depth}`.
  - `/v1/read` → `{source_id, file_id, offset, length}`.
- `token` is **not** in the body; it is taken from the `Authorization` header only.
- Adapter maps to the service call, passing the extracted token as the first positional argument:
  - `LocalFileService.list(token, source_id, file_id, limit=…, offset=…, name_contains=…)`
  - `LocalFileService.find(token, source_id, file_id, name_contains=…, limit=…, max_entries=…, max_depth=…)`
  - `LocalFileService.read(token, source_id, file_id, offset=…, length=…)`
- The adapter must **not** invent defaults the client did not send beyond what the service signature already defaults. Missing required key (`source_id`, `file_id`, `name_contains` for find, `offset`/`length` for read) → `invalid`.

### 2.2 Save — `POST /v1/save?<query>` with a raw body

- Query (URL-encoded by the client via `urllib.parse.urlencode`): `source_id`, `file_id`, `overwrite=true|false`, `create_parents=true|false`.
- Request headers: `Content-Type: application/octet-stream`, `Content-Length` exact, `Authorization: Bearer <token>`, `Connection: close`.
- Body = raw file bytes (never JSON, never base64).
- Adapter maps: `LocalFileService.save(token, source_id, file_id, data, overwrite=<bool>, create_parents=<bool>)`, where `overwrite`/`create_parents` are parsed from the query strings `"true"`/`"false"` **exactly** (any other token → `invalid`).
- **No credentials in the query** — the adapter rejects `token`/`authorization`/`bearer` appearing as query keys (they never should; treat as `invalid`).

---

## 3. Response contract

### 3.1 Success, JSON operations (`list`, `find`, `save`)

- Status `200`, `Content-Type: application/json`, `Content-Length` = exact JSON byte length.
- Body: `{"ok": true, "result": {…}}` where `result` is the service return value **unchanged**:
  - `list` → `{"items": [metadata…], "next_offset": int|null}`
  - `find` → `{"items": [metadata…], "truncated": bool, "reason": …, "inspected": int, "skipped": [str…]}`
  - `save` → `{"ref": {"source_id": …, "file_id": …}, "bytes_written": int, "parents_may_have_been_created": bool}`
- `metadata` shape (from `_serialize_metadata`): `{"ref": {"source_id", "file_id"}, "name", "parent_id", "kind", "size_bytes"}`.

### 3.2 Success, `read`

- Status `200`, `Content-Type: application/octet-stream` (the client compares the media type before `;` case-insensitively — the adapter sends the bare type).
- `Content-Length` = `len(result.data)`.
- Exactly **one** instance of each observation header, decimal, from `RangeReadResult` fields (verified names in `drive_tool/local.py`):
  - `X-Drive-Offset` ← `result.offset` (must equal the requested `offset`; the adapter serialises what the service returned — it does not re-derive).
  - `X-Drive-Observed-Size` ← `result.observed_size`
  - `X-Drive-Observed-Mtime-Ns` ← `result.observed_mtime_ns`
  - `X-Drive-EOF-Observed` ← `result.eof_observed` as `true`/`false` (lowercase)
- The adapter must **not** synthesise EOF, must **not** enforce `observed_size >= offset + len(data)`, and must **not** add a second copy of any of these headers. It serialises the adapter's observation exactly; the client's own short-window/exact-fill/EOF rules then hold.

### 3.3 Error envelope (any non-200)

- Body: `{"ok": false, "error": {"code": <code>, "outcome_uncertain": <bool>, "retry_safe": <bool>}}`, `Content-Type: application/json`, `Content-Length` exact.
- `code` is one of the eight the client recognises and the service defines: `invalid`, `denied`, `not_found`, `exists`, `too_large`, `busy`, `unavailable`, `timeout`.
- `outcome_uncertain` / `retry_safe` are copied verbatim from the `ServiceError` fields. If the adapter raises the error itself (framing, admission), it sets them per §5/§7.
- **Proposed status mapping** (the client ignores the exact status and only needs non-200 + a valid envelope; the mapping is a required choice, §12):

| code | HTTP status |
|---|---|
| invalid | 400 |
| denied | 403 |
| not_found | 404 |
| exists | 409 |
| too_large | 413 |
| busy | 503 |
| unavailable | 503 |
| timeout | 504 |

- The adapter never sends `1xx`, `3xx`, or a redirect (the client does not follow redirects; a 3xx would be parsed as an error body and become `unavailable`). The adapter never leaks server exception text, token, root, or body bytes into the envelope or into any log (§11).

---

## 4. Strict framing, header duplicates, Content-Length, Transfer-Encoding

The adapter is a **bounded, fail-closed** HTTP/1.1 request parser. It never trusts the client and never reads unbounded input.

1. **Request line** ≤ 8192 bytes; only `POST` accepted; target must be one of the four exact paths (or `/v1/save` with query). Overlong line, wrong method, unknown path → `invalid`.
2. **Header block** ≤ 16384 bytes total and ≤ 64 header lines. Exceeding either bound → `invalid` (connection closed).
3. **`Content-Length`**: required on every request, exactly **one** header, value a non-negative decimal with no sign/space/`+`, and it must be ≤ the operation's body cap (§6). Duplicate `Content-Length`, missing `Content-Length`, non-decimal value, or a declared length above the cap → fail closed (`invalid`, or `too_large` when above cap). After reading, the actual body byte count must equal the declared length; a short read (client vanished) → connection dropped with **no** service call (§9).
4. **`Transfer-Encoding`**: **rejected** on any request (`invalid`). The client always sends `Content-Length`; chunked request bodies are unsupported by design, so the adapter never parses chunked framing. (Response side is always `Content-Length`-framed.)
5. **`Authorization`**: exactly one header, exact form `Bearer <token>` (single ASCII space). Zero or ≥2 occurrences → `denied` (or `invalid`; see §14-D2). The token bytes are passed unchanged to the service; the adapter never validates token content itself.
6. **`Content-Type`**: validated per operation — `application/json` for list/find/read, `application/octet-stream` for save. Missing or mismatched → `invalid` (fail closed; §14-D3 for leniency).
7. **`Connection`**: the client always sends `close`. The adapter honours one request per connection and always closes after the response; it never implements keep-alive or pipelining (an inbound `keep-alive` is ignored, the connection still closes).
8. **`Expect: 100-continue`**: the client never sends it; if present, the adapter does not emit a `100 Continue` and treats the request per normal framing (or rejects as `invalid` — §14-D3).
9. Duplicate/ambiguous copies of any singleton header the adapter depends on (`Content-Length`, `Authorization`, `Content-Type`, `Connection`) → fail closed.
10. The adapter writes a response only after it has a complete, validated request; it never streams a partial success envelope.

---

## 5. Auth-before-operation IO

- The **service** already enforces the ordering the contract requires: every operation calls `_authenticate_and_authorize(token, source_id, op)` first, then parses file id/options, then acquires the lease and does filesystem work. The adapter preserves this by **delegating once** and doing no filesystem work of its own.
- Adapter-side ordering per connection: parse request line + headers → cheap framing checks (§4, incl. exactly-one `Authorization`) → read the bounded body → **one** `LocalFileService` call. Reading the request body from the socket is socket IO, not a per-request filesystem call, so it does not violate the ordering rule.
- No closest-name hints, no metadata probing, no `source_id` existence checks happen in the adapter. Denied tokens and unauthorized aliases surface as `denied` identically regardless of whether a path exists (the service guarantees this; the adapter must not add a path-dependent pre-check).
- Open assumption: `LocalFileService` exposes **no** public auth-only hook, so the adapter cannot authenticate the token *before* reading the body (see §13-A2). Because bodies are bounded (§6), this is not a DoS vector. If the service later exposes an auth-only probe, the adapter may authenticate earlier.

---

## 6. Bounds (request, response, work)

| Bound | Value | Source / rationale |
|---|---|---|
| Max JSON control/success/error body (request and response) | 65536 bytes | client `_MAX_JSON_BODY`; adapter enforces the same cap on inbound JSON and never emits a larger envelope |
| Max save request body | 1048576 bytes | client `_MAX_SAVE_BYTES` = service `SERVICE_MAX_READ_BYTES`; a fixed wire cap the adapter can enforce **before** it knows the grant (grant caps are enforced later by the service) |
| Max read response body | requested `length` ≤ 1048576 | client `_MAX_READ_LENGTH`; the adapter writes at most `len(result.data)` |
| Max request line | 8192 bytes | adapter choice (§12) |
| Max header block | 16384 bytes / 64 lines | adapter choice (§12) |
| Read window / offset+length | `length` 1..1048576, `offset+length ≤ 2**63-1` | client + service; service enforces grant cap → `too_large` |
| find budgets | `max_entries` 1..2000, `max_depth` 0..16 | service `SERVICE_MAX_FIND_ENTRIES`, `SERVICE_MAX_DEPTH` |
| list | `limit` 1..100, `offset ≥ 0` | service `SERVICE_MAX_LIMIT` |
| name_contains | ≤ 256 code points | client + service |
| save parent depth | ≤ 16 | service `SERVICE_MAX_DEPTH` |
| Configured agents / grants | ≤ 6 / ≤ 32 | service `MAX_CONFIGURED_AGENTS`, `MAX_CONFIGURED_GRANTS` |

The adapter enforces the wire caps (body size, framing) and otherwise lets the service enforce the semantic caps, translating the resulting `ServiceError` code. It never widens a cap the service sets.

---

## 7. Concurrency and admission (six, bounded, no unbounded threading)

- **Fixed worker set of 6**, created once at startup. The accept loop never spawns a thread per connection; there is no unbounded thread growth.
- **In-flight operation cap = 6**, matching `MAX_CONFIGURED_AGENTS = 6` and the design's "about six agents". A semaphore/counter of 6 gates *dispatched operations* (one per accepted, validated request).
- **Bounded admission** (required choice — §14-D1): when 6 operations are in flight, the 7th connection is either
  - **(a)** answered immediately with `503`/`busy` (`outcome_uncertain=false`, `retry_safe=true`), or
  - **(b)** held in a small bounded queue (≤ 6) and dispatched when a worker frees, with connections beyond the queue reset.
  Either way the listener `backlog` is bounded (proposed 16) and no unbounded buffering occurs. The design recommends **(a)** for honest, bounded behaviour and predictable client outcomes.
- Concurrency is over *retained* service adapters (the service supports concurrent operations on retained adapters and counts active leases); the adapter adds no second locking layer over filesystem state.
- The adapter must not promise cancellation of a blocked filesystem syscall. If a worker is stuck in a service call, that worker is unavailable; with 6 workers a sustained stall saturates admission and new requests get `busy`. This is the smallest honest isolation strategy (MODULE-006 §2).

---

## 8. Socket inactivity budget vs. no filesystem deadline

- The adapter sets a **per-connection socket inactivity budget** (proposed 5.0 s, mirroring the client default) covering: reading the request line, headers, and body, and writing the response. On inactivity expiry it closes the connection. This bounds **slow-header and slow-body clients** explicitly (MODULE-006 §2).
- This budget is an **inactivity/operation budget, not a hard wall-clock deadline**. Once the adapter hands a request to the service, the **filesystem operation has no hard deadline**: the socket timeout does not cancel an in-flight syscall, and the worker waits for the service call to return. The adapter must document — in code and in any operator note — that it cannot promise hard cancellation of a blocked filesystem operation, exactly as the client documents for its own socket budget.
- `timeout` here is **not** passed into the service (the service has no per-call timeout parameter); the service-level drain budget is separate (§10).

---

## 9. Connection-close, no retries, safe uncertain save on disconnect

- **Connection-close:** one request per connection; the adapter always closes the socket after writing the response (or after any failure). No keep-alive, no pipelining, no connection reuse.
- **No retries:** the adapter never retries an operation, and in particular **never** retries or re-executes a `save`. There is no request-id idempotency in this layer (explicitly deferred per MODULE-006 §4); the adapter must not dedupe or replay.
- **Save uncertainty on disconnect — the required behaviour:**
  1. The adapter reads the **complete** save body before calling the service. If the client disconnects with an incomplete body, the adapter makes **no** service call → no filesystem side effect. (Client sees a transport failure → maps to `outcome_uncertain=true, retry_safe=false` for a write; correct and safe.)
  2. Once the service call is dispatched, the adapter **never** attempts to undo it. If the save returns success but the client disconnects before/while the response is written, the effect **stands**; the adapter does not roll back parents, does not delete, and does not re-run.
  3. If the service raises while write work is in flight, the `ServiceError` already carries `outcome_uncertain=true, retry_safe=false`; the adapter copies these into the envelope. If the connection is already gone, no envelope can be delivered and the client's conservative transport mapping (`outcome_uncertain=true, retry_safe=false`) is the correct outcome.
  4. The adapter never claims a save was "known not committed" and never advertises verify-then-retry as race-safe.
- Read-only transport failures keep the client's `outcome_uncertain=false, retry_safe=true` mapping; the adapter does not change read semantics.

---

## 10. Startup / shutdown / drain ownership

- **Startup:** the adapter constructs `LocalFileService(policies)` first. If it raises (oversize config, a root that fails the adapter's no-follow constructor), startup aborts with the original exception; the service already rolls back any adapters it opened. The adapter then binds the loopback listener; if binding fails, it closes the service and aborts. No configured root is ever created and there is no fallback to a broader root.
- **Shutdown sequence (owned by the adapter):**
  1. Stop accepting: close the listening socket so no new connections arrive.
  2. Let in-flight workers finish their current request (bounded by the drain budget), then signal workers to stop.
  3. Call `LocalFileService.close(timeout=drain_budget)` (proposed 5.0 s). If it returns `False`, some operations had not drained: the adapter **does not** force-close active descriptors; it reports "not fully drained" and leaves resources to a later `close` (the service supports a later close finishing the job). If it returns `True`, all adapters were closed exactly once.
  4. Join worker threads with a bounded wait. The adapter makes **no** promise of bounded process termination — non-daemon worker threads blocked in a filesystem syscall can delay exit, and the adapter says so rather than pretending otherwise.
- **Ownership split:** the adapter owns listener + workers + socket deadlines; the service owns adapters/writers + leases + drain. There is no `__del__`-driven forced closure of active operations.

---

## 11. Redaction

- The error envelope carries only the fixed `code` and the two booleans. It never carries remote/OS exception text, the bearer token, any root, or file bytes.
- Adapter logs (if any) are redacted: no token, no root, no body. The service already suppresses `__cause__`/`__context__` on `ServiceError`; the adapter raises its own errors `from None` and does not attach the raw exception.
- If a client echoes a token/root in a malformed request, the adapter's response still contains none of it.

---

## 12. Required choices (the adapter MUST fix these; values are the proposal)

- R1. New module name/path: `drive_tool/http_adapter.py` (single new production file).
- R2. Listener: `127.0.0.1` only, plain HTTP, ephemeral-or-fixed port; no TLS/proxy/redirect.
- R3. Exact path set: `/v1/list`, `/v1/find`, `/v1/read`, `/v1/save`; all `POST`; everything else `invalid`.
- R4. Framing bounds: request line ≤ 8192 B, header block ≤ 16384 B / 64 lines, exactly-one `Content-Length` (≤ operation cap), `Transfer-Encoding` rejected, actual length must equal declared.
- R5. Singleton headers: exactly one `Authorization` (`Bearer <token>`), one `Content-Type` (per-op), one `Connection` (`close` honoured).
- R6. Concurrency: fixed 6 workers, in-flight cap 6, bounded listener backlog, no per-connection thread creation.
- R7. Admission policy on saturation: §14-D1 (proposed: immediate `503 busy`).
- R8. Socket inactivity budget (proposed 5.0 s) for request read and response write; no hard FS deadline; documented.
- R9. Status mapping (§3.3 table) and the exact error envelope.
- R10. Drain budget passed to `LocalFileService.close(timeout=…)` (proposed 5.0 s); `False` → not-drained reported, no force-close.
- R11. No retries, no request-id idempotency, save never re-executed; disconnect handling per §9.
- R12. Redaction per §11.

## 13. Unresolved backend API assumptions (must be confirmed before implementation)

- A1. **`RangeReadResult` field names** — *resolved and verified*: `data, offset, observed_size, observed_mtime_ns, eof_observed` (`drive_tool/local.py` @ `cbf60867…`), identical to the client `ReadReply`. The adapter maps these attributes to the four observation headers. *(Retained here because it is the one cross-artefact coupling that must not drift; D058 must keep these names.)*
- A2. **No public auth-only hook** on `LocalFileService`: the adapter cannot authenticate before reading the body. Assumed acceptable because bodies are bounded. Confirm, or expose an auth-only probe later.
- A3. **`busy` is not raised by the current service implementation** (only `unavailable` during drain). The adapter synthesises `busy` for admission rejection (§7). Confirm the client/ops accept an adapter-sourced `busy`.
- A4. **Token type/format into `authenticate`**: the drop shows `authenticate(token)` with no explicit type/format contract beyond `str`. The adapter passes the raw bearer string unchanged (client tokens are 32..256 visible ASCII). Confirm the policy table's expected input.
- A5. **`find.reason`** may be `None`/free-form; the adapter forwards it as-is inside the result object. Confirm no serialisation constraint.
- A6. **`list.next_offset` may be `None`**; the adapter emits JSON `null`. Confirm.
- A7. **`save` ref shape**: the service returns `{"ref": {"source_id", "file_id"}}` with `file_id` in canonical `p/…` form (or `root`). The adapter forwards it unchanged. Confirm the client expects canonical ids back (it does not re-validate them).
- A8. **`ServiceError.outcome_uncertain`/`retry_safe`** are already set by the service per code and per write-in-flight; the adapter copies them verbatim and never overrides them. Confirm.
- A9. **Service concurrency semantics**: the service supports concurrent operations on retained adapters and counts active leases under a condition lock; `close(timeout)` returns `False` when not drained. The adapter's 6-worker/6-in-flight model relies on this. Confirm no additional serialisation is required.
- A10. **Grant caps vs wire caps**: the adapter's fixed save-body cap (1 MiB) may exceed a grant's `max_write_bytes`; the service then returns `too_large`. Confirm the two-stage cap is intended.

---

## 14. Open decisions for the director

- **D1. Admission on saturation (7th concurrent request):** (a) immediate `503 busy` *(recommended — bounded, honest, predictable)*, or (b) hold in a bounded ≤6 queue. Also confirm listener `backlog` (proposed 16).
- **D2. Missing/duplicate `Authorization`:** map to `denied` *(auth boundary)* or `invalid` *(framing)*? The client treats both identically; pick the intended semantics.
- **D3. Content-Type / `Expect` strictness:** fail closed on missing/mismatched `Content-Type` and reject `Expect: 100-continue` *(recommended)*, or be lenient since the client always sends correct headers?
- **D4. Socket inactivity budget value:** 5.0 s (mirror the client default) or another value; and whether it is operator-configurable.
- **D5. Drain budget value and shutdown exit behaviour:** 5.0 s (proposed); and whether the adapter should exit non-zero when `close` returns `False`.
- **D6. Exact numeric framing bounds** (8192 B request line, 16384 B/64-line header block) — confirm or tighten.
- **D7. Module name** `drive_tool/http_adapter.py` and the single-new-file scope.
- **D8. Whether the adapter is in scope for MODULE-006 acceptance now, or staged after the REST core** (MODULE-006 §6 keeps public transport/real-root config as a separate reviewed step; this design is loopback-only and synthetic).
- **D9. Confirm A2–A10** with the backend owner (D058) before implementation starts.

---

## 15. Synthetic test and soak plan (plan only — not executed)

All tests are synthetic: tiny POSIX roots, fake/synthetic policies, ephemeral loopback port, the **real accepted `DriveClient`** as one driver and **raw sockets** as another. No real roots, tokens, or external service.

### 15.1 Integrated conformance tests (planned)
- **Wire conformance:** the real `DriveClient` drives all four ops end-to-end against the adapter; assert exact result objects, save query round-trip, and exactly-one observation headers with correct values from a synthetic `RangeReadResult`.
- **Framing/robustness (raw sockets):** missing/duplicate `Content-Length`, non-decimal `Content-Length`, declared-length vs actual mismatch, `Transfer-Encoding: chunked` present, oversized request line, oversized header block, duplicate `Authorization`, wrong `Content-Type`, slow-header, slow-body (inactivity budget fires), `Expect: 100-continue`.
- **Auth/authorization ordering:** denied token and unauthorized alias → `denied` before any FS call (instrument with a probe counter proving **zero** adapter/service filesystem calls); two agents, same alias, different roots → no cross-root leakage.
- **Bounds:** JSON body > 65536 → rejected before dispatch; save body > 1 MiB → rejected before read; read `length` > grant cap → `too_large`; `limit`/`max_entries`/`max_depth`/`offset+length` out of range → `invalid`.
- **Read semantics:** exact-fill window → `eof_observed=false`; short window → `true`; stale `observed_size` under growth tolerated; offset mismatch rejected.
- **Save semantics:** no-overwrite collision → `exists`; missing parents created in one call; fault-injected post-lease storage failure → `outcome_uncertain=true, retry_safe=false`; client disconnect **after** save applied → effect stands (verified on disk), client observes a transport failure; client disconnect **before** full body → no side effect.
- **Concurrency/admission:** saturate 6 in-flight, assert the 7th behaves per D1; assert no thread count growth beyond the fixed pool; assert FD count stable across the run.
- **Lifecycle:** startup rollback when a later root is invalid; shutdown with an active operation → `close` returns `False` and active descriptor stays open; idempotent close (no double-close); operations after drain starts → `unavailable`; listener closed first.
- **Redaction:** malformed request that echoes a token/root yields an envelope and logs containing neither.

### 15.2 600-call smoke (planned)
- One agent, mixed list/find/read/save, sequential plus small bursts up to 6. Assert: all outcomes as expected; FD count (`/proc/self/fd`) returns to baseline; no temp-file residue; RSS bounded; thread count constant; clean drain.

### 15.3 10000-call six-agent soak (planned, gated on the smoke passing)
- 6 agents × distinct aliases/roots, ~1667 calls each, mixed operations, sustained concurrency up to 6, **bounded fixtures** (small fixed corpus, reused files, no unbounded growth of inputs). Checks: FD count stable, no temp/leak growth, thread count constant at the fixed pool, RSS bounded, all errors are recognised codes, drain completes `True` at the end. Failure of the smoke blocks the soak (MODULE-006 §7: define bounds before testing, don't move them to fit a result).

### 15.4 Resource checks (all stages)
- `len(os.listdir('/proc/self/fd'))` before/after; `threading.active_count()`; temp-dir listing; `resource.getrusage` RSS; assert no monotonic growth across the soak.

---

## 16. Non-goals / explicit deferrals

- No TLS, no public binding, no proxy, no redirects, no keep-alive/pipelining.
- No real roots or tokens; no credential/config loader; no deployment.
- No request-id idempotency or durable replay (deferred per MODULE-006 §4).
- No hard filesystem deadline or syscall cancellation.
- No change to `drive_tool/service_client.py` or `drive_tool/file_service.py`; no second path resolver; no policy logic in the adapter.
- No MCP wrapper (a thin wrapper is a later step after REST acceptance, MODULE-006 §6).
