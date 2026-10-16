path = "tests/test_http_adapter.py"
src = open(path, encoding="utf-8").read()
anchor = 'if __name__ == "__main__":\n    unittest.main()\n'
assert src.count(anchor) == 1, "anchor not unique"

BLOCK = '''# ---------------------------------------------------------------------------
# D087 close()-budget regressions.
#
# Translated from the D087 example regression (which was a pytest module with a
# bare adapter built via __new__) into this existing unittest harness.  The
# assertions are preserved and extended with the properties D091 asks for: the
# contended caller honours its own budget within a documented scheduler margin,
# the failed close touches no active descriptor, the lock is released exactly
# once, close is idempotent afterwards, and no thread leaks.


class _BlockingService:
    """Minimal service whose close() blocks until it is released."""

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.close_calls = 0

    def close(self, *, timeout):
        self.close_calls += 1
        self.entered.set()
        self.release.wait(timeout=5.0)
        return True


class _Slot:
    """One worker slot, matching the adapter's internal shape."""

    __slots__ = ("conn", "thread")

    def __init__(self, conn=None):
        self.conn = conn
        self.thread = None


def _bare_adapter(service, slots=()):
    """A DriveHTTPAdapter with no listener or threads, for close()-only tests.

    ``_port`` stays 0 so the adapter's own ``_wake_listener`` short-circuits.
    """
    a = DriveHTTPAdapter.__new__(DriveHTTPAdapter)
    a._close_lock = threading.Lock()
    a._closed = False
    a._listener_closed = False
    a._draining = False
    a._pool_cond = threading.Condition()
    a._slots = list(slots)
    a._listener = None
    a._accept_thread = None
    a._workers = []
    a._service = service
    a._port = 0
    return a


@unittest.skipUnless(_ADAPTER_AVAILABLE, _SKIP_REASON)
class CloseBudgetTests(unittest.TestCase):
    def _contend(self, slots=()):
        service = _BlockingService()
        adapter = _bare_adapter(service, slots=slots)
        first_result = []
        first = threading.Thread(
            target=lambda: first_result.append(adapter.close(timeout=5.0)),
            daemon=True,
        )
        first.start()
        self.assertTrue(service.entered.wait(timeout=1.0),
                        "first close never reached the service lease")
        return adapter, service, first, first_result

    def test_second_close_honors_deadline_while_first_holds_lock(self):
        adapter, service, first, first_result = self._contend()
        try:
            started = time.monotonic()
            second_result = adapter.close(timeout=0.05)
            elapsed = time.monotonic() - started
            # budget 0.05s plus a 0.10s documented scheduler margin
            self.assertIs(second_result, False)
            self.assertLess(elapsed, 0.05 + 0.10, elapsed)
            self.assertEqual(service.close_calls, 1)
            service.release.set()
            first.join(timeout=1.0)
            self.assertFalse(first.is_alive())
            self.assertEqual(first_result, [True])
            self.assertIs(adapter._closed, True)
            self.assertEqual(service.close_calls, 1)
            # idempotent afterwards, with no further service lease
            self.assertIs(adapter.close(timeout=0.1), True)
            self.assertEqual(service.close_calls, 1)
        finally:
            service.release.set()
            first.join(timeout=5.0)

    def test_contended_close_leaves_active_descriptors_untouched(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        adapter, service, first, first_result = self._contend(slots=(_Slot(left),))
        threads_before = threading.active_count()
        try:
            self.assertIs(adapter.close(timeout=0.05), False)
            # the contended close returned without entering the critical section:
            # the handed-off connection is neither closed nor cleared
            self.assertIs(adapter._slots[0].conn, left)
            self.assertNotEqual(left.fileno(), -1)
            right.sendall(b"ping")
            self.assertEqual(left.recv(4), b"ping")
        finally:
            service.release.set()
            first.join(timeout=5.0)
        # once the winner completes it does close the pending handoff, and no
        # thread is left behind
        self.assertIsNone(adapter._slots[0].conn)
        self.assertLessEqual(threading.active_count(), threads_before)
        self.assertIs(adapter.close(timeout=0.1), True)

    def test_lock_is_released_once_and_close_is_idempotent(self):
        adapter, service, first, first_result = self._contend()
        try:
            self.assertIs(adapter.close(timeout=0.05), False)
            service.release.set()
            first.join(timeout=1.0)
            self.assertEqual(first_result, [True])
            self.assertTrue(adapter._close_lock.acquire(blocking=False),
                            "close lock was not released")
            adapter._close_lock.release()
            for _ in range(3):
                self.assertIs(adapter.close(timeout=0.05), True)
            self.assertEqual(service.close_calls, 1)
        finally:
            service.release.set()
            first.join(timeout=5.0)


'''
open(path, "w", encoding="utf-8").write(src.replace(anchor, BLOCK + anchor))
print("appended CloseBudgetTests")
