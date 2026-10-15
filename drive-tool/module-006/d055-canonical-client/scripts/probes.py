"""D052 independent adversarial probes for drive_tool.service_client.

Uses real tiny loopback HTTP services plus controlled transport seams.
Prints one line per probe and a summary. Exit 0 only if all probes pass.
"""
from __future__ import annotations
import http.client, http.server, json, os, socket, socketserver, sys, threading, time
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, os.environ.get("D052_TREE", "/scratch/work/candidate"))
from drive_tool.service_client import DriveClient, DriveClientError, ReadReply

TOKEN = "Ab1" + "x" * 37  # visible ASCII, len 40
ROOT = "/srv/secret-root"  # a synthetic "root" string used in redaction probes

# ---------------------------------------------------------------------------
# loopback server
# ---------------------------------------------------------------------------
class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def _go(self):
        cl = self.headers.get("Content-Length")
        body = self.rfile.read(int(cl)) if cl else b""
        rec = {"method": self.command, "path": self.path,
               "headers": {k.lower(): v for k, v in self.headers.items()},
               "raw_headers": list(self.headers.items()), "body": body}
        self.server.records.append(rec)
        self.server.responder(self, body, rec)
        self.close_connection = True
    do_POST = _go
    do_GET = _go

class _Srv(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

def start(responder):
    srv = _Srv(("127.0.0.1", 0), _Handler)
    srv.responder = responder
    srv.records = []
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    return srv, srv.server_address[1]

def send(h, status=200, body=b"", headers=(), ctype=None, declared="auto", chunked=False):
    h.send_response(status)
    if ctype: h.send_header("Content-Type", ctype)
    for k, v in headers: h.send_header(k, v)
    if chunked:
        h.send_header("Transfer-Encoding", "chunked")
    elif declared == "auto":
        h.send_header("Content-Length", str(len(body)))
    elif declared is not None:
        h.send_header("Content-Length", str(declared))
    h.end_headers()
    if chunked:
        h.wfile.write(b"%x\r\n" % len(body) + body + b"\r\n0\r\n\r\n")
    elif body:
        h.wfile.write(body)

def client(port, timeout=5.0):
    return DriveClient(port=port, token=TOKEN, timeout=timeout)

RESULTS = []
def probe(name):
    def deco(fn):
        try:
            fn()
            RESULTS.append((name, True, ""))
        except Exception as e:
            RESULTS.append((name, False, repr(e)[:200]))
        return fn
    return deco

def expect_raises(fn, exc=DriveClientError):
    try:
        fn()
    except exc as e:
        return e
    except Exception as e:
        raise AssertionError(f"wrong exception {type(e).__name__}: {e}")
    raise AssertionError("no exception raised")

# ---------------------------------------------------------------------------
# wire contract
# ---------------------------------------------------------------------------
@probe("wire.list exact path/headers/body")
def _():
    def r(h, b, rec):
        send(h, 200, json.dumps({"ok": True, "result": {"items": [], "next_offset": None}}).encode(), ctype="application/json")
    srv, port = start(r)
    out = client(port).list("src1", "root", limit=5, offset=2)
    assert out == {"items": [], "next_offset": None}, out
    rec = srv.records[0]
    assert rec["method"] == "POST", rec["method"]
    assert rec["path"] == "/v1/list", rec["path"]
    H = rec["headers"]
    assert H["content-type"] == "application/json", H
    assert H["authorization"] == "Bearer " + TOKEN, H
    assert H["connection"].lower() == "close", H
    assert int(H["content-length"]) == len(rec["body"]), H
    assert json.loads(rec["body"]) == {"source_id": "src1", "file_id": "root", "limit": 5, "offset": 2}, rec["body"]
    assert "name_contains" not in json.loads(rec["body"]), "name_contains should be omitted when None"
    srv.shutdown()

@probe("wire.list includes name_contains when given")
def _():
    def r(h, b, rec): send(h, 200, b'{"ok":true,"result":{}}', ctype="application/json")
    srv, port = start(r); client(port).list("s", name_contains="ab")
    assert json.loads(srv.records[0]["body"])["name_contains"] == "ab"
    srv.shutdown()

@probe("wire.find exact keys")
def _():
    def r(h, b, rec): send(h, 200, b'{"ok":true,"result":{}}', ctype="application/json")
    srv, port = start(r); client(port).find("s", "root", name_contains="x", limit=7, max_entries=9, max_depth=3)
    body = json.loads(srv.records[0]["body"])
    assert body == {"source_id": "s", "file_id": "root", "name_contains": "x", "limit": 7, "max_entries": 9, "max_depth": 3}, body
    assert srv.records[0]["path"] == "/v1/find"
    srv.shutdown()

@probe("wire.read exact keys")
def _():
    def r(h, b, rec):
        send(h, 200, b"abc", headers=[("X-Drive-Offset","10"),("X-Drive-Observed-Size","100"),
             ("X-Drive-Observed-Mtime-Ns","5"),("X-Drive-EOF-Observed","false")],
             ctype="application/octet-stream")
    srv, port = start(r); rep = client(port).read("s", "p/a.txt", offset=10, length=3)
    assert isinstance(rep, ReadReply) and rep.data == b"abc" and rep.offset == 10, rep
    assert json.loads(srv.records[0]["body"]) == {"source_id":"s","file_id":"p/a.txt","offset":10,"length":3}
    assert srv.records[0]["path"] == "/v1/read"
    srv.shutdown()

@probe("wire.save query urlencoded + octet-stream body")
def _():
    def r(h, b, rec): send(h, 200, b'{"ok":true,"result":{"bytes_written":3}}', ctype="application/json")
    srv, port = start(r)
    out = client(port).save("s", "p/a b.txt", b"\x00\x01\x02", overwrite=True, create_parents=False)
    rec = srv.records[0]
    u = urlsplit(rec["path"])
    assert u.path == "/v1/save", u.path
    q = parse_qs(u.query)
    assert q["source_id"] == ["s"] and q["file_id"] == ["p/a b.txt"], q
    assert q["overwrite"] == ["true"] and q["create_parents"] == ["false"], q
    assert rec["headers"]["content-type"] == "application/octet-stream"
    assert rec["body"] == b"\x00\x01\x02"
    assert rec["headers"]["authorization"] == "Bearer " + TOKEN
    assert "authorization" not in rec["path"].lower() and TOKEN not in rec["path"]
    assert out == {"bytes_written": 3}
    srv.shutdown()

# ---------------------------------------------------------------------------
# bounded replies
# ---------------------------------------------------------------------------
@probe("bounded declared CL over cap fails before body read")
def _():
    def r(h, b, rec):
        h.send_response(200); h.send_header("Content-Type","application/json")
        h.send_header("Content-Length", "999999"); h.end_headers()  # no body
    srv, port = start(r)
    expect_raises(lambda: client(port).list("s"))
    srv.shutdown()

@probe("bounded missing CL (chunked) exactly cap ok")
def _():
    body = json.dumps({"ok": True, "result": {"n": 1}}).encode()
    def r(h, b, rec): send(h, 200, body, ctype="application/json", chunked=True)
    srv, port = start(r)
    assert client(port).list("s") == {"n": 1}
    srv.shutdown()

@probe("bounded chunked cap+1 excess fails")
def _():
    big = b"{" + b" " * 70000 + b"}"
    def r(h, b, rec): send(h, 200, big, ctype="application/json", chunked=True)
    srv, port = start(r)
    expect_raises(lambda: client(port).list("s"))
    srv.shutdown()

@probe("bounded error body over cap fails")
def _():
    big = b"x" * 70000
    def r(h, b, rec): send(h, 400, big, ctype="application/json", chunked=True)
    srv, port = start(r)
    expect_raises(lambda: client(port).list("s"))
    srv.shutdown()

@probe("bounded read declared CL over request fails before read")
def _():
    def r(h, b, rec):
        h.send_response(200); h.send_header("Content-Type","application/octet-stream")
        for k,v in [("X-Drive-Offset","0"),("X-Drive-Observed-Size","9999"),("X-Drive-Observed-Mtime-Ns","1"),("X-Drive-EOF-Observed","false")]:
            h.send_header(k,v)
        h.send_header("Content-Length","999999"); h.end_headers()
    srv, port = start(r)
    expect_raises(lambda: client(port).read("s","p/a",offset=0,length=4))
    srv.shutdown()

# ---------------------------------------------------------------------------
# read header semantics
# ---------------------------------------------------------------------------
def _read_headers(extra, data=b"abc", status=200, ctype="application/octet-stream", declared="auto", chunked=False, drop=()):
    base = [("X-Drive-Offset","0"),("X-Drive-Observed-Size","3"),("X-Drive-Observed-Mtime-Ns","1"),("X-Drive-EOF-Observed","true")]
    base = [(k,v) for k,v in base if k not in drop]
    hdrs = base + list(extra)
    def r(h, b, rec):
        send(h, status, data, headers=hdrs, ctype=ctype, declared=declared, chunked=chunked)
    return start(r)

@probe("read duplicate offset header fails closed")
def _():
    srv, port = _read_headers([("X-Drive-Offset","0")])
    expect_raises(lambda: client(port).read("s","p/a",length=3)); srv.shutdown()

@probe("read malformed decimal header fails closed")
def _():
    srv, port = _read_headers([("X-Drive-Observed-Size","12x")], drop=("X-Drive-Observed-Size",))
    expect_raises(lambda: client(port).read("s","p/a",length=3)); srv.shutdown()

@probe("read invalid eof token fails closed")
def _():
    srv, port = _read_headers([("X-Drive-EOF-Observed","yes")])
    expect_raises(lambda: client(port).read("s","p/a",length=3)); srv.shutdown()

@probe("read wrong content-type fails closed")
def _():
    srv, port = _read_headers([], ctype="text/plain")
    expect_raises(lambda: client(port).read("s","p/a",length=3)); srv.shutdown()

@probe("read missing header fails closed")
def _():
    srv, port = _read_headers([], drop=("X-Drive-Observed-Mtime-Ns",))
    expect_raises(lambda: client(port).read("s","p/a",length=3)); srv.shutdown()

@probe("read offset mismatch fails closed")
def _():
    srv, port = _read_headers([("X-Drive-Offset","5")])
    expect_raises(lambda: client(port).read("s","p/a",offset=0,length=3)); srv.shutdown()

@probe("read short window without eof fails closed")
def _():
    srv, port = _read_headers([("X-Drive-EOF-Observed","false")], data=b"ab")
    expect_raises(lambda: client(port).read("s","p/a",length=3)); srv.shutdown()

@probe("read exact fill with eof fails closed")
def _():
    srv, port = _read_headers([("X-Drive-EOF-Observed","true")], data=b"abc")
    expect_raises(lambda: client(port).read("s","p/a",length=3)); srv.shutdown()

@probe("read short window with eof ok (short content)")
def _():
    srv, port = _read_headers([], data=b"ab")
    rep = client(port).read("s","p/a",length=3)
    assert rep.data == b"ab" and rep.eof_observed is True, rep
    srv.shutdown()

@probe("read stale observed_size under growth allowed")
def _():
    # observed_size(3) < offset(0)+len(data)(5): must be allowed (growth)
    srv, port = _read_headers([("X-Drive-Observed-Size","3"),("X-Drive-EOF-Observed","false")], drop=("X-Drive-Observed-Size","X-Drive-EOF-Observed"), data=b"abcde")
    rep = client(port).read("s","p/a",length=5)
    assert rep.data == b"abcde" and rep.observed_size == 3, rep
    srv.shutdown()

@probe("read bytes exceed requested length fails")
def _():
    srv, port = _read_headers([], data=b"abcdef", declared=None, chunked=True)
    expect_raises(lambda: client(port).read("s","p/a",length=3)); srv.shutdown()

@probe("truncated chunked read body does not leak a raw exception")
def _():
    def r(h, b, rec):
        h.send_response(200); h.send_header("Content-Type","application/octet-stream")
        for k,v in [("X-Drive-Offset","0"),("X-Drive-Observed-Size","10"),("X-Drive-Observed-Mtime-Ns","1"),("X-Drive-EOF-Observed","false")]:
            h.send_header(k,v)
        h.send_header("Transfer-Encoding","chunked"); h.end_headers()
        h.wfile.write(b"a\r\nabc\r\n")   # claims 10 bytes, delivers 3, then closes
        h.close_connection = True
    srv, port = start(r)
    # must surface as a DriveClientError, never a raw http.client.IncompleteRead
    try:
        client(port).read("s","p/a",length=8)
        raise AssertionError("expected DriveClientError")
    except DriveClientError:
        pass
    srv.shutdown()

# ---------------------------------------------------------------------------
# JSON / error envelopes
# ---------------------------------------------------------------------------
@probe("success malformed JSON -> unavailable")
def _():
    srv, port = start(lambda h,b,r: send(h,200,b"{not json",ctype="application/json"))
    e = expect_raises(lambda: client(port).list("s"))
    assert e.code == "unavailable" and e.outcome_uncertain is False and e.retry_safe is True
    srv.shutdown()

@probe("success ok!=true -> unavailable")
def _():
    srv, port = start(lambda h,b,r: send(h,200,b'{"ok":false,"result":{}}',ctype="application/json"))
    assert expect_raises(lambda: client(port).list("s")).code == "unavailable"
    srv.shutdown()

@probe("known error codes recognized")
def _():
    for code in ["invalid","denied","not_found","exists","too_large","busy","unavailable","timeout"]:
        body = json.dumps({"ok":False,"error":{"code":code,"outcome_uncertain":False,"retry_safe":True}}).encode()
        srv, port = start(lambda h,b,r,body=body: send(h,400,body,ctype="application/json"))
        e = expect_raises(lambda: client(port).list("s"))
        assert e.code == code, (code, e.code)
        srv.shutdown()

@probe("unknown code -> unavailable")
def _():
    body = json.dumps({"ok":False,"error":{"code":"weird","outcome_uncertain":False,"retry_safe":True}}).encode()
    srv, port = start(lambda h,b,r: send(h,500,body,ctype="application/json"))
    assert expect_raises(lambda: client(port).list("s")).code == "unavailable"
    srv.shutdown()

@probe("ok:true on non-200 -> unavailable")
def _():
    srv, port = start(lambda h,b,r: send(h,500,b'{"ok":true,"result":{}}',ctype="application/json"))
    assert expect_raises(lambda: client(port).list("s")).code == "unavailable"
    srv.shutdown()

@probe("save unknown reply -> uncertain, not retry-safe")
def _():
    srv, port = start(lambda h,b,r: send(h,500,b'garbage',ctype="application/json"))
    e = expect_raises(lambda: client(port).save("s","p/a",b"x"))
    assert e.outcome_uncertain is True and e.retry_safe is False, (e.outcome_uncertain, e.retry_safe)
    srv.shutdown()

@probe("save transport failure (refused) -> uncertain, not retry-safe")
def _():
    # pick a port with no listener
    s = socket.socket(); s.bind(("127.0.0.1",0)); dead = s.getsockname()[1]; s.close()
    e = expect_raises(lambda: client(dead).save("s","p/a",b"x"))
    assert e.outcome_uncertain is True and e.retry_safe is False, (e.outcome_uncertain, e.retry_safe)

@probe("read transport failure -> uncertain False, retry-safe True")
def _():
    s = socket.socket(); s.bind(("127.0.0.1",0)); dead = s.getsockname()[1]; s.close()
    e = expect_raises(lambda: client(dead).read("s","p/a"))
    assert e.outcome_uncertain is False and e.retry_safe is True

@probe("no automatic retry on save (exactly one request)")
def _():
    srv, port = start(lambda h,b,r: send(h,500,b'{"ok":false,"error":{"code":"busy"}}',ctype="application/json"))
    expect_raises(lambda: client(port).save("s","p/a",b"x"))
    time.sleep(0.2)
    assert len(srv.records) == 1, len(srv.records)
    srv.shutdown()

@probe("no automatic retry on read (exactly one request)")
def _():
    srv, port = start(lambda h,b,r: send(h,500,b'{"ok":false,"error":{"code":"busy"}}',ctype="application/json"))
    expect_raises(lambda: client(port).read("s","p/a"))
    time.sleep(0.2)
    assert len(srv.records) == 1, len(srv.records)
    srv.shutdown()

# ---------------------------------------------------------------------------
# redaction
# ---------------------------------------------------------------------------
@probe("redaction: token/root/remote text never leak")
def _():
    evil = json.dumps({"ok":False,"error":{"code":"denied","outcome_uncertain":False,
        "retry_safe":True,"message":"boom " + TOKEN + " root=" + ROOT}}).encode()
    srv, port = start(lambda h,b,r: send(h,403,evil,ctype="application/json"))
    e = expect_raises(lambda: client(port).save("s","p/a",b"x"))
    text = str(e) + repr(e) + "".join(getattr(e,"args",()))
    assert TOKEN not in text, "token leaked"
    assert ROOT not in text, "root leaked"
    assert "boom" not in text, "remote message leaked"
    assert e.code == "denied"
    srv.shutdown()

@probe("redaction: repr of client hides token")
def _():
    c = client(12345)
    assert TOKEN not in repr(c), repr(c)
    assert "redacted" in repr(c).lower()

# ---------------------------------------------------------------------------
# seams: validation before network, close-on-exception, per-call connections
# ---------------------------------------------------------------------------
class _FakeResp:
    def __init__(self, status=200, body=b'{"ok":true,"result":{}}', headers=None, ctype="application/json", raise_on_read=False):
        self.status = status; self._body = body; self._ctype = ctype
        self._h = {k: [v] for k, v in (headers or {}).items()}; self._raise = raise_on_read; self.closed = False
    def getheader(self, name, default=None):
        if name.lower() == "content-length": return str(len(self._body))
        if name.lower() == "content-type": return self._ctype
        return self._h.get(name, default)
    @property
    def headers(self):
        outer = self
        class H:
            def get_all(self, name): return outer._h.get(name)
        return H()
    def read(self, n=None):
        if self._raise: raise AssertionError("read called after failure")
        return self._body
    def close(self): self.closed = True

class _FakeConn:
    def __init__(self, resp=None, raise_on_request=False):
        self.resp = resp; self.closed = False; self.requests = []
        self._raise = raise_on_request
    def request(self, *a, **k):
        self.requests.append((a, k))
        if self._raise: raise ConnectionResetError("boom")
    def getresponse(self): return self.resp
    def close(self): self.closed = True

class _Seam(DriveClient):
    def __init__(self, *a, conn_factory=None, **k):
        super().__init__(*a, **k)
        self._opens = []
        self._factory = conn_factory or (lambda: _FakeConn(_FakeResp()))
    def _open(self):
        c = self._factory(); self._opens.append(c); return c

@probe("invalid options before any socket (list/find/read/save)")
def _():
    c = _Seam(port=1, token=TOKEN)
    bad = [
        lambda: c.list(""), lambda: c.list("s", file_id=""),
        lambda: c.list("s", limit=0), lambda: c.list("s", limit=101),
        lambda: c.list("s", offset=-1), lambda: c.list("s", name_contains=5),
        lambda: c.find("s", name_contains=""), lambda: c.find("s", name_contains=None),
        lambda: c.find("s", name_contains="x", max_entries=0),
        lambda: c.find("s", name_contains="x", max_depth=65),
        lambda: c.read("s", "root"), lambda: c.read("s", "p/a", length=0),
        lambda: c.read("s", "p/a", length=1048577), lambda: c.read("s", "p/a", offset=-1),
        lambda: c.read("s", "/abs"), lambda: c.read("s", "p/../a"),
        lambda: c.save("s", "root", b"x"), lambda: c.save("s", "p/a", "notbytes"),
        lambda: c.save("s", "p/a", b"x", overwrite=1), lambda: c.save("s", "p/a", b"x"*1048577),
    ]
    for fn in bad:
        try:
            fn(); raise AssertionError("expected TypeError/ValueError")
        except (TypeError, ValueError):
            pass
    assert c._opens == [], f"network opened for invalid args: {len(c._opens)}"

@probe("constructor invalid before network")
def _():
    for k in [dict(port=0,token=TOKEN), dict(port=True,token=TOKEN), dict(port=1,token="short"),
              dict(port=1,token="a"*31), dict(port=1,token="a"*257), dict(port=1,token="a"*31+"\n"),
              dict(port=1,token=TOKEN,timeout=0), dict(port=1,token=TOKEN,timeout=float("nan"))]:
        try:
            DriveClient(**k); raise AssertionError(f"accepted {k}")
        except (TypeError, ValueError):
            pass

@probe("connection + response closed on success")
def _():
    resp = _FakeResp()
    conn = _FakeConn(resp)
    c = _Seam(port=1, token=TOKEN, conn_factory=lambda: conn)
    c.list("s")
    assert conn.closed and resp.closed, (conn.closed, resp.closed)

@probe("connection + response closed on transport error")
def _():
    conn = _FakeConn(raise_on_request=True)
    c = _Seam(port=1, token=TOKEN, conn_factory=lambda: conn)
    expect_raises(lambda: c.read("s","p/a"))
    assert conn.closed, "conn not closed on error"

@probe("connection + response closed on protocol error")
def _():
    resp = _FakeResp(status=500, body=b"notjson", ctype="application/json")
    conn = _FakeConn(resp)
    c = _Seam(port=1, token=TOKEN, conn_factory=lambda: conn)
    expect_raises(lambda: c.list("s"))
    assert conn.closed and resp.closed

@probe("new connection per call (no reuse)")
def _():
    c = _Seam(port=1, token=TOKEN)
    c.list("s"); c.find("s", name_contains="x"); c.save("s","p/a",b"x")
    assert len(c._opens) == 3, len(c._opens)
    assert len(set(id(x) for x in c._opens)) == 3

@probe("cap+1 read via seam argument")
def _():
    seen = {}
    class R(_FakeResp):
        def read(self, n=None): seen["n"] = n; return b'{"ok":true,"result":{}}'
    conn = _FakeConn(R())
    c = _Seam(port=1, token=TOKEN, conn_factory=lambda: conn)
    c.list("s")
    assert seen["n"] == 65537, seen  # _MAX_JSON_BODY + 1

@probe("read bounded read uses length+1")
def _():
    seen = {}
    class R(_FakeResp):
        def __init__(self): super().__init__(status=200, body=b"abc", ctype="application/octet-stream",
            headers={"X-Drive-Offset":"0","X-Drive-Observed-Size":"3","X-Drive-Observed-Mtime-Ns":"1","X-Drive-EOF-Observed":"false"})
        def read(self, n=None): seen["n"] = n; return b"abc"
    conn = _FakeConn(R())
    c = _Seam(port=1, token=TOKEN, conn_factory=lambda: conn)
    c.read("s","p/a",length=3)
    assert seen["n"] == 4, seen

# ---------------------------------------------------------------------------
# redirects + concurrency
# ---------------------------------------------------------------------------
@probe("redirect not followed")
def _():
    hit = {"n": 0}
    def r(h, b, rec):
        if rec["path"] == "/v1/list":
            h.send_response(302); h.send_header("Location","/elsewhere"); h.send_header("Content-Length","0"); h.end_headers()
        else:
            hit["n"] += 1; send(h, 200, b'{"ok":true,"result":{}}', ctype="application/json")
    srv, port = start(r)
    expect_raises(lambda: client(port).list("s"))
    time.sleep(0.2)
    assert hit["n"] == 0, "followed redirect"
    srv.shutdown()

@probe("concurrent independent requests")
def _():
    def r(h, b, rec):
        src = json.loads(rec["body"])["source_id"]
        send(h, 200, json.dumps({"ok":True,"result":{"src":src}}).encode(), ctype="application/json")
    srv, port = start(r)
    out = {}
    def worker(i):
        out[i] = client(port).list(f"src{i}")
    ts = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert out == {i: {"src": f"src{i}"} for i in range(12)}, out
    srv.shutdown()

if __name__ == "__main__":
    npass = sum(1 for _, ok, _ in RESULTS if ok)
    for name, ok, det in RESULTS:
        print(("PASS " if ok else "FAIL ") + name + (("  :: " + det) if det else ""))
    print(f"\n{len(RESULTS)} probes, {npass} passed, {len(RESULTS)-npass} failed")
    raise SystemExit(0 if npass == len(RESULTS) else 1)
