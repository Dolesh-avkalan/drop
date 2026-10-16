# d094 (deepseek)

- status: done
- chat: https://chat.deepseek.com/a/chat/s/880b80b8-1cdf-4dcb-9dc5-e8503c6ae44a
- model: deepseek (deepthink on, search off)
- finished: 2026-10-16T01:12:58Z

## Question

DeepSeek, surgical busyphasebudget patch+unittestregression perGeminiD092/D094. Exactb962a04d preservesclosebudget. No auth/architecturechanges, no imaginaryguarantees. TESTS_NOT_RUN unlessactualevidence; Sarvamassembles, GeminiDelta. No merge/deploy.

(input files: Dolesh-avkalan/drive-tool:tasks/d094-busy-reject-patch.txt@3b2fccc2338470394d246d129e393320d1afb3a2)

## Answer

D094 static patch proposal — TESTS_NOT_RUN

Scope honored: surgical _busy_reject phase-budget patch only. No auth/schema/header semantics change, no architecture change, no queues/threads/FS on reject path, no OS/TCP guarantee claimed. The 20 ms write reserve is a program-budget allocation inside the existing 50 ms / 16 KiB ceiling. BUSY_REJECT_BUDGET_SECONDS total close budget is preserved as the outer deadline.

No actual execution performed here. Sarvam must assemble/run; Gemini reviews delta. No merge/deploy/real roots.

## 1. Constants patch

Apply near existing BUSY_REJECT_BUDGET_SECONDS / MAX_BUSY_READ_BYTES:

```python
BUSY_REJECT_BUDGET_SECONDS = 0.050
BUSY_PRE_READ_BUDGET_SECONDS = 0.010
BUSY_WRITE_RESERVE_SECONDS = 0.020
BUSY_POST_DRAIN_BUDGET_SECONDS = 0.020
MAX_BUSY_READ_BYTES = 16384
```

## 2. _busy_reject replacement

Replace the monolithic pre-read / write / drain body with this exact phase logic. Keep existing response/header bytes if they already match this envelope; the important part is the deadline partition.

```python
    def _busy_reject(self, conn):
        now = time.monotonic()
        busy_deadline = now + BUSY_REJECT_BUDGET_SECONDS
        total_read = 0

        # Phase 1: bounded pre-read. Must not consume the reserved write slice.
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

        # Phase 2: reserved write window inside the same 50ms outer ceiling.
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

        # Phase 3: bounded post-write drain; never exceeds 16 KiB or outer deadline.
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

## 3. Unittest regression file

tests/test_d094_busy_phase_budget.py

This is deterministic: fake monotonic clock, fake socket, no network, no pytest fixtures. It tests the actual _busy_reject phase logic with a minimal _send_with_deadline stub that respects the passed deadline. The old monolithic pre-read would consume the full 50 ms, so the write attempt would be skipped; the new phase split must still write the 503 busy envelope.

```python
import importlib
import os
import socket
import unittest
from unittest import mock

# Sarvam: set env if the real module/class names differ.
_SERVER_MODULE = os.environ.get("DRIVE_TOOL_SERVER_MODULE", "server")
_SERVER_CLASS = os.environ.get("DRIVE_TOOL_SERVER_CLASS", "Server")
server = importlib.import_module(_SERVER_MODULE)
Server = getattr(server, _SERVER_CLASS)

class _Clock:
    def __init__(self):
        self.t = 1000.0

    def monotonic(self):
        return self.t

    def advance(self, dt):
        self.t += dt

