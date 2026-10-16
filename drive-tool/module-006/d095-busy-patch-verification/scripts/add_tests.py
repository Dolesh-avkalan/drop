path = "tests/test_http_adapter.py"
src = open(path, encoding="utf-8").read()
done = []

def sub(name, old, new, count=1):
    global src
    n = src.count(old)
    assert n == count, "hunk %s: expected %d, found %d" % (name, count, n)
    src = src.replace(old, new, count)
    done.append(name)

# --- constants join the harness import, fallback and frozen contract table ---
sub("import", '''        ACCEPT_POLL_INTERVAL_SECONDS, BUSY_REJECT_BUDGET_SECONDS,
        DEFAULT_DRAIN_TIMEOUT_SECONDS, DEFAULT_SOCKET_TIMEOUT_SECONDS,''',
    '''        ACCEPT_POLL_INTERVAL_SECONDS, BUSY_POST_DRAIN_BUDGET_SECONDS,
        BUSY_PRE_READ_BUDGET_SECONDS, BUSY_REJECT_BUDGET_SECONDS,
        BUSY_WRITE_RESERVE_SECONDS, DEFAULT_DRAIN_TIMEOUT_SECONDS,
        DEFAULT_SOCKET_TIMEOUT_SECONDS,''')

sub("fallback", '''    BUSY_REJECT_BUDGET_SECONDS = 0.05
    MAX_BUSY_READ_BYTES = 16384''', '''    BUSY_REJECT_BUDGET_SECONDS = 0.050
    BUSY_PRE_READ_BUDGET_SECONDS = 0.010
    BUSY_WRITE_RESERVE_SECONDS = 0.020
    BUSY_POST_DRAIN_BUDGET_SECONDS = 0.020
    MAX_BUSY_READ_BYTES = 16384''')

sub("contract", '''    "ACCEPT_POLL_INTERVAL_SECONDS": 0.05, "BUSY_REJECT_BUDGET_SECONDS": 0.05,
    "MAX_BUSY_READ_BYTES": 16384, "POST_RESPONSE_DRAIN_SECONDS": 0.05,''',
    '''    "ACCEPT_POLL_INTERVAL_SECONDS": 0.05, "BUSY_REJECT_BUDGET_SECONDS": 0.050,
    "BUSY_PRE_READ_BUDGET_SECONDS": 0.010, "BUSY_WRITE_RESERVE_SECONDS": 0.020,
    "BUSY_POST_DRAIN_BUDGET_SECONDS": 0.020,
    "MAX_BUSY_READ_BYTES": 16384, "POST_RESPONSE_DRAIN_SECONDS": 0.05,''')

anchor = 'if __name__ == "__main__":\n    unittest.main()\n'
assert src.count(anchor) == 1

BLOCK = '''# ---------------------------------------------------------------------------
# D094 busy-phase budget regressions.
#
# Translated from the D094 example regression (written against an imagined
# ``server``/``Server``) onto this harness and the real
# ``drive_tool.http_adapter`` / ``DriveHTTPAdapter``.  Fully deterministic: a fake
# monotonic clock and a fake socket, no network and no pytest dependency.
#
# The defect under test is that the pre-read used the whole outer budget, so a
# peer that sends nothing consumed all 50 ms and the 503 busy write was never
# attempted -- the client then saw a transport reset (unavailable) instead of a
# busy envelope.  The phase split reserves a write window.

from unittest import mock as _mock


class _FakeClock:
    def __init__(self):
        self.t = 1000.0

    def monotonic(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class _FakeConn:
    def __init__(self, clock, chunks=None, recv_advance=None,
                 timeout_on_empty=False, endless=False):
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


@unittest.skipUnless(_ADAPTER_AVAILABLE, _SKIP_REASON)
class BusyPhaseBudgetTests(unittest.TestCase):
    def setUp(self):
        import drive_tool.http_adapter as _ha
        self.ha = _ha
        self.clock = _FakeClock()
        patcher = _mock.patch.object(_ha.time, "monotonic", self.clock.monotonic)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.adapter = object.__new__(_ha.DriveHTTPAdapter)

        def send_with_deadline(conn, data, deadline):
            now = _ha.time.monotonic()
            if now >= deadline:
                return False
            conn.settimeout(max(0.0, deadline - now))
            conn.send(data)
            return True

        self.adapter._send_with_deadline = send_with_deadline

    def _elapsed(self):
        return self.clock.t - 1000.0

    def test_delayed_payload_pre_read_cannot_starve_busy_write(self):
        conn = _FakeConn(self.clock, timeout_on_empty=True)
        self.adapter._busy_reject(conn)
        self.assertGreater(len(conn.sent), 0,
                           "503 write must be attempted after the bounded pre-read")
        self.assertIn(b"503 Service Unavailable", conn.sent)
        self.assertIn(b\'"code":"busy"\', conn.sent)
        self.assertLessEqual(self._elapsed(),
                             self.ha.BUSY_REJECT_BUDGET_SECONDS + 0.001)

    def test_total_read_and_deadline_caps(self):
        conn = _FakeConn(self.clock, chunks=[b"x" * 4096] * 10, recv_advance=0.001)
        self.adapter._busy_reject(conn)
        self.assertLessEqual(conn.total_read, self.ha.MAX_BUSY_READ_BYTES)
        self.assertLessEqual(self._elapsed(),
                             self.ha.BUSY_REJECT_BUDGET_SECONDS + 0.001)

    def test_post_drain_is_bounded(self):
        conn = _FakeConn(self.clock, endless=True, recv_advance=0.005)
        self.adapter._busy_reject(conn)
        self.assertLessEqual(self._elapsed(),
                             self.ha.BUSY_REJECT_BUDGET_SECONDS + 0.001)
        self.assertLessEqual(conn.total_read, self.ha.MAX_BUSY_READ_BYTES)

    def test_busy_envelope_is_not_unavailable(self):
        conn = _FakeConn(self.clock, timeout_on_empty=True)
        self.adapter._busy_reject(conn)
        sent_lower = bytes(conn.sent).lower()
        self.assertIn(b\'"outcome_uncertain":false\', sent_lower)
        self.assertIn(b\'"retry_safe":true\', sent_lower)
        self.assertNotIn(b"unavailable", sent_lower)

    def test_phase_constants_are_frozen(self):
        self.assertEqual(self.ha.BUSY_REJECT_BUDGET_SECONDS, 0.050)
        self.assertEqual(self.ha.BUSY_PRE_READ_BUDGET_SECONDS, 0.010)
        self.assertEqual(self.ha.BUSY_WRITE_RESERVE_SECONDS, 0.020)
        self.assertEqual(self.ha.BUSY_POST_DRAIN_BUDGET_SECONDS, 0.020)
        self.assertEqual(self.ha.MAX_BUSY_READ_BYTES, 16384)
        self.assertEqual(self.ha.MAX_IN_FLIGHT_OPERATIONS, 6)
        self.assertEqual(self.ha.POST_RESPONSE_DRAIN_SECONDS, 0.05)
        self.assertLessEqual(
            self.ha.BUSY_PRE_READ_BUDGET_SECONDS + self.ha.BUSY_WRITE_RESERVE_SECONDS,
            self.ha.BUSY_REJECT_BUDGET_SECONDS)


'''
open(path, "w", encoding="utf-8").write(src.replace(anchor, BLOCK + anchor))
print("applied:", done)
