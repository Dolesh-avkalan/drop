"""D088: does teardown produce the structured 503 `unavailable`?

Small, clearly-labelled diagnostic (not a gate run).  Holds N calls inside the
service, then closes the adapter while they are in flight, and records what the
client sees and what the adapter emits.
"""
import collections
import json
import sys
import tempfile
import threading
import time

sys.path.insert(0, ".")
import tests.test_http_adapter as T
import drive_tool.http_adapter as HA
from drive_tool.http_adapter import DriveHTTPAdapter
from drive_tool.service_client import DriveClient, DriveClientError

N = int(sys.argv[1]) if len(sys.argv) > 1 else 3
emitted = collections.Counter()
_orig = DriveHTTPAdapter._safe_send_error


def safe(self, conn, status, code, unc, retry):
    emitted[(status, code, bool(unc), bool(retry))] += 1
    return _orig(self, conn, status, code, unc, retry)


DriveHTTPAdapter._safe_send_error = safe

base = tempfile.mkdtemp(prefix="d088-teardown-")
policies, _roots = T._standard_policies(base)
svc = T.InstrumentedService(policies)
a = DriveHTTPAdapter(service=svc, port=0, socket_timeout=5.0)
svc.block = True
svc.block_target = N
svc.block_timeout = 10.0
results = []
lock = threading.Lock()


def call(i):
    try:
        DriveClient(port=a.port, token=T._MAIN_TOKEN, timeout=5.0).list("main", limit=5)
        with lock:
            results.append({"i": i, "code": "ok"})
    except DriveClientError as e:
        with lock:
            results.append({"i": i, "code": e.code,
                            "uncertain": e.outcome_uncertain, "retry": e.retry_safe})
    except Exception as e:  # noqa: BLE001
        with lock:
            results.append({"i": i, "code": "exc:" + type(e).__name__})


ts = [threading.Thread(target=call, args=(i,)) for i in range(N)]
for t in ts:
    t.start()
print("gate entered:", svc.entered.wait(timeout=5.0))
r = a.close(timeout=0.2)
print("close(timeout=0.2) ->", r)
svc.release_gate()
for t in ts:
    t.join(timeout=10)
print("close(timeout=5.0) ->", a.close(timeout=5.0))
print("SERVER emissions:", {str(k): v for k, v in sorted(emitted.items())})
print("CLIENT results:", json.dumps(sorted(results, key=lambda x: x["i"])))
import shutil
shutil.rmtree(base, ignore_errors=True)