class _FakeConn:
    def __init__(
        self,
        clock,
        chunks=None,
        recv_advance=None,
        timeout_on_empty=False,
        endless=False,
    ):
        self.clock = clock
        self.chunks = list(chunks or [])
        self.recv_advance = recv_advance
        self.timeout_on_empty = timeout_on_empty
        self.endless = endless
        self.timeout = None
        self.sent = bytearray()
        self.total_read = 0
        self.closed = False
        self.shutdown_called = False
        self.recv_calls = 0

    def settimeout(self, t):
        self.timeout = t

    def recv(self, n):
        self.recv_calls += 1
        if self.timeout is None:
            raise socket.timeout()

        advance = self.recv_advance if self.recv_advance is not None else self.timeout
        self.clock.advance(advance)

        if self.endless:
            chunk = b"x"
            self.total_read += len(chunk)
            return chunk

        if self.chunks:
            chunk = self.chunks.pop(0)
            if chunk:
                chunk = chunk[:n]
                self.total_read += len(chunk)
                return chunk

        if self.timeout_on_empty:
            raise socket.timeout()
        return b""

    def send(self, data):
        self.sent.extend(data)
        return len(data)

    def shutdown(self, how):
        self.shutdown_called = True

    def close(self):
        self.closed = True

class TestD094BusyPhaseBudget(unittest.TestCase):
    def setUp(self):
        self.clock = _Clock()
        patcher = mock.patch.object(server.time, "monotonic", self.clock.monotonic)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.srv = object.__new__(Server)

        def send_with_deadline(conn, data, deadline):
            now = server.time.monotonic()
            if now >= deadline:
                return False
            conn.settimeout(max(0.0, deadline - now))
            conn.send(data)
            return True

        self.srv._send_with_deadline = send_with_deadline

    def _elapsed(self):
        return self.clock.t - 1000.0

    def test_delayed_payload_pre_read_cannot_starve_busy_write(self):
        conn = _FakeConn(self.clock, timeout_on_empty=True)
        self.srv._busy_reject(conn)

        self.assertGreater(
            len(conn.sent),
            0,
            "503 write must be attempted after bounded pre-read",
        )
        self.assertIn(b"503 Service Unavailable", conn.sent)
        self.assertIn(b'"code":"busy"', conn.sent)
        self.assertLessEqual(
            self._elapsed(),
            server.BUSY_REJECT_BUDGET_SECONDS + 0.001,
        )

    def test_total_read_and_deadline_caps(self):
        conn = _FakeConn(
            self.clock,
            chunks=[b"x" * 4096] * 10,
            recv_advance=0.001,
        )
        self.srv._busy_reject(conn)

        self.assertLessEqual(conn.total_read, server.MAX_BUSY_READ_BYTES)
        self.assertLessEqual(
            self._elapsed(),
            server.BUSY_REJECT_BUDGET_SECONDS + 0.001,
        )

    def test_post_drain_is_bounded(self):
        conn = _FakeConn(self.clock, endless=True, recv_advance=0.005)
        self.srv._busy_reject(conn)

        self.assertLessEqual(
            self._elapsed(),
            server.BUSY_REJECT_BUDGET_SECONDS + 0.001,
        )
        self.assertLessEqual(conn.total_read, server.MAX_BUSY_READ_BYTES)

    def test_busy_envelope_is_not_unavailable(self):
        conn = _FakeConn(self.clock, timeout_on_empty=True)
        self.srv._busy_reject(conn)

        sent_lower = bytes(conn.sent).lower()
        self.assertIn(b'"outcome_uncertain":false', sent_lower)
        self.assertIn(b'"retry_safe":true', sent_lower)
        self.assertNotIn(b"unavailable", sent_lower)

if __name__ == "__main__":
    unittest.main()
```

## 4. Status / handoff

- Patch: surgical constants + _busy_reject phase deadlines only.

- Regression: unittest-compatible, fake clock/socket, deterministic old-fail/new-pass intent for delayed-payload accept gap.

- Close budget: outer BUSY_REJECT_BUDGET_SECONDS remains total program budget; no added close wait.

- Guarantees: none beyond bounded program loops; adverse/oversized/stalled peers remain best-effort at TCP/kernel boundary.

- TESTS_NOT_RUN here unless actual execution evidence is provided.

- Sarvam assembles/tests; Gemini reviews delta. No merge/deploy/real roots.
