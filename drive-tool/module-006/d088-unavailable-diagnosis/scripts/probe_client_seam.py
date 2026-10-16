"""D088: attribute the client-side `unavailable` to a concrete seam.

Instruments drive_tool.service_client._wrap_transport and _parse_error_envelope
(runtime only) and drives the D085 gate call shape, so each client `unavailable`
can be attributed to a transport exception type or to an unparseable reply.
"""
import collections
import json
import sys
import tempfile
import threading
import time

sys.path.insert(0, ".")
import tests.test_http_adapter as T
import drive_tool.service_client as SC
from drive_tool.http_adapter import DriveHTTPAdapter
from drive_tool.service_client import DriveClient, DriveClientError

CALLS = int(sys.argv[1]) if len(sys.argv) > 1 else 1200
CONC = int(sys.argv[2]) if len(sys.argv) > 2 else 6

transport = collections.Counter()
envelope_fallback = collections.Counter()
orig_wrap = SC._wrap_transport
orig_env = SC._parse_error_envelope


def wrap(exc, *, write_op):
    transport[type(exc).__name__] += 1
    return orig_wrap(exc, write_op=write_op)


def env(raw, *, write_op):
    r = orig_env(raw, write_op=write_op)
    if r.code == "unavailable":
        envelope_fallback["empty" if not raw else "nonempty"] += 1
    return r


SC._wrap_transport = wrap
SC._parse_error_envelope = env

AGENTS = list(T._SOAK_AGENTS)
LABEL = {tok: "agent%d" % i for i, (tok, _s) in enumerate(AGENTS)}
OPS = ("list", "find", "read", "save")


def op_for(i):
    r = i % 10
    return "list" if r < 3 else "find" if r < 5 else "read" if r < 8 else "save"


base = tempfile.mkdtemp(prefix="d088-seam-")
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
print("_wrap_transport exception types:", dict(transport))
print("_parse_error_envelope -> unavailable (raw empty/nonempty):", dict(envelope_fallback))
print("unavailable rows (%d):" % len(rows))
for r in rows:
    print("   ", json.dumps(r, sort_keys=True))
import shutil
shutil.rmtree(base, ignore_errors=True)
