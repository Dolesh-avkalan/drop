# D079 — independent security counterexample execution (no fixes)

**Task:** D079. Independently reproduce the counterexamples in the Gemini D074 review
against the integrated candidate, prove raw statuses / timing / exits / cleanup, and
evaluate Defect 3 honestly. No fixes, no production or test-branch changes.

## 0. Source identity

- candidate commit `f304425ab774158090edd69f1b605bcc3b03096d` (integration `cc9c994e`
  + D076 save-test correction); source and tests were **not modified** by D079.
- `drive_tool/http_adapter.py` — blob `02576d59d555afc7afde89fd8e2e63a1c1c43e24`,
  37502 bytes, sha256 `191ad2be919fabdd2f4ec9edb0820165c2c4358ce05c93574514b5ee30a30ff3`, 1099 lines.
- reviewed report: `drop` `7a84686a02a736b7ec181658902f4db08725b267`,
  `drive-tool/module-006/d074-http-security-review.md`, blob `cc172871…`.
- every probe ran against the real adapter over synthetic temporary roots; all probes are
  bounded (socket_timeout shortened to 1–2 s) and finish in well under 5 minutes.
- results are identical on CPython 3.11.2 and 3.12.13.

## 1. Verdicts

| # | Gemini claim | D079 verdict |
| --- | --- | --- |
| 1 | Framing bounds / bare-LF without CRLFCRLF stall until 504 (or silent EOF) | **CONFIRMED** |
| 2 | `_check_headers` Step 5 raises 413 before Step 6/7; leading zeros rejected | **CONFIRMED** |
| 3 | Trailing-bytes check in `_read_body` is unreachable dead code | **DISCONFIRMED as a defect** |
| 4.1 | Startup 6-slot false 503 busy race | **NOT REPRODUCED** |
| 4.2 | Repeat/concurrent `close()` wake-connects to the released port | **CONFIRMED (mechanism)** |
| 4.3 | Handed-off connection not closed by `close()` | **CONFIRMED** |

## 2. Defect 1 — CONFIRMED (`logs/probe_framing_*.txt`)

`_read_request` Phase A loops on `buf.find(b"\r\n\r\n")` and only guards
`len(buf) > MAX_REQUEST_LINE_BYTES + MAX_HEADER_BLOCK_BYTES` (24576) inside the loop; the
finer limits (request line 8192, header block 16384, bare `\n`) are deferred until after
the terminator is present. Raw results (socket_timeout = 1.0 s):

```
overlong request line, no CRLFCRLF     half=False elapsed= 1.001s bytes=186 504 Gateway Timeout code=timeout
overlong request line, no CRLFCRLF     half=True  elapsed= 0.001s bytes=0   <no bytes>
overlong header block, no CRLFCRLF     half=False elapsed= 1.002s bytes=186 504 Gateway Timeout code=timeout
overlong header block, no CRLFCRLF     half=True  elapsed= 0.001s bytes=0   <no bytes>
bare LF terminator                     half=False elapsed= 1.002s bytes=186 504 Gateway Timeout code=timeout
bare LF terminator                     half=True  elapsed= 0.001s bytes=0   <no bytes>
control: buffer > 24576 (size check)   half=False elapsed= 0.001s bytes=183 400 Bad Request     code=invalid
```

Contract expectation is a prompt `400 invalid`; observed is `504 timeout` after the socket
timeout, or **0 bytes** on peer half-close. The coarse >24576 guard does fire immediately,
which isolates the fault to the missing fine-grained checks, not to the loop itself.

## 3. Defect 2 — CONFIRMED (`logs/probe_content_length_*.txt`)

Step 5 raises `413 too_large` when `len(cl_raw) > 10` before Step 6 (Content-Type) and
Step 7 (Authorization), and counts raw digits without normalising leading zeros:

```
c1 huge CL, no Authorization                        413 Payload Too Large  code=too_large   (contract: 403 denied)
c2 huge CL, valid auth, CT text/plain               413 Payload Too Large  code=too_large   (contract: 400 invalid)
c3 leading zeros CL 00000000002, valid auth+CT {}   413 Payload Too Large  code=too_large   (contract: Step 5 pass)
c4 control 11-digit CL, valid auth+CT json          413 Payload Too Large  code=too_large   (legitimate)
c5 control CL 2, valid auth+CT json, body {}        403 Forbidden          code=denied      (dispatched normally)
```

## 4. Defect 3 — DISCONFIRMED as a defect (`logs/probe_pipelined_*.txt`)

Gemini is right that the *inner* check
if len(body) > content_length: raise 400 invalid` inside the read loop is unreachable,
because the loop reads `conn.recv(min(_RECV_CHUNK, need))` and can never overbuffer past
content_length`. That alone is not a defect: the check is redundant defence-in-depth.

