# d080 (deepseek)

- status: done
- chat: https://chat.deepseek.com/a/chat/s/a8b2e4a5-f103-46b5-b8c4-5461c4abad50
- model: deepseek (deepthink on, search off)
- finished: 2026-10-15T23:07:15Z

## Question

DeepSeek, narrow HTTP fixes/regressions for D074 findings1/2/4 under D080; production02576d59 on integrated f304425a base. Do not alter auth/schema semantics pending GeminiD075. Defect3 is tentative: never force speculative overread to prove absent future pipelining. Minimal patch, honest tests provenance; no merge/deploy. Sarvam tests and Gemini reviews delta.

(input files: Dolesh-avkalan/drive-tool:tasks/d080-http-security-fixes.txt@99a4b28cf3e0b2b75be43cc62129a7578ff9aadb)

## Answer

Scope: D080 narrow correction only. Patch targets drive_tool/http_adapter.py; regressions target tests/test_http_adapter.py. D074 defect 3 is not “fixed” by speculative over-read/peek. The only dead-code removal is the unreachable post-recv excess check in _read_body, with no behavioral change. Auth/schema delegation semantics for invalid JSON payloads remain untouched pending Gemini D075.

Execution provenance: TESTS_NOT_RUN here. Sarvam assembles/executes; Gemini reviews delta. No merge/deploy/real roots.

## Patch: drive_tool/http_adapter.py

