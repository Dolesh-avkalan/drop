# d074 (gemini)

- status: done
- chat: https://gemini.google.com/app/0b75b07bd134b2f2
- model: 4 argon (thinking: high)
- finished: 2026-10-15T22:33:03Z

## Question

Gemini, independent exact-source HTTP security review D074. Scope head d59bef9e productionblob02576d59, adopted D061 with director overrides supplied. Actual execution D073 runs separately. Concrete defects/counterexamples and narrow correction boundaries, ACCEPT/CHANGES REQUIRED, honest TESTS_NOT_RUN. No implementation or new features/deployment. Complete source/contract inline fallback.

(input files: Dolesh-avkalan/drive-tool:tasks/d074-gemini-http-security.txt@4ab631bde1bfc5ece1a2acf7c4d47764a67b0957)

## Answer

Verdict: CHANGES REQUIRED
Execution Status: TESTS_NOT_RUN (static exact-source security and contract review of drive_tool/http_adapter.py at head d59bef9e343816c6d266cfbffa6b4c4d8200e3c4, blob 02576d59d555afc7afde89fd8e2e63a1c1c43e24, against adopted D061 contract and D064 director overrides; baseline 506 does not cover http_adapter.py and D073 execution runs separately).

## 1. Proven Defects & Concrete Counterexamples
### Defect 1: Framing Bounds & Bare-\n Checks in _read_request Stall Until 504 timeout (or Close Silently on EOF) When \r\n\r\n Is Absent

- Location: DriveHTTPAdapter._read_request (drive_tool/http_adapter.py, lines 539–568).

- Violation: Contract §3.2.1, §3.3.1, §9.1.2.

- Mechanism: Phase A loops on idx = buf.find(b"\r\n\r\n") and only checks if len(buf) > MAX_REQUEST_LINE_BYTES + MAX_HEADER_BLOCK_BYTES: (24,576 bytes) inside the read loop. All checks for first_crlf + 2 > MAX_REQUEST_LINE_BYTES (8,192 B), header_end - (first_crlf + 2) > MAX_HEADER_BLOCK_BYTES (16,384 B), > MAX_HEADER_COUNT (64), bare \n without \r, and invalid request-line bytes are deferred until after \r\n\r\n is present in buf. Furthermore, if len(buf) > 24576 is checked before conn.recv rather than immediately after buf.extend(chunk).

- Concrete Counterexamples:

1. Overlong request line without \r\n\r\n: A raw socket sends b"POST /" + b"a" * 8200 + b" HTTP/1.1\r\n" (or b"A" * 8193 with no \r\n; 8,193 B $\le$ 24,576 B) and waits for the 400 invalid response. Because \r\n\r\n is absent and len(buf) <= 24576, _read_request blocks in conn.recv() until self._socket_timeout elapses and responds with 504 Gateway Timeout (code="timeout", retry_safe=True) instead of 400 Bad Request (code="invalid", retry_safe=False). If the client half-closes (shutdown(socket.SHUT_WR)), conn.recv() returns b"", raising _DisconnectSignal, and the worker closes the socket with 0 bytes emitted instead of 400 invalid.

2. Overlong header block without \r\n\r\n: A raw socket sends b"POST /v1/list HTTP/1.1\r\nX-Pad: " + b"a" * 16384 + b"\r\n" (24 B request line + 16,393 B headers = 16,417 B $\le$ 24,576 B) without the final \r\n and waits (or half-closes). The worker emits 504 timeout (or 0 bytes on EOF) instead of 400 invalid.

3. Bare \n line terminators without \r\n\r\n: A raw socket sends b"POST /v1/list HTTP/1.1\nHost: 127.0.0.1\n\n" (or terminates the header block with \r\n\n). Because buf.find(b"\r\n\r\n") never matches, the worker blocks until socket_timeout and returns 504 timeout (or 0 bytes on SHUT_WR) instead of 400 invalid.

### Defect 2: _check_headers Step 5 Raises 413 too_large Before Step 6 (Content-Type) and Step 7 (Authorization)

- Location: DriveHTTPAdapter._check_headers (drive_tool/http_adapter.py, lines 633–676, specifically lines 644–645).

- Violation: Contract §3.4 (deterministic pre-body header check order: Step 5 Content-Length syntax $\rightarrow$ Step 6 Content-Type $\rightarrow$ Step 7 Authorization $\rightarrow$ Step 8 Wire Payload Size Gate) and §9.1.3.

- Mechanism: Line 644 evaluates if len(cl_raw) > _MAX_CONTENT_LENGTH_DIGITS: raise _ReqErrorSignal(413, "too_large", False, False) inside Step 5, prior to validating Content-Type (Step 6) and lexical Authorization (Step 7). It also counts raw digit bytes without normalizing leading zeros.

- Concrete Counterexamples:

1. Unauthenticated huge Content-Length: Client sends POST /v1/list HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 99999999999\r\nContent-Type: application/json\r\n\r\n with no Authorization header (or Authorization: Bearer short). The adapter returns 413 too_large instead of 403 denied.