The contract requirement (§3.5.2.1) is narrower — reject when the buffered recv that
completed the header block **already** contains more than `content_length` bytes beyond
`\r\n\r\n`. That requirement **is** implemented and **is** reachable, as the first
statement of `_read_body`:

```python
def _read_body(self, conn, initial, content_length, deadline):
    if len(initial) > content_length:
        raise _ReqErrorSignal(400, "invalid", False, False)
```

Raw evidence:

```
A already-buffered > CL (CL=100, 200 sent)   400 Bad Request  service_calls=0 []
B control CL=2 body {}                       403 Forbidden    service_calls=1 [('list', None)]
C pipelined req1(CL=6000)+req2               200 OK           service_calls=1 [('list', 'root')]
D pipelined req1(CL=6000)+req2 again         200 OK           service_calls=1 [('list', 'root')]
```

- Case A: when the header-completing recv really did buffer more than `content_length`
  bytes beyond the header, the adapter rejects with `400 invalid` and calls
  `LocalFileService` **zero** times — the contract behaviour.
- Cases C/D: a pipelined second request left in the kernel receive buffer (not
  already-buffered past the framing point) yields `200 OK` — which is contract-correct,
  because no single recv buffer ever held more than `content_length` bytes beyond
  `\r\n\r\n`. Critically, **the second request is never executed**: `service_calls == 1`
  in both runs, and the trailing bytes are discarded by `_finalize_connection`'s bounded
  drain before the socket is closed.

So: no contract violation, no request smuggling, no second request executed. D079 does
**not** call this a defect merely because a line is unreachable, and does not propose any
speculative peek/wait.

## 5. Defect 4 — lifecycle (`logs/probe_lifecycle_*.txt`)

**4.1 startup 6-slot false 503 — NOT REPRODUCED.** `self._idle_slots = []` is initialised
empty and `self._accept_thread.start()` runs before the six worker threads start, so the
static window exists. But 40 trials × 6 concurrent requests issued immediately after
`__init__` returned produced **zero** busy rejections:

```
trials=40 requests=240 tally={'ok_403': 240}
```

Every request was parsed and dispatched normally. The window is narrow: the accept thread
polls with a 50 ms listener timeout and the workers register during startup, so a client
that connects after `__init__` returns did not observe a false 503 in this bounded probe.
Reported honestly as not reproduced (static window present, no dynamic counterexample).

**4.2 repeated close() wake-connects after the listener is closed — CONFIRMED (mechanism).**
With an in-flight gated operation, `close(timeout=0.1)` returned `False` and closed the
listener; a second `close()` still had `self._closed == False`, so it re-invoked
`_wake_listener()`. Instrumenting `_wake_listener` to record its target:

```
close#1(timeout=0.1) -> False  wake_calls=1  targets=[(37829, 9)]     <- listener fd 9 (open)
close#2(timeout=0.3) -> True   wake_calls=2  targets=[(37829, 9), (37829, -1)]  <- fd -1 = listener CLOSED
```

The second call targets `(127.0.0.1, 37820)` — the adapter's released port — while the
listener is already closed (`fileno() == -1`). Whether that connect reaches a foreign
socket depends on the OS port state at that instant; the released port could not be
re-bound during the probe window (the in-flight connection still held it), so the
"hits another listener" consequence was not directly observed. The wake-connect against a
closed listener is confirmed.

**4.3 handed-off connection not closed by close() — CONFIRMED (3/3).** An idle client
connected and was handed to a worker; `close(timeout=0.05)` returned `False` immediately,
and the connection was **not** closed by `close()` — the worker entered `_serve`, blocked,
and only closed the socket after the socket timeout:

```
trial 0: close(0.05)=False returned in 0.050s; client got 186 bytes after 1.982s status=HTTP/1.1 504 Gateway Timeout
trial 1: close(0.05)=False returned in 0.050s; client got 186 bytes after 1.980s status=HTTP/1.1 504 Gateway Timeout
trial 2: close(0.05)=False returned in 0.051s; client got 186 bytes after 1.981s status=HTTP/1.1 504 Gateway Timeout
```

This matches Gemini's description: unlike `_rollback_startup()`, `close()` does not
close/clear `slot.conn`, so a handed-off connection is served after `close()` begins.

## 6. Scope

Independent counterexample execution only. No fixes, no production or test-branch
changes, no merge, no deploy, no real roots. Source and tests are byte-unchanged
(`http_adapter.py` blob `02576d59`, `tests/test_http_adapter.py` blob `80798e32`).