```diff
--- a/drive_tool/http_adapter.py
+++ b/drive_tool/http_adapter.py
@@
         self._port = 0
         self._listener = None
         self._accept_thread = None
         self._slots = []
         self._workers = []
         self._draining = False
         self._closed = False
+        self._listener_closed = False
 
         self._pool_lock = threading.Lock()
         self._pool_cond = threading.Condition(self._pool_lock)
         self._idle_slots = []
+        self._close_lock = threading.Lock()
@@
             self._listener = listener
             self._port = bound_port
 
             for _ in range(MAX_IN_FLIGHT_OPERATIONS):
                 self._slots.append(_WorkerSlot())
 
+            with self._pool_cond:
+                self._idle_slots.extend(self._slots)
+
             self._accept_thread = threading.Thread(
                 target=self._accept_loop,
                 name="drive-http-accept",
                 daemon=False,
             )
@@
                 slot.thread = worker
                 self._workers.append(worker)
 
-            self._accept_thread.start()
             for worker in self._workers:
                 worker.start()
+            self._accept_thread.start()
         except BaseException:
             self._rollback_startup()
             raise
@@
     def close(self, *, timeout=DEFAULT_DRAIN_TIMEOUT_SECONDS):
         if type(timeout) is bool or not isinstance(timeout, (int, float)):
             raise ValueError("timeout must be a finite non-negative number")
         timeout_f = float(timeout)
         if not math.isfinite(timeout_f) or timeout_f < 0.0:
             raise ValueError("timeout must be a finite non-negative number")
 
-        if self._closed:
-            return True
-
-        deadline = time.monotonic() + timeout_f
-
-        with self._pool_cond:
-            self._draining = True
-            self._pool_cond.notify_all()
-
-        self._wake_listener()
-
-        if self._listener is not None:
-            try:
-                self._listener.close()
-            except OSError:
-                pass
-
-        remaining = max(0.0, deadline - time.monotonic())
-        try:
-            service_closed = self._service.close(timeout=remaining)
-        except BaseException:
-            service_closed = False
-
-        if self._accept_thread is not None:
-            remaining = max(0.0, deadline - time.monotonic())
-            try:
-                self._accept_thread.join(timeout=remaining)
-            except BaseException:
-                pass
-
-        for worker in self._workers:
-            remaining = max(0.0, deadline - time.monotonic())
-            try:
-                worker.join(timeout=remaining)
-            except BaseException:
-                pass
-
-        accept_done = self._accept_thread is None or not self._accept_thread.is_alive()
-        workers_done = all(not worker.is_alive() for worker in self._workers)
-
-        if service_closed and accept_done and workers_done:
-            self._closed = True
-            return True
-        return False
+        with self._close_lock:
+            if self._closed:
+                return True
+
+            deadline = time.monotonic() + timeout_f
+
+            with self._pool_cond:
+                should_close_listener = not self._listener_closed
+                self._listener_closed = True
+                self._draining = True
+                for slot in self._slots:
+                    if slot.conn is not None:
+                        try:
+                            slot.conn.close()
+                        except OSError:
+                            pass
+                        slot.conn = None
+                self._pool_cond.notify_all()
+
+            if should_close_listener:
+                self._wake_listener()
+                if self._listener is not None:
+                    try:
+                        self._listener.close()
+                    except OSError:
+                        pass
+
+            remaining = max(0.0, deadline - time.monotonic())
+            try:
+                service_closed = self._service.close(timeout=remaining)
+            except BaseException:
+                service_closed = False
+
+            if self._accept_thread is not None:
+                remaining = max(0.0, deadline - time.monotonic())
+                try:
+                    self._accept_thread.join(timeout=remaining)
+                except BaseException:
+                    pass
+
+            for worker in self._workers:
+                remaining = max(0.0, deadline - time.monotonic())
+                try:
+                    worker.join(timeout=remaining)
+                except BaseException:
+                    pass
+
+            accept_done = self._accept_thread is None or not self._accept_thread.is_alive()
+            workers_done = all(not worker.is_alive() for worker in self._workers)
+
+            if service_closed and accept_done and workers_done:
+                self._closed = True
+                return True
+            return False
@@
         # Phase A: read until the header terminator CRLFCRLF.
         while True:
             idx = buf.find(b"\r\n\r\n")
             if idx >= 0:
                 break
+            self._check_partial_header_block(buf)
             if len(buf) > MAX_REQUEST_LINE_BYTES + MAX_HEADER_BLOCK_BYTES:
                 raise _ReqErrorSignal(400, "invalid", False, False)
             remaining = deadline - time.monotonic()
@@
         return _ParsedRequest(
             endpoint=endpoint, query=query, token=token, body=body
         )
 
+    def _check_partial_header_block(self, buf):
+        for i, byte in enumerate(buf):
+            if byte == 0x0A:
+                if i == 0 or buf[i - 1] != 0x0D:
+                    raise _ReqErrorSignal(400, "invalid", False, False)
+            elif byte == 0x0D:
+                if i + 1 < len(buf) and buf[i + 1] != 0x0A:
+                    raise _ReqErrorSignal(400, "invalid", False, False)
+
+        first_crlf = buf.find(b"\r\n")
+        if first_crlf < 0:
+            end = len(buf)
+            if end and buf[-1] == 0x0D:
+                end -= 1
+            for b in buf[:end]:
+                if b < 0x20 or b > 0x7E:
+                    raise _ReqErrorSignal(400, "invalid", False, False)
+            if buf.endswith(b"\r"):
+                if len(buf) > MAX_REQUEST_LINE_BYTES - 1:
+                    raise _ReqErrorSignal(400, "invalid", False, False)
+            else:
+                if len(buf) > MAX_REQUEST_LINE_BYTES - 2:
+                    raise _ReqErrorSignal(400, "invalid", False, False)
+            return
+
+        if first_crlf + 2 > MAX_REQUEST_LINE_BYTES:
+            raise _ReqErrorSignal(400, "invalid", False, False)
+        target = self._parse_request_line(bytes(buf[:first_crlf]))
+        self._parse_target(target)
+        if len(buf) - (first_crlf + 2) > MAX_HEADER_BLOCK_BYTES:
+            raise _ReqErrorSignal(400, "invalid", False, False)
+        if buf.count(b"\r\n", first_crlf + 2, len(buf)) > MAX_HEADER_COUNT + 1:
+            raise _ReqErrorSignal(400, "invalid", False, False)
+
     def _parse_request_line(self, line):
         for b in line:
             if b < 0x20 or b > 0x7E:
                 raise _ReqErrorSignal(400, "invalid", False, False)
@@
         for b in cl_raw:
             if b < 0x30 or b > 0x39:
                 raise _ReqErrorSignal(400, "invalid", False, False)
-        if len(cl_raw) > _MAX_CONTENT_LENGTH_DIGITS:
-            raise _ReqErrorSignal(413, "too_large", False, False)
-        content_length = int(cl_raw)
+        cl_norm = cl_raw.lstrip(b"0") or b"0"
+        if len(cl_norm) > _MAX_CONTENT_LENGTH_DIGITS:
+            content_length = MAX_SAVE_BODY_BYTES + 1
+        else:
+            content_length = int(cl_norm)
@@
             if not chunk:
                 raise _DisconnectSignal()
             body.extend(chunk)
-            if len(body) > content_length:
-                raise _ReqErrorSignal(400, "invalid", False, False)
         return bytes(body)
```

Notes on the patch:

- Defect 1: partial header block is now bounded incrementally; bare LF/CR and overlong request-line/header/count are rejected before CRLFCRLF completion.

- Defect 2: Content-Length syntax is still 400; leading zeros are normalized; oversized values become the Step 8 413 after Content-Type and lexical Authorization checks. No invalid-payload delegation/auth semantics changed.

