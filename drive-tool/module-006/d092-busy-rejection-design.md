# d092 (gemini)

- status: done
- chat: https://gemini.google.com/app/4c2c07b9bf2ca759
- model: 4 argon (thinking: high)
- finished: 2026-10-16T00:53:11Z

## Question

Gemini, focused busyreject transport diagnosis/design D092. D088attributionproven; exactsource supplied. Preserve50ms/16KiB/fixedthreads/noqueue; no blanketerrorbudget or impossibletransportguarantees. Minimal phasebudget correction+regressions ifneeded; noimplementation. AdoptD089orthogonalgates with honest schedulerlimits. StaticTESTS_NOT_RUN.

(input files: Dolesh-avkalan/drive-tool:tasks/d092-busy-rejection-design.txt@f8b63ad0658c6cba63c5197c715b8c5e90786a02)

## Answer

## D092 Design Decision: _busy_reject Phase-Budget Partitioning

Decision: Adopt a minimal three-phase budget split inside _busy_reject(self, conn) that preserves the existing 50ms (BUSY_REJECT_BUDGET_SECONDS = 0.050) total wall-clock ceiling, 16 KiB (MAX_BUSY_READ_BYTES = 16384) total read cap, fixed worker pool, and zero-queue architecture. Cap the pre-response read phase to a short slice (10ms) and reserve a guaranteed response-write window (20ms minimum) followed by half-close (SHUT_WR) and a bounded post-write drain (20ms cap within busy_deadline).

## 1. D088 Root-Cause Diagnosis & Attribution Proof

Empirical evidence from D088 (7dab4357 / 8cd137f7) isolates all unexpected client unavailable errors during saturation to transport-level RemoteDisconnected inside _busy_reject:

| Metric (D088 Saturation Run) | Observed Count | Attribution Meaning |
| --- | --- | --- |
| server_busy_reject | 39 | Exact number of connections entering _busy_reject on the accept thread |
| client_busy | 37 | Rejections where the 503 busy JSON envelope was written and read cleanly |
| client_unavailable | 2 | Client caught RemoteDisconnected (EOF before status line) and synthesized unavailable |
| server_unavailable_envelopes | 0 | Server never emitted an HTTP unavailable envelope |
| malformed_fallback | 0 | _safe_send_error fallback path never triggered |

### Exact Mechanism of Failure in Supplied _busy_reject Source

1. Monolithic Deadline Starvation: _busy_reject sets a single deadline busy_deadline = time.monotonic() + BUSY_REJECT_BUDGET_SECONDS (50ms) and immediately assigns the entire remaining 50ms timeout to the pre-response conn.recv(MAX_BUSY_READ_BYTES).

2. Handshake-Before-Payload Race: Because accept() returns as soon as the kernel completes the TCP 3-way handshake (SYN / SYN-ACK / ACK), the server accept thread frequently enters _busy_reject and calls conn.recv(...) before the client thread executes sendall() to place the HTTP request into the socket (or when a raw/stalled peer pauses after connecting).

3. Zero-Byte Response Write: If the client thread is delayed by 50ms between connect() and sendall() (or stalls on a raw socket), the pre-response conn.recv() blocks for the full 50ms busy_deadline and times out. Execution then enters self._send_with_deadline(conn, response, busy_deadline), which immediately evaluates remaining = deadline - time.monotonic(), finds remaining <= 0, and returns False without calling conn.send().

4. Silent EOF (RemoteDisconnected): _busy_reject proceeds directly to conn.shutdown(socket.SHUT_WR) and conn.close() having written 0 bytes. DriveClient reads an empty EOF (http.client.RemoteDisconnected) and maps it to a client-side unavailable error (37 + 2 = 39).

5. Secondary Post-Write Drain Stall: In the existing post-write drain loop (while total_read < MAX_BUSY_READ_BYTES), any peer that sent fewer than 16 KiB and has not yet closed its write side holds the single accept thread until the full 50ms busy_deadline expires, delaying subsequent connections waiting in the listen backlog.

## 2. Minimal Phase-Budget Design (Within 50ms / 16 KiB)

To guarantee that the pre-response read can never starve the 184-byte HTTP 503 busy write while still draining normal small requests to prevent kernel TCP RST on close(), partition BUSY_REJECT_BUDGET_SECONDS (0.050s) into three bounded phases:

| Phase | Constant | Budget Slice | Responsibility & Invariant |
| --- | --- | --- | --- |
| Phase 1: Bounded Pre-Read | BUSY_PRE_READ_BUDGET_SECONDS = 0.010 | Up to 10ms (clamped to busy_deadline - BUSY_WRITE_RESERVE_SECONDS) | Single conn.recv(MAX_BUSY_READ_BYTES) absorbs request bytes already in SO_RCVBUF. Times out after at most 10ms if client write is delayed, leaving 40ms for write + drain. |
| Phase 2: Reserved Write | BUSY_WRITE_RESERVE_SECONDS = 0.020 | At least 20ms reserved (up to 40ms remaining before busy_deadline) | self._send_with_deadline(conn, response, busy_deadline) writes the static 503 busy response into SO_SNDBUF, followed immediately by conn.shutdown(socket.SHUT_WR) to queue TCP FIN. |
| Phase 3: Bounded Post-Drain | BUSY_POST_DRAIN_BUDGET_SECONDS = 0.020 | Up to 20ms (clamped to busy_deadline) | Loops conn.recv(MAX_BUSY_READ_BYTES - total_read) until EOF (not chunk), total_read == 16384, or drain_deadline expiry, then calls conn.close(). |

### Normal Small Requests vs. Adverse / Oversized / Stalled Inputs

- Well-Formed Small Requests (DriveClient): Request payloads are well under 16 KiB (typically 200–600 bytes).

- If request bytes arrive within 10ms, Phase 1 drains them in less than 1ms, Phase 2 writes the 503 response and SHUT_WR in less than 0.5ms, and Phase 3 exits as soon as the client reads the 503 and closes (b"" EOF). Even if the client reads slowly after drain_deadline, SO_RCVBUF is already empty (0 unread bytes), so conn.close() emits a clean FIN rather than TCP RST.

- If the client thread is preempted between connect() and sendall() for more than 10ms, Phase 1 times out at +10ms, Phase 2 immediately writes the 503 response and SHUT_WR into the socket buffer, and Phase 3 absorbs the late-arriving request bytes up to drain_deadline.

- Adverse, Oversized (greater than 16 KiB), or Stalled Peers (Best-Effort Caveat):

- If an adversarial or broken peer transmits more than MAX_BUSY_READ_BYTES (16 KiB) or stalls without reading across the entire 50ms window while continuing to push unread bytes into SO_RCVBUF after drain_deadline, calling conn.close() with unread bytes remaining in SO_RCVBUF may still cause the OS kernel to emit TCP RST. This is a fundamental TCP/kernel boundary and remains an explicitly accepted best-effort limit so the single accept thread cannot be pinned past 50ms or 16 KiB.

- The accept thread never parses HTTP headers, never authenticates tokens, and never touches the filesystem during _busy_reject.

## 3. Exact Correction Contract for DeepSeek

Apply only the following surgical constants and _busy_reject phase-budget logic (no architectural rewrites, no extra threads, no queues, no client retries):

```python
BUSY_REJECT_BUDGET_SECONDS = 0.050
BUSY_PRE_READ_BUDGET_SECONDS = 0.010
BUSY_WRITE_RESERVE_SECONDS = 0.020
BUSY_POST_DRAIN_BUDGET_SECONDS = 0.020
MAX_BUSY_READ_BYTES = 16384
```

```python
    def _busy_reject(self, conn):
        now = time.monotonic()
        busy_deadline = now + BUSY_REJECT_BUDGET_SECONDS
        total_read = 0

        # Phase 1: Bounded pre-read that cannot consume the reserved write budget.
        pre_read_deadline = min(
            now + BUSY_PRE_READ_BUDGET_SECONDS,
            busy_deadline - BUSY_WRITE_RESERVE_SECONDS,
        )
        remaining = pre_read_deadline - time.monotonic()
        if remaining > 0:
            try:
                conn.settimeout(remaining)
                chunk = conn.recv(MAX_BUSY_READ_BYTES)
                if chunk:
                    total_read += len(chunk)
            except (socket.timeout, OSError, ValueError):
                pass

        # Phase 2: Reserved response write slice within the 50ms total ceiling.
        body = (
            b'{"ok":false,"error":{"code":"busy",'
            b'"outcome_uncertain":false,"retry_safe":true}}'
        )
        response = (
            b"HTTP/1.1 503 Service Unavailable\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
            b"Connection: close\r\n"
            b"\r\n"
            + body
        )
        self._send_with_deadline(conn, response, busy_deadline)

        try:
            conn.shutdown(socket.SHUT_WR)
        except OSError:
            pass

        # Phase 3: Bounded post-write drain within remaining 50ms / 16 KiB budget.
        drain_deadline = min(
            busy_deadline,
            time.monotonic() + BUSY_POST_DRAIN_BUDGET_SECONDS,
        )
        while total_read < MAX_BUSY_READ_BYTES:
            remaining = drain_deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                conn.settimeout(remaining)
                chunk = conn.recv(MAX_BUSY_READ_BYTES - total_read)
            except (socket.timeout, OSError, ValueError):
                break
            if not chunk:
                break
            total_read += len(chunk)

        try:
            conn.close()
        except OSError:
            pass
```