2. Invalid Content-Type with huge Content-Length: Client sends valid Authorization, Content-Type: text/plain, and Content-Length: 99999999999. The adapter returns 413 too_large instead of 400 invalid.

3. Leading zeros in Content-Length: Client sends valid headers with Content-Length: 00000000002 (11 digits, numeric value 2) and body {}. The adapter rejects with 413 too_large.

### Defect 3: Trailing-Bytes Check Inside _read_body Is Unreachable Dead Code

- Location: DriveHTTPAdapter._read_body (drive_tool/http_adapter.py, lines 680–706, specifically lines 696 and 704).

- Violation: Contract §3.5.2.1 ("If the buffered recv() that completed the header block or body read already contains > content_length bytes beyond \r\n\r\n, reject immediately with 400 invalid ... without calling LocalFileService") and §9.1.2.

- Mechanism: When len(initial) < content_length, line 696 reads chunk = conn.recv(min(_RECV_CHUNK, need)) where need = content_length - len(body). Because the recv() buffer size is capped at need, len(chunk) can never exceed need, so len(body) can never exceed content_length. Line 704 (if len(body) > content_length: raise _ReqErrorSignal(400, "invalid", False, False)) is unreachable dead code.

- Concrete Counterexample:

- A client sends two back-to-back requests in a single sendall(req1 + req2) where req1 has Content-Length: 5000 (so header + req1 body exceeds _RECV_CHUNK = 4096), or sends req1 headers first followed by sendall(req1_body + req2). Phase A's recv(4096) consumes headers plus part of req1's body; _read_body then calls conn.recv(min(4096, need)) which reads only need bytes and leaves req2 sitting in SO_RCVBUF. Instead of rejecting with 400 invalid before calling LocalFileService, the worker dispatches req1 to LocalFileService and returns 200 OK.

### Defect 4: Startup Worker-Slot Registration Race in __init__ and Repeat/Concurrent close() Races

- Location: DriveHTTPAdapter.__init__ (drive_tool/http_adapter.py, lines 284, 300–318) and DriveHTTPAdapter.close (lines 380–430).

- Violation: Contract §6.1.2 (6-slot admission before 503 busy), §7.2 (idempotent subsequent/concurrent close() calls and immediate drain), and D064 override (concurrent close / lifecycle).

- Mechanism & Counterexamples:

1. Startup false 503 busy race (__init__ lines 284, 315–317): self._idle_slots is initialized to [] and self._accept_thread.start() runs before worker.start(). Slots are only added to self._idle_slots when each worker thread is scheduled by the OS and enters _worker_loop (line 480). If 1–6 connections arrive immediately after DriveHTTPAdapter(...) returns before all 6 workers reach _pool_cond.wait(), _accept_loop sees self._idle_slots empty or incomplete and falsely rejects requests with 503 busy while fewer than 6 operations are in flight.

2. Repeat/concurrent close() wake-connect on closed port (close lines 392–401): When close(timeout=0.1) returns False because a worker is still in flight (Contract §9.1.6), self._listener has already been closed, releasing self._port. On the subsequent close() call (or a concurrent close() call from a second thread), self._closed is still False, so close() calls self._wake_listener() again—opening a loopback connection to (HOST, self._port) after the adapter's listener was already closed (potentially hitting another socket that bound the released ephemeral port).

3. Pending slot.conn handoff not closed in close() (close lines 392–394 vs _rollback_startup lines 333–340): Unlike _rollback_startup(), close() does not close/clear slot.conn for connections already handed off by _accept_loop to a worker thread that has not yet woken from _pool_cond.wait(). That worker wakes up, sees slot.conn is not None, and enters _serve(conn) after close() started, blocking up to socket_timeout if the peer is idle.

## 2. Verified Non-Defective Surfaces

- Public API, Constants & Constructor Rollback (§1–§2): __all__, constants, policies/service mutual exclusion, LocalFileService type validation, port/socket_timeout validation, and _rollback_startup() (including self._service.close(timeout=5.0) on injected or owned services) match D061 and D064 overrides.

- Auth-First Public Delegation & Zero-FS-IO (§4): _call_list, _call_find, _call_read, and _call_save strictly avoid private PolicyTable access, extract candidate_source_id only when syntactically unambiguous, and delegate invalid payloads with file_id=None so LocalFileService._authenticate_and_authorize always runs before _parse_canonical_parts(None) halts with invalid prior to _acquire_binding_lease.

- Response Validation, Read/EOF Semantics & Error Matrix (§5): _send_json_response enforces the 64 KiB outbound cap and sets outcome_uncertain=True, retry_safe=False on save vs outcome_uncertain=False on list/find. _send_read_response validates RangeReadResult field types (type(x) is ..., rejecting bool for int fields) and the 1 MiB cap before emitting headers. ServiceError flags are copied verbatim.