- Defect 3: no recv(..., need + 1) speculative over-read. The unreachable post-recv excess branch is removed only.

- Defect 4: idle slots are populated before workers/accept start; workers start before accept; close is serialized, listener wake/close is once-only, pending slot.conn handoffs are closed, and repeat/concurrent close is idempotent under one _close_lock.

## Regressions: tests/test_http_adapter.py

These assume an existing adapter fixture backed by a LocalFileService or equivalent live adapter. They are written as raw-socket probes so they exercise framing/order/close behavior directly.

```python
import socket
import threading
import time

import pytest

def _raw_exchange(adapter, payload, timeout=1.0):
    s = socket.create_connection((adapter.host, adapter.port), timeout=timeout)
    try:
        s.sendall(payload)
        s.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            try:
                chunk = s.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        s.close()

@pytest.mark.parametrize(
    "payload",
    [
        # overlong request line without CRLFCRLF
        b"POST /" + b"a" * 8200 + b" HTTP/1.1\r\n",
        # overlong header block without final CRLF
        b"POST /v1/list HTTP/1.1\r\nX-Pad: " + b"a" * 16384 + b"\r\n",
        # bare-LF header block
        b"POST /v1/list HTTP/1.1\nHost: 127.0.0.1\n\n",
    ],
)
def test_d080_partial_header_bounds_reject_early(adapter, payload):
    raw = _raw_exchange(adapter, payload)
    assert b" 400 " in raw
    assert b'"code":"invalid"' in raw
    assert b'"retry_safe":false' in raw
    assert b" 504 " not in raw

def test_d080_content_length_priority_and_leading_zeros(adapter):
    # Missing Authorization + huge Content-Length: auth check precedes size gate.
    raw = _raw_exchange(
        adapter,
        b"POST /v1/list HTTP/1.1\r\n"
        b"Host: 127.0.0.1\r\n"
        b"Content-Length: 99999999999\r\n"
        b"Content-Type: application/json\r\n\r\n",
    )
    assert b" 403 " in raw
    assert b" 413 " not in raw

    # Valid lexical Authorization + invalid Content-Type + huge Content-Length: CT before size.
    raw = _raw_exchange(
        adapter,
        b"POST /v1/list HTTP/1.1\r\n"
        b"Host: 127.0.0.1\r\n"
        b"Authorization: Bearer " + b"x" * 32 + b"\r\n"
        b"Content-Length: 99999999999\r\n"
        b"Content-Type: text/plain\r\n\r\n",
    )
    assert b" 400 " in raw
    assert b" 413 " not in raw

    # Leading zeros are normalized: 00000000002 is 2, not too_large.
    raw = _raw_exchange(
        adapter,
        b"POST /v1/list HTTP/1.1\r\n"
        b"Host: 127.0.0.1\r\n"
        b"Authorization: Bearer " + b"x" * 32 + b"\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Length: 00000000002\r\n\r\n{}",
    )
    assert b" 413 " not in raw

def test_d080_startup_six_worker_readiness(adapter):
    results = []
    barrier = threading.Barrier(6)

    def hit():
        barrier.wait()
        s = socket.create_connection((adapter.host, adapter.port), timeout=2.0)
        try:
            s.sendall(
                b"POST /v1/list HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n"
                b"Content-Length: 0\r\n"
                b"Content-Type: application/json\r\n\r\n"
            )
            s.shutdown(socket.SHUT_WR)
            results.append(s.recv(4096))
        finally:
            s.close()

    threads = [threading.Thread(target=hit) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 6
    assert not any(b" 503 " in r for r in results)

def test_d080_repeat_close_does_not_wake_released_port(adapter):
    # Occupy one worker with an incomplete request so close() cannot fully drain.
    c = socket.create_connection((adapter.host, adapter.port), timeout=2.0)
    probe = None
    try:
        c.sendall(b"POST /v1/list HTTP/1.1\r\nHost: 127.0.0.1\r\n")
        time.sleep(0.05)
        assert adapter.close(timeout=0.01) is False

        port = adapter.port
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind((adapter.host, port))
        probe.listen(1)
        probe.settimeout(0.2)

        t = threading.Thread(target=lambda: adapter.close(timeout=0.05))
        t.start()
        t.join()

        with pytest.raises(socket.timeout):
            probe.accept()
    finally:
        c.close()
        if probe is not None:
            probe.close()
```

Test provenance:

- TESTS_NOT_RUN: no execution performed in this response.

- Sarvam should run these against the integrated f304425a base with production02576d59.

- If the existing test suite uses a different adapter fixture name, map adapter to that fixture; do not change auth/schema tests pending D075.