## 4. D089 Orthogonal Gates, Scheduler Honesty & Regression Contract
### Orthogonal Gate Criteria (D089)

1. Gate 1 — Valid Below-Capacity Gate (6 concurrent requests, max_workers = 6):

- Condition: Up to 6 concurrent well-formed DriveClient requests execute within server capacity.

- Pass Criterion: 6/6 return ok: True, busy == 0, unexpected unavailable == 0, retries == 0.

2. Gate 2 — Normal Barrier-Synchronized Saturation Gate (6 + 1 deterministic busy test):

- Condition: 6 worker-holding requests synchronize via an in-handler entry barrier/event to occupy all 6 worker threads (using the D089 55ms hold schedule budget), and 1 additional well-formed small DriveClient request is issued once all 6 workers have signaled entry.

- Pass Criterion: 6 holder requests complete with ok: True, the +1 overflow request deterministically receives HTTP 503 busy (ok: False, code == "busy", outcome_uncertain == False, retry_safe == True), unexpected unavailable == 0 (zero blanket unavailable allowance), and retries == 0.

- Honest Scheduler Caveat on the 55ms Hold: The 55ms worker hold in D089 is a test schedule budget only, not a mathematical occupancy invariant under arbitrary OS scheduler preemption. If an overloaded host OS suspends the +1 client thread for longer than the remaining hold window after barrier release, a worker may legitimately finish before the +1 connection is accepted. Gate 2 assumes normal local scheduler progression after barrier release and must not make impossible real-time OS scheduling claims.

### Required Repro & Regression Tests for DeepSeek

- Test 1 — Delayed-Payload Busy Reject Repro (Direct D088 Regression):

- Occupy all 6 worker threads via barrier synchronization. Open a raw TCP connection (7th connection) to the server, wait 15ms–25ms after connect() before sending a valid small HTTP request (reproducing the D088 connect()-to-sendall() scheduling gap that previously starved _busy_reject when pre-read used the full 50ms), and read the response.

- Assertion: Under the old monolithic 50ms pre-read if delayed to 50ms (or when pre-read consumed the budget), _send_with_deadline aborted; under the D092 phase split, any connection that stalls during the 10ms pre-read still receives the full HTTP 503 busy JSON envelope within the 50ms budget with zero RemoteDisconnected errors.

- Test 2 — Deterministic 6 + 1 Actual DriveClient Saturation Test:

- Run 6 barrier-held requests (55ms hold budget after barrier entry) plus 1 actual DriveClient small request with retries disabled (retries = 0).

- Assertion: Exactly 6 ok: True responses, 1 code == "busy" response, 0 unavailable responses.

- Test 3 — 50ms / 16 KiB Ceiling Enforcement on Stalled/Oversized Peer:

- While all 6 workers are held, connect a raw socket that sends nothing (stalled peer) or streams 32 KiB without closing.

- Assertion: _busy_reject returns HTTP 503 busy, reads at most 16384 bytes, and releases the accept thread within the 50ms budget window (plus normal socket teardown tolerance).

## 5. Six-Persona Review Sign-Off

- Systems / Concurrency Architect: Approved. Splitting the 50ms ceiling into 10ms pre-read, >= 20ms reserved write, and <= 20ms post-drain eliminates accept-thread write starvation without adding queues, worker threads, or blocking locks.

- Network / Transport Engineer: Approved. Capping pre-read ensures self._send_with_deadline always executes with positive deadline remaining, conn.shutdown(socket.SHUT_WR) cleanly sequences the server FIN behind the 503 payload, and bounded pre/post draining prevents kernel TCP RST on well-formed small DriveClient requests.

- Security / Abuse-Resistance Reviewer: Approved. Total accept-thread time per rejected connection remains strictly bounded by BUSY_REJECT_BUDGET_SECONDS (50ms) and MAX_BUSY_READ_BYTES (16 KiB), with zero authentication or filesystem work on the reject path.

- Protocol / API Contract Reviewer: Approved. Well-formed rejected requests deterministically receive {"ok":false,"error":{"code":"busy","outcome_uncertain":false,"retry_safe":true}} rather than collapsing into client-synthesized unavailable (outcome_uncertain: true) via RemoteDisconnected.

- Test / Determinism Engineer: Approved. Adopts D089 orthogonal below-capacity (6/6) and barrier-saturation (6+1) gates with unexpected unavailable == 0 and zero retries, while explicitly framing the 55ms worker hold as a test schedule budget rather than an absolute OS scheduler guarantee.

- Implementation / Release Gatekeeper: Approved. Scope is restricted to a 3-constant + ~10-line phase-deadline refinement inside _busy_reject plus focused regression tests for DeepSeek implementation.

Status: Static design analysis only — TESTS_NOT_RUN.
