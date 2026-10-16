"""D088 bounded per-call diagnosis of unexpected HTTP `unavailable` responses.

Diagnostic only: no production or test change, no gate relabelling.

Mirrors the D085 gate workload (same six soak agents, same op mix by index % 10,
same client concurrency) but drives each call over a raw loopback socket so the
wire response can be classified:

  structured_error   HTTP status + a JSON error envelope with a known code
  structured_success HTTP status + {"ok": true, ...}
  no_bytes           the peer closed without emitting anything (teardown)
  unparsed           bytes arrived but no valid envelope (malformed reply)
  transport_error    the exchange itself raised (reset / timeout)

Usage: probe_unavailable_detail.py [calls] [concurrency] [mode]
  mode = raw (default) | client
Token strings are never printed; agents appear as agent0..agent5.
"""
import collections
import json
import socket
import sys
import tempfile
import threading
import time
import hashlib

sys.path.insert(0, ".")
import tests.test_http_adapter as T
from drive_tool.http_adapter import DriveHTTPAdapter

CALLS = int(sys.argv[1]) if len(sys.argv) > 1 else 1200
CONC = int(sys.argv[2]) if len(sys.argv) > 2 else 6
MODE = sys.argv[3] if len(sys.argv) > 3 else "raw"

AGENTS = list(T._SOAK_AGENTS)
LABEL = {tok: "agent%d" % i for i, (tok, _s) in enumerate(AGENTS)}

# Expected grants, derived from the same policy table the adapter uses.
_GRANTS = {}
for _p in T._standard_policies(tempfile.mkdtemp(prefix="d088-grants-"))[0]:
    _GRANTS[_p.token_sha256] = {g.alias: set(g.operations) for g in _p.grants}


def expected_grant(token, source, op):
    grants = _GRANTS.get(hashlib.sha256(token.encode("ascii")).digest(), {})
    return op in grants.get(source, set())


OPS = ("list", "find", "read", "save")


def op_for(i):
    roll = i % 10
    if roll < 3:
        return "list"
    if roll < 5:
        return "find"
    if roll < 8:
        return "read"
    return "save"


def build(i, token, source):
    """Same request shapes DriveClient emits (Connection: close, fresh socket)."""
    op = op_for(i)
    if op == "list":
        body = T._jb({"source_id": source, "file_id": "root", "limit": 20, "offset": 0})
        return op, T._json_req("/v1/list", {"source_id": source, "file_id": "root",
                                            "limit": 20, "offset": 0}, token), len(body)
    if op == "find":
        payload = {"source_id": source, "file_id": "root", "name_contains": "data",
                   "limit": 10, "max_entries": 2000, "max_depth": 4}
        return op, T._json_req("/v1/find", payload, token), len(T._jb(payload))
    if op == "read":
        payload = {"source_id": source, "file_id": "p/readme.txt", "offset": 0,
                   "length": 64}
        return op, T._json_req("/v1/read", payload, token), len(T._jb(payload))
    q = ("source_id=%s&file_id=p%%2Fsavepool%%2Fs%02d.bin&overwrite=true"
         "&create_parents=true" % (source, i % 32))
    return op, T._save_req(q, b"x" * 8, token), 8


def classify(raw, exc, status, code, op=None, ctype=None):
    if exc is not None:
        return "transport_error"
    if not raw:
        return "no_bytes"
    if status is None:
        return "unparsed"
    if status == 200 and ctype and "octet-stream" in ctype:
        return "structured_success"   # binary /v1/read reply
    try:
        obj = json.loads(raw.split(b"\r\n\r\n", 1)[1].decode("utf-8"))
    except Exception:  # noqa: BLE001
        return "unparsed"
    if not isinstance(obj, dict):
        return "unparsed"
    if obj.get("ok") is True:
        return "structured_success"
    if obj.get("ok") is False and isinstance(obj.get("error"), dict):
        return "structured_error"
    return "unparsed"


