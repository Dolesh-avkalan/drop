"""D088: does the adapter itself ever emit a 503 `unavailable`?

Instruments the adapter's error-emission seams (runtime only; no source change)
and drives the D085 gate call shape, so the server-side emission tally can be
compared with the client-side code tally.  A client-side `unavailable` with no
matching server emission is a transport fallback, not a structured 503.
"""
import collections
import json
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, ".")
import tests.test_http_adapter as T
import drive_tool.http_adapter as HA
from drive_tool.http_adapter import DriveHTTPAdapter
from drive_tool.service_client import DriveClient, DriveClientError

CALLS = int(sys.argv[1]) if len(sys.argv) > 1 else 1200
CONC = int(sys.argv[2]) if len(sys.argv) > 2 else 6

emitted = collections.Counter()
busy_rejects = collections.Counter()
write_errors = collections.Counter()

_orig_safe = DriveHTTPAdapter._safe_send_error


def safe(self, conn, status, code, unc, retry):
    emitted[(status, code, bool(unc), bool(retry))] += 1
    try:
        return _orig_safe(self, conn, status, code, unc, retry)
    except Exception as e:  # noqa: BLE001
        write_errors[type(e).__name__] += 1
        raise


_orig_busy = DriveHTTPAdapter._busy_reject


def busy(self, conn):
    busy_rejects["count"] += 1
    return _orig_busy(self, conn)


DriveHTTPAdapter._safe_send_error = safe
DriveHTTPAdapter._busy_reject = busy

AGENTS = list(T._SOAK_AGENTS)
LABEL = {tok: "agent%d" % i for i, (tok, _s) in enumerate(AGENTS)}
OPS = ("list", "find", "read", "save")


def op_for(i):
    r = i % 10
    return "list" if r < 3 else "find" if r < 5 else "read" if r < 8 else "save"


base = tempfile.mkdtemp(prefix="d088-emit-")
policies, roots = T._standard_policies(base)
a = DriveHTTPAdapter(policies, port=0, socket_timeout=5.0)
time.sleep(0.1)
client_codes = collections.Counter()
rows = []
lock = threading.Lock()


def worker(w):
    local = collections.Counter()
    local_rows = []
    for i in range(w, CALLS, CONC):
        token, source = AGENTS[i % len(AGENTS)]
        op = op_for(i)
        try:
            c = DriveClient(port=a.port, token=token, timeout=5.0)
            if op == "list":
                c.list(source, limit=20)
            elif op == "find":
                c.find(source, name_contains="data", limit=10)
            elif op == "read":
                c.read(source, "p/readme.txt", length=64)
            else:
                c.save(source, "p/savepool/s%02d.bin" % (i % 32), b"x" * 8,
                       overwrite=True)
            local["ok"] += 1
        except DriveClientError as e:
            local[e.code] += 1
            if e.code == "unavailable":
                local_rows.append({"i": i, "agent": LABEL[token], "source": source,
                                   "op": op, "code": e.code,
                                   "uncertain": e.outcome_uncertain,
                                   "retry": e.retry_safe})
        except Exception as e:  # noqa: BLE001
            local["exc:" + type(e).__name__] += 1
    with lock:
        client_codes.update(local)
        rows.extend(local_rows)


ts = [threading.Thread(target=worker, args=(w,)) for w in range(CONC)]
t0 = time.monotonic()
for t in ts:
    t.start()
for t in ts:
    t.join(timeout=280)
el = time.monotonic() - t0
closed = a.close(timeout=10.0)

print("calls=%d concurrency=%d wall=%.2fs closed=%s" % (CALLS, CONC, el, closed))
print("SERVER emissions (status, code, uncertain, retry) -> count:")
for k, v in sorted(emitted.items()):
    print("   %s -> %d" % (k, v))
print("SERVER busy_reject calls:", dict(busy_rejects))
print("SERVER write errors:", dict(write_errors))
print("CLIENT codes:", dict(client_codes))
print("CLIENT unavailable rows:", len(rows))
for r in rows:
    print("   ", json.dumps(r, sort_keys=True))
disk = {al: len(os.listdir(os.path.join(r, "savepool")))
        if os.path.isdir(os.path.join(r, "savepool")) else 0
        for al, r in sorted(roots.items())}
print("disk files per source (savepool):", disk, "total", sum(disk.values()))
import shutil
shutil.rmtree(base, ignore_errors=True)
