# d084 (gemini)

- status: done
- chat: https://gemini.google.com/app/0b75b07bd134b2f2
- model: 4 argon (thinking: high)
- finished: 2026-10-16T00:18:08Z

## Question

Gemini, focused delta review D084 in existing D074context. Exactcc1cd326 production8cd137f7, actual oldfail/newpass supplied. No repeated fullaudit or authadjudication if D083 alreadyhandlesit; scope security/lifecycle remainingdefects. Static TESTS_NOT_RUN, noimplementation/merge/deploy. Return narrow verdict and concrete requiredprobes.

(input files: Dolesh-avkalan/drive-tool:tasks/d084-http-delta-review.txt@1f7fc7f60dcfc82e41bbfe0c946d287d1ce83d72)

## Answer

Verdict (D084 Security & Lifecycle Delta Only): ACCEPT
Execution Status: TESTS_NOT_RUN (static review of drive_tool/http_adapter.py delta 02576d59… $\rightarrow$ 8cd137f7323eb5c9e1e4166471a04073204840e5 at head cc1cd326a1df85ad906796e535db466b4cf664ba, evaluated alongside the supplied D081 oldfail/newpass and D079 execution evidence; the 9 pre-existing auth/schema delegation failures are deferred to D083 without re-adjudication here).

## 1. Itemized Delta Adjudication (D074 Defects 1–4)
### 1.1 Defect 1 — Pre-\r\n\r\n Framing & Bare-LF/CR Bounds (_read_request / _check_partial_header_block, lines 676, 720–752)

- Status: Resolved (ACCEPT).

- Analysis: Calling self._check_partial_header_block(buf) at the top of Phase A (immediately after checking buf.find(b"\r\n\r\n") and before the next conn.recv()) deterministically rejects bare \n, bare \r, invalid request-line bytes, request lines exceeding MAX_REQUEST_LINE_BYTES (8,192 B), invalid method/target/version once the first \r\n arrives, header blocks exceeding MAX_HEADER_BLOCK_BYTES (16,384 B), and header line counts exceeding MAX_HEADER_COUNT (64) with 400 invalid before blocking on another socket read or hitting 504 timeout / silent EOF on half-close. Because if idx >= 0: break executes prior to _check_partial_header_block(buf), body bytes following \r\n\r\n are never scanned by the partial header check.

### 1.2 Defect 2 — Content-Length Digit Normalization & Step 5 vs. Step 8 Priority (_check_headers, lines 827–831)

- Status: Resolved (ACCEPT) in drive_tool/http_adapter.py; 1 pre-existing test expectation in tests/test_http_adapter.py requires alignment.

- Analysis: cl_norm = cl_raw.lstrip(b"0") or b"0" normalizes leading zeros before checking _MAX_CONTENT_LENGTH_DIGITS (10), and len(cl_norm) > _MAX_CONTENT_LENGTH_DIGITS assigns content_length = MAX_SAVE_BODY_BYTES + 1 instead of raising 413 inside Step 5. Step 6 (Content-Type $\rightarrow$ 400 invalid) and Step 7 (lexical Authorization $\rightarrow$ 403 denied) now execute before Step 8 raises 413 too_large.

- Adjudication of the 10th Suite Failure (huge_digit_content_length): Under Contract §3.4 Steps 5 and 8, a Content-Length matching ^[0-9]+$ with $>10$ significant digits (plus valid Content-Type and valid lexical Authorization) is syntactically valid decimal digits whose numeric value exceeds the wire payload size cap. Returning 413 too_large at Step 8 is the required contract behavior; test_all_framing_cases_rejected_400_invalid (huge_digit_content_length) in tests/test_http_adapter.py is a test-vs-contract divergence and must be moved/updated to assert 413 too_large (code="too_large").

### 1.3 Defect 3 — Unreachable Post-recv Check in _read_body (lines 890–892)

- Status: Disconfirmed as a defect / Resolved (ACCEPT).

- Analysis: Removing the unreachable if len(body) > content_length: line without adding speculative over-read preserves exact Content-Length framing and honors Contract §3.5.2 and the D064 override: trailing bytes already buffered in the header recv() (len(initial) > content_length) fail closed with 400 invalid before LocalFileService dispatch, and a second request is never parsed or executed.

### 1.4 Defect 4 — Startup Slot Readiness, Once-Only Listener Wake/Close, and 4.3 Handed-Off Slot vs. Actively-Owned Request Socket

- 4.1 Startup Slot Readiness (__init__, lines 307–308, 325–327): Resolved (ACCEPT). Pre-populating self._idle_slots.extend(self._slots) under self._pool_cond and starting all 6 workers before self._accept_thread.start() eliminates the static startup race by construction. Evaluating this via the deterministic post-__init__ invariant (len(adapter._idle_slots) == MAX_IN_FLIGHT_OPERATIONS) plus a 6-way concurrent burst is sufficient; no artificial thread-scheduler delay injection is required.

