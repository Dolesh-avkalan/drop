"""D085 minimal repro: busy rejections under the fixed 600-call smoke shape.

Reproduces the smoke failure and varies only the client concurrency, so the
busy count can be attributed.  No production change is made or proposed here.
"""
import collections
import socket
import sys
import tempfile
import threading
import time

sys.path.insert(0, ".")
import tests.test_http_adapter as T
from drive_tool.http_adapter import DriveHTTPAdapter
from drive_tool.service_client import DriveClient, DriveClientError


def run(concurrency, calls=600, agents=((T._MAIN_TOKEN, "main"),)):
    base = tempfile.mkdtemp(prefix="d085-busy-")
    policies, _r = T._standard_policies(base)
    a = DriveHTTPAdapter(policies, port=0, socket_timeout=5.0)
    time.sleep(0.1)
    counts = collections.Counter()
    lock = threading.Lock()

    def worker(w):
        local = collections.Counter()
        for i in range(w, calls, concurrency):
            token, source_id = agents[i % len(agents)]
            client = DriveClient(port=a.port, token=token, timeout=5.0)
            local[T._mixed_call(client, source_id, i)] += 1
        with lock:
            counts.update(local)

    ts = [threading.Thread(target=worker, args=(w,)) for w in range(concurrency)]
    t0 = time.monotonic()
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=120)
    el = time.monotonic() - t0
    a.close(timeout=10.0)
    busy = counts.get("err:busy", 0)
    print("concurrency=%d calls=%d busy=%d total=%d seconds=%.2f other_errors=%s"
          % (concurrency, calls, busy, sum(counts.values()), el,
             {k: v for k, v in counts.items() if k.startswith("err:") and k != "err:busy"}))
    import shutil
    shutil.rmtree(base, ignore_errors=True)
    return busy


for c in (4, 5, 6):
    run(c)
