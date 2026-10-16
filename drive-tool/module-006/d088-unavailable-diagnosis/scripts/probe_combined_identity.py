"""D088 decisive combined diagnostic.

Instruments, in one process and one 1200-call run:
  * the adapter's admission seam  (_busy_reject)  -> server-side busy count
  * the adapter's error seam      (_safe_send_error) -> every structured emission
  * the client's transport seam   (_wrap_transport)  -> exception type per failure
  * the client's envelope seam    (_parse_error_envelope) -> fallback hits

so that, when a client `unavailable` appears, it can be attributed in the same
run: structured 503 from the adapter, an unparseable reply, or a transport reset.
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
import drive_tool.service_client as SC
from drive_tool.http_adapter import DriveHTTPAdapter
from drive_tool.service_client import DriveClient, DriveClientError

CALLS = int(sys.argv[1]) if len(sys.argv) > 1 else 1200
CONC = int(sys.argv[2]) if len(sys.argv) > 2 else 6

emitted = collections.Counter()
busy_rejects = collections.Counter()
transport = collections.Counter()
env_fallback = collections.Counter()

_o_safe = DriveHTTPAdapter._safe_send_error
_o_busy = DriveHTTPAdapter._busy_reject
_o_wrap = SC._wrap_transport
_o_env = SC._parse_error_envelope


def safe(self, conn, status, code, unc, retry):
    emitted[(status, code)] += 1
    return _o_safe(self, conn, status, code, unc, retry)


def busy(self, conn):
    busy_rejects["count"] += 1
    return _o_busy(self, conn)


def wrap(exc, *, write_op):
    transport[type(exc).__name__] += 1
    return _o_wrap(exc, write_op=write_op)


def env(raw, *, write_op):
    r = _o_env(raw, write_op=write_op)
    if r.code == "unavailable":
        env_fallback["empty" if not raw else "nonempty"] += 1
    return r


DriveHTTPAdapter._safe_send_error = safe
DriveHTTPAdapter._busy_reject = busy
SC._wrap_transport = wrap
SC._parse_error_envelope = env

AGENTS = list(T._SOAK_AGENTS)
LABEL = {tok: "agent%d" % i for i, (tok, _s) in enumerate(AGENTS)}


def op_for(i):
    r = i % 10
    return "list" if r < 3 else "find" if r < 5 else "read" if r < 8 else "save"


base = tempfile.mkdtemp(prefix="d088-comb-")
policies, roots = T._standard_policies(base)
a = DriveHTTPAdapter(policies, port=0, socket_timeout=5.0)
time.sleep(0.1)
codes = collections.Counter()
rows = []
lock = threading.Lock()


def worker(w):
    local = collections.Counter()
    lr = []
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
                c.save(source, "p/savepool/s%02d.bin" % (i % 32), b"x" * 8, overwrite=True)
            local["ok"] += 1
        except DriveClientError as e:
            local[e.code] += 1
            if e.code == "unavailable":
                lr.append({"i": i, "agent": LABEL[token], "source": source, "op": op,
                           "uncertain": e.outcome_uncertain, "retry": e.retry_safe})
    with lock:
        codes.update(local)
        rows.extend(lr)


ts = [threading.Thread(target=worker, args=(w,)) for w in range(CONC)]
t0 = time.monotonic()
for t in ts:
    t.start()
for t in ts:
    t.join(timeout=280)
el = time.monotonic() - t0
closed = a.close(timeout=10.0)

print("calls=%d concurrency=%d wall=%.2fs closed=%s" % (CALLS, CONC, el, closed))
print("CLIENT codes:", dict(codes))
print("SERVER structured emissions:", {str(k): v for k, v in sorted(emitted.items())})
print("SERVER _busy_reject calls:", dict(busy_rejects))
print("CLIENT _wrap_transport exception types:", dict(transport))
print("CLIENT envelope->unavailable fallback:", dict(env_fallback))
cb = codes.get("busy", 0)
cu = codes.get("unavailable", 0)
print("IDENTITY busy_reject == client_busy + client_unavailable: %d == %d + %d -> %s"
      % (busy_rejects.get("count", 0), cb, cu,
         busy_rejects.get("count", 0) == cb + cu))
print("unavailable rows (%d):" % len(rows))
for r in rows:
    print("   ", json.dumps(r, sort_keys=True))
disk = {al: (len(os.listdir(os.path.join(r, "savepool")))
             if os.path.isdir(os.path.join(r, "savepool")) else 0)
        for al, r in sorted(roots.items())}
print("disk files per source (savepool):", disk, "total", sum(disk.values()))
import shutil
shutil.rmtree(base, ignore_errors=True)