- 4.2 Once-Only Listener Wake/Close (close, lines 399–424): Resolved (ACCEPT). Tracking self._listener_closed under self._pool_cond ensures _wake_listener() and _listener.close() run at most once across repeated close() calls.

- 4.3 Handed-Off slot.conn vs. Actively-Owned Worker Socket & close() Deadline (close, lines 409–415; _worker_loop, lines 495–505): Resolved (ACCEPT).

- Distinction:

1. Pending handoff (slot.conn is not None): When _accept_loop assigns slot.conn = conn and close() acquires self._pool_cond before the woken worker pops slot.conn, close() now closes slot.conn, sets slot.conn = None, sets self._draining = True, and calls notify_all(). When the worker wakes from _pool_cond.wait(), it sees slot.conn is None and exits immediately without calling _serve(conn).

2. Actively-owned worker socket (slot.conn is None, worker inside _serve(conn)): Once a worker pops conn = slot.conn; slot.conn = None, conn belongs exclusively to that worker thread. close() must not cross-thread close() an active worker socket while the worker is executing settimeout/recv/send/shutdown, as doing so asynchronously closes the underlying OS file descriptor and creates a POSIX FD-reuse hazard against concurrent threads.

3. Bounded deadlines under active ownership: A worker already blocked in _read_request(conn) on an idle peer is bounded by its monotonic request_deadline = time.monotonic() + self._socket_timeout (Contract §3.1, emitting 504 timeout on expiry), while close(timeout=...) is bounded by its own single shared deadline = time.monotonic() + timeout_f via worker.join(timeout=remaining) (Contract §7.2, returning False when timeout < remaining_socket_timeout and True on a subsequent close() once the worker finishes). If the peer finishes sending its request after self._service.close() has run, LocalFileService._ensure_not_draining() rejects it immediately with 503 unavailable. Consequently, D079's observation on an already-serving idle connection is expected contract behavior, not a remaining defect.

- Non-Blocking Lifecycle Note on _close_lock (close, line 399): Wrapping the entire close() body (including self._service.close(timeout=remaining) and worker.join(timeout=remaining)) inside with self._close_lock: is safe for sequential/repeat close() calls, but if two threads call close(timeout=5.0) and close(timeout=0.05) concurrently, the second caller waits on _close_lock for the first caller's join before computing deadline = time.monotonic() + timeout_f. If DeepSeek touches http_adapter.py during the D083 pass, computing deadline = time.monotonic() + timeout_f before acquiring _close_lock (or relying on self._pool_cond to guard _closed, _listener_closed, _draining, and slot.conn without holding a lock across service.close() / worker.join()) is a clean 2-line refinement, though not a blocker on its own.

## 2. Concrete Required Test & Probe Adjustments (tests/test_http_adapter.py)

1. Reclassify huge_digit_content_length in tests/test_http_adapter.py:

- Update test_all_framing_cases_rejected_400_invalid (huge_digit_content_length) (where Content-Type and lexical Authorization are valid and Content-Length is all-digit $>10$ digits) to expect 413 Payload Too Large (code="too_large", outcome_uncertain=False, retry_safe=False) per Contract §3.4 Step 8, matching test_content_length_priority_and_leading_zeros.

2. Retain the 4 D080SecurityFixRegressionTests in tests/test_http_adapter.py:

- test_partial_header_bounds_reject_early (overlong request line, overlong header block, and bare LF without \r\n\r\n $\rightarrow$ 400 invalid).

- test_content_length_priority_and_leading_zeros (missing auth + 11-digit CL $\rightarrow$ 403 denied; bad Content-Type + valid auth + 11-digit CL $\rightarrow$ 400 invalid; leading-zero CL 00000000002 passes framing).

- test_startup_six_worker_readiness (deterministic len(adapter._idle_slots) == 6 post-__init__ check + 6-way concurrent burst with zero 503 busy).

- test_repeat_close_does_not_wake_released_port (assert _wake_listener is invoked exactly once across an incomplete close(timeout=...) returning False followed by a subsequent close(timeout=...) returning True).

3. Optional Deterministic Probe for 4.3 Pending-Handoff Closure (if desired in D080SecurityFixRegressionTests):

- Rather than racing an OS thread wakeup, acquire adapter._pool_cond in a test, pop an idle slot and assign a socket.socketpair() endpoint to slot.conn without notifying workers, release adapter._pool_cond, and call adapter.close(timeout=1.0): assert close() returns True immediately, slot.conn is None, and the peer endpoint observes immediate EOF (recv(1) == b"") without waiting for socket_timeout.