def one_call(a, i, token, source):
    op, raw_req, blen = build(i, token, source)
    rec = {"i": i, "agent": LABEL[token], "source": source, "op": op,
           "expected_grant": expected_grant(token, source, op), "body_len": blen}
    exc = None
    raw = b""
    status = code = None
    unc = retry = None
    if MODE == "raw":
        try:
            raw = T._exchange(a.port, raw_req)
        except Exception as e:  # noqa: BLE001
            exc = type(e).__name__
        if raw:
            status, _h, body = T._parse(raw)
            _ctype = _h.get("content-type", "")
            if status is not None:
                try:
                    obj = json.loads(body.decode("utf-8"))
                    if obj.get("ok") is False and isinstance(obj.get("error"), dict):
                        code = obj["error"].get("code")
                        unc = obj["error"].get("outcome_uncertain")
                        retry = obj["error"].get("retry_safe")
                except Exception:  # noqa: BLE001
                    pass
    else:
        from drive_tool.service_client import DriveClient, DriveClientError
        try:
            c = DriveClient(port=a.port, token=token, timeout=5.0)
            getattr(c, op)(source, **({"limit": 20} if op == "list"
                                      else {"name_contains": "data", "limit": 10}
                                      if op == "find"
                                      else {"file_id": "p/readme.txt", "length": 64}
                                      if op == "read"
                                      else {"file_id": "p/savepool/s%02d.bin" % (i % 32),
                                            "data": b"x" * 8, "overwrite": True}))
            status = 200
        except DriveClientError as e:
            code = e.code
            unc = e.outcome_uncertain
            retry = e.retry_safe
            status = -1
        except Exception as e:  # noqa: BLE001
            exc = type(e).__name__
    rec.update({"status": status, "code": code, "uncertain": unc, "retry": retry,
                "class": classify(raw, exc, status, code, op, _ctype) if MODE == "raw"
                else ("client_error" if status == -1 else "client_success")})
    return rec


def main():
    base = tempfile.mkdtemp(prefix="d088-diag-")
    policies, roots = T._standard_policies(base)
    a = DriveHTTPAdapter(policies, port=0, socket_timeout=5.0)
    time.sleep(0.1)
    records = []
    lock = threading.Lock()

    def worker(w):
        local = []
        for i in range(w, CALLS, CONC):
            token, source = AGENTS[i % len(AGENTS)]
            local.append(one_call(a, i, token, source))
        with lock:
            records.extend(local)

    ts = [threading.Thread(target=worker, args=(w,)) for w in range(CONC)]
    t0 = time.monotonic()
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=280)
    elapsed = time.monotonic() - t0
    closed = a.close(timeout=10.0)
    records.sort(key=lambda r: r["i"])

    classes = collections.Counter(r["class"] for r in records)
    codes = collections.Counter(r["code"] for r in records if r["code"])
    ops = collections.Counter(r["op"] for r in records)
    print("mode=%s calls=%d concurrency=%d wall=%.2fs closed=%s" %
          (MODE, len(records), CONC, elapsed, closed))
    print("classes:", dict(classes))
    print("codes:", dict(codes))
    print("ops:", dict(ops))

    interesting = [r for r in records
                   if r["class"] in ("structured_error", "no_bytes", "unparsed",
                                     "transport_error")
                   or (r["code"] not in (None, "denied"))]
    print("non-2xx / non-denied rows: %d" % len(interesting))
    for r in interesting:
        print("  ", json.dumps(r, sort_keys=True))

    # actual disk state after the saves
    disk = {}
    for alias, root in sorted(roots.items()):
        pool = os.path.join(root, "savepool")
        files = sorted(os.listdir(pool)) if os.path.isdir(pool) else []
        disk[alias] = len(files)
    print("disk files per source root (savepool):", disk)
    print("total files:", sum(disk.values()))

    import shutil
    shutil.rmtree(base, ignore_errors=True)


import os  # noqa: E402
main()