- Busy Budget, Post-Response Teardown & Thread Survival (§6): _busy_reject enforces a single 50 ms monotonic deadline and 16 KiB total read budget without looping on 1 MiB bodies. _finalize_connection enforces a 50 ms / 64 KiB post-SHUT_WR drain. _worker_loop catches BaseException around _serve(conn) so malformed inputs cannot kill workers.

- Shared close() Deadline & Redaction (§7–§8): close() computes one deadline = time.monotonic() + timeout_f, invokes self._service.close(timeout=remaining) before joining threads, adds zero extra grace time, and preserves live backend descriptors on incomplete drain. Error envelopes and __repr__ redact all sensitive state.

## 3. Minimal Scoped Fixes Required for DeepSeek (drive_tool/http_adapter.py Only)

1. Fix Defect 1 in _read_request (lines 539–568):

- Immediately after buf.extend(chunk) inside Phase A:

- Check idx = buf.find(b"\r\n\r\n"). If idx >= 0, break and validate buf[:idx + 4].

- While idx < 0 (no \r\n\r\n yet):

- Reject any bare \n (\n at index 0 or not preceded by \r) or bare \r (any \r in buf[:-1] not followed by \n) with _ReqErrorSignal(400, "invalid", False, False).

- Let first_crlf = buf.find(b"\r\n").

- If first_crlf < 0: scan buf[:-1] if buf.endswith(b"\r") else buf for bytes outside 0x20..0x7E, and if len(buf) - (1 if buf.endswith(b"\r") else 0) > MAX_REQUEST_LINE_BYTES - 2, raise _ReqErrorSignal(400, "invalid", False, False).

- If first_crlf >= 0: if first_crlf + 2 > MAX_REQUEST_LINE_BYTES, raise _ReqErrorSignal(400, "invalid", False, False); validate request line/target via _parse_request_line and _parse_target; if len(buf) - (first_crlf + 2) > MAX_HEADER_BLOCK_BYTES, raise _ReqErrorSignal(400, "invalid", False, False).

- If not chunk (EOF before \r\n\r\n) after a non-empty buffer that already has first_crlf >= 0 with invalid completed header lines, or if first_crlf < 0 and buffer is clean, keep _DisconnectSignal() for clean early disconnect.

2. Fix Defect 2 in _check_headers (lines 644–645):

- In Step 5, normalize leading zeros via cl_norm = cl_raw.lstrip(b"0") or b"0". If len(cl_norm) > _MAX_CONTENT_LENGTH_DIGITS, set content_length = MAX_SAVE_BODY_BYTES + 1 instead of raising 413 early; otherwise content_length = int(cl_norm). Let Step 8 raise 413 too_large after Step 6 (Content-Type) and Step 7 (Authorization) have passed.

3. Fix Defect 3 in _read_body (line 696):

- Change chunk = conn.recv(min(_RECV_CHUNK, need)) to chunk = conn.recv(min(_RECV_CHUNK, need + 1)) so already-buffered trailing bytes in SO_RCVBUF when the body read completes are read and rejected by line 704 (if len(body) > content_length: raise _ReqErrorSignal(400, "invalid", False, False)).

4. Fix Defect 4 in __init__ (lines 284, 300–318) and close (lines 392–401):

- In __init__: populate self._idle_slots = list(self._slots) before starting threads, and start the 6 worker threads before self._accept_thread.start().

- In close(): track self._listener_closed = False under self._pool_cond. Under with self._pool_cond:, set should_close_listener = not self._listener_closed; self._listener_closed = True; self._draining = True, close/clear any non-None slot.conn across self._slots (matching _rollback_startup), and notify_all(). Only invoke self._wake_listener() and self._listener.close() when should_close_listener is True.

## 4. Required Regression Probes (tests/test_http_adapter.py)

1. Framing without \r\n\r\n: Raw socket tests sending (a) 8,193-byte request line without \r\n\r\n, (b) 24-byte request line + 16,385-byte header without \r\n\r\n, and (c) LF-only request POST /v1/list HTTP/1.1\nHost: 127.0.0.1\n\n must promptly receive 400 Bad Request (code="invalid", retry_safe=False), never 504 timeout or silent EOF.

2. Pre-body header check priority on >10-digit Content-Length: Raw socket sending Content-Length: 99999999999 with missing/invalid Authorization must receive 403 denied (not 413 too_large); with valid Authorization and Content-Type: text/plain must receive 400 invalid; Content-Length: 00000000002 with valid headers and {} body must pass Step 5.

3. Multi-chunk / >4 KiB body with buffered trailing pipelined request: Send a valid request with Content-Length: 5000 concatenated with a second HTTP request in one sendall(); assert 400 invalid and zero LocalFileService execution.

4. Immediate post-__init__ 6-request burst & repeat/concurrent close(): Issue 6 concurrent requests immediately after DriveHTTPAdapter(...) returns (assert zero 503 busy), and verify that when close(timeout=0.05) returns False during an in-flight barrier, binding a new socket or calling close(timeout=5.0) a second time (and concurrently from two threads) does not connect to the released port and returns True once the barrier releases.
