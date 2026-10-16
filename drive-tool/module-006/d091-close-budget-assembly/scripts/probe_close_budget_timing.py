"""D091 timing probe: a contended close() must honour its own budget.

Builds a bare adapter with a service whose close() parks, starts a long first
close, then times a second close(timeout=0.05) taken while the first still holds
the lock.  Prints the raw elapsed and the returned value.
"""
import sys
import threading
import time

sys.path.insert(0, ".")
from drive_tool.http_adapter import DriveHTTPAdapter


class BlockingService:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.close_calls = 0

    def close(self, *, timeout):
        self.close_calls += 1
        self.entered.set()
        self.release.wait(timeout=5.0)
        return True


def bare(service):
    a = DriveHTTPAdapter.__new__(DriveHTTPAdapter)
    a._close_lock = threading.Lock()
    a._closed = False
    a._listener_closed = False
    a._draining = False
    a._pool_cond = threading.Condition()
    a._slots = []
    a._listener = None
    a._accept_thread = None
    a._workers = []
    a._service = service
    a._port = 0
    return a


svc = BlockingService()
adapter = bare(svc)
first_result = []
first = threading.Thread(target=lambda: first_result.append(adapter.close(timeout=5.0)),
                         daemon=True)
first.start()
print("first close reached the service lease:", svc.entered.wait(timeout=1.0))
t0 = time.monotonic()
second = adapter.close(timeout=0.05)
elapsed = time.monotonic() - t0
print("contended close(timeout=0.05) -> %r in %.4fs (budget 0.05s + 0.10s margin = 0.15s)"
      % (second, elapsed))
print("service.close calls during the contended close:", svc.close_calls)
svc.release.set()
first.join(timeout=6.0)
print("first close returned:", first_result, "alive:", first.is_alive())
print("adapter._closed:", adapter._closed)
print("service.close calls total:", svc.close_calls)
print("idempotent follow-up close(timeout=0.1) ->", adapter.close(timeout=0.1))
print("VERDICT:", "PASS" if (second is False and elapsed < 0.15 and svc.close_calls == 1)
      else "FAIL")
