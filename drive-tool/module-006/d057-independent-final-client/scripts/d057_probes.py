"""D057 independent adversarial probes for drive_tool.service_client.

Written fresh for D057 (not the D052/D055 builder probe scripts). Uses real tiny
loopback HTTP services plus controlled transport seams. One line per probe; exit
0 only if all pass. This exercises a simulated HTTP service, NOT the real Drive
service.
"""
from __future__ import annotations
import http.client, http.server, json, os, socket, socketserver, sys, threading, time
from urllib.parse import parse_qs, urlsplit

TREE = os.environ.get("D057_TREE", "/scratch/work/candidate")
sys.path.insert(0, TREE)
from drive_tool.service_client import DriveClient, DriveClientError, ReadReply

TOKEN = "Zx9" + "q" * 37          # 40 visible ASCII
ROOT = "/srv/real-root-secret"     # synthetic root string for redaction probes


class _H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def _go(self):
        cl = self.headers.get("Content-Length")
        body = self.rfile.read(int(cl)) if cl else b""
        rec = {"method": self.command, "path": self.path,
               "headers": {k.lower(): v for k, v in self.headers.items()},
               "body": body}
        self.server.records.append(rec)
        self.server.responder(self, body, rec)
        self.close_connection = True
    do_POST = _go


class _Srv(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def start(responder):
    srv = _Srv(("127.0.0.1", 0), _H)
    srv.responder = responder
    srv.records = []
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def send(h, status=200, body=b"", headers=(), ctype=None, declared="auto", chunked=False):
    h.send_response(status)
    if ctype: h.send_header("Content-Type", ctype)
    for k, v in headers: h.send_header(k, v)
    if chunked: h.send_header("Transfer-Encoding", "chunked")
    elif declared == "auto": h.send_header("Content-Length", str(len(body)))
    elif declared is not None: h.send_header("Content-Length", str(declared))
    h.end_headers()
    if chunked: h.wfile.write(b"%x\r\n" % len(body) + body + b"\r\n0\r\n\r\n")
    elif body: h.wfile.write(body)


def client(port, timeout=5.0): return DriveClient(port=port, token=TOKEN, timeout=timeout)
def dead_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

R = []
def probe(name):
    def deco(fn):
        try:
            fn(); R.append((name, True, ""))
        except Exception as e:
            R.append((name, False, repr(e)[:220]))
        return fn
    return deco

def raises(fn, exc=DriveClientError):
    try: fn()
    except exc as e: return e
    except Exception as e: raise AssertionError(f"wrong exc {type(e).__name__}: {e}")
    raise AssertionError("no exception")


# ---------------------------------------------------------------------------
# 1. canonical prefix enforcement BEFORE any socket
# ---------------------------------------------------------------------------
class _Resp:
    def __init__(self, status=200, body=b'{"ok":true,"result":{}}', ctype="application/json", headers=None):
        self.status = status; self._b = body; self._c = ctype
        self._h = {k: [v] for k, v in (headers or {}).items()}; self.closed = False
    def getheader(self, n, d=None):
        if n.lower() == "content-length": return str(len(self._b))
        if n.lower() == "content-type": return self._c
        return self._h.get(n, d)
    @property
    def headers(self):
        o = self
        class H:
            def get_all(self, n): return o._h.get(n)
        return H()
    def read(self, n=None): return self._b
    def close(self): self.closed = True

class _Conn:
    def __init__(self, resp=None): self.resp = resp; self.closed = False; self.requests = []
    def request(self, *a, **k): self.requests.append((a, k))
    def getresponse(self): return self.resp
    def close(self): self.closed = True

class _Seam(DriveClient):
    def __init__(self, *a, **k):
        super().__init__(*a, **k); self._opens = []
    def _open(self):
        c = _Conn(_Resp()); self._opens.append(c); return c

BAD_IDS = ["a.txt", "docs/x", "p", "p/", "p//x", "p/../x", "p/./x", "/abs", "p/a\\b", "p/a\x00b"]

@probe("prefix: malformed/nonprefixed ids rejected before any socket (all 4 ops)")
def _():
    c = _Seam(port=1, token=TOKEN)
    for fid in BAD_IDS:
        for fn in (lambda f=fid: c.read("src", f),
                   lambda f=fid: c.save("src", f, b"x"),
                   lambda f=fid: c.list("src", f),
                   lambda f=fid: c.find("src", f, name_contains="x")):
            try:
                fn(); raise AssertionError(f"accepted bad id {fid!r}")
            except ValueError:
                pass
    assert c._opens == [], f"socket opened for invalid id: {len(c._opens)}"

@probe("prefix: bare 'p' and 'p/' rejected (nonempty canonical suffix required)")
def _():
    c = _Seam(port=1, token=TOKEN)
    for fid in ("p", "p/"):
        try: c.read("src", fid); raise AssertionError(f"accepted {fid!r}")
        except ValueError: pass
    assert c._opens == []

@probe("prefix: root allowed only for list/find, rejected for read/save")
def _():
    c = _Seam(port=1, token=TOKEN)
    for fn in (lambda: c.read("src", "root"), lambda: c.save("src", "root", b"x")):
        try: fn(); raise AssertionError("root accepted for read/save")
        except ValueError: pass
    assert c._opens == []
    # list/find accept root
    for op in (lambda: c.list("src", "root"), lambda: c.find("src", "root", name_contains="x")):
        op()
    assert len(c._opens) == 2

@probe("prefix: NUL rejected even when it would look prefixed")
def _():
    c = _Seam(port=1, token=TOKEN)
    try: c.read("src", "p/a\x00b"); raise AssertionError("NUL accepted")
    except ValueError: pass
    assert c._opens == []


# ---------------------------------------------------------------------------
# 2. valid ids transmitted unchanged (spaces / plus)
# ---------------------------------------------------------------------------
@probe("wire: list JSON body carries canonical id verbatim (space+plus)")
def _():
    def r(h, b, rec): send(h, 200, b'{"ok":true,"result":{}}', ctype="application/json")
    srv, port = start(r)
    client(port).list("src", "p/a b+c.txt")
    assert json.loads(srv.records[0]["body"])["file_id"] == "p/a b+c.txt"
    srv.shutdown()

@probe("wire: read JSON body carries canonical id verbatim")
def _():
    def r(h, b, rec):
        send(h, 200, b"ab", headers=[("X-Drive-Offset","0"),("X-Drive-Observed-Size","2"),
             ("X-Drive-Observed-Mtime-Ns","1"),("X-Drive-EOF-Observed","true")],
             ctype="application/octet-stream")
    srv, port = start(r)
    client(port).read("src", "p/a b+c.txt", length=4)
    assert json.loads(srv.records[0]["body"])["file_id"] == "p/a b+c.txt"
    srv.shutdown()

@probe("wire: save query round-trips canonical id with space and plus")
def _():
    def r(h, b, rec): send(h, 200, b'{"ok":true,"result":{}}', ctype="application/json")
    srv, port = start(r)
    client(port).save("src", "p/a b+c.txt", b"x")
    q = parse_qs(urlsplit(srv.records[0]["path"]).query)
    assert q["file_id"] == ["p/a b+c.txt"], q
    assert srv.records[0]["path"].startswith("/v1/save?"), srv.records[0]["path"]
    srv.shutdown()


# ---------------------------------------------------------------------------
# 3. duplicate / malformed observation headers fail closed (actual stdlib)
# ---------------------------------------------------------------------------
def read_headers(extra, data=b"abc", status=200, ctype="application/octet-stream",
                 declared="auto", chunked=False, drop=()):
    base = [("X-Drive-Offset","0"),("X-Drive-Observed-Size","3"),
            ("X-Drive-Observed-Mtime-Ns","1"),("X-Drive-EOF-Observed","true")]
    base = [(k,v) for k,v in base if k not in drop]
    def r(h, b, rec): send(h, status, data, headers=base+list(extra), ctype=ctype, declared=declared, chunked=chunked)
    return start(r)

@probe("dup header: duplicate X-Drive-Offset fails closed")
def _():
    srv, port = read_headers([("X-Drive-Offset","0")])
    raises(lambda: client(port).read("src","p/a",length=3)); srv.shutdown()

@probe("dup header: duplicate X-Drive-EOF-Observed fails closed")
def _():
    srv, port = read_headers([("X-Drive-EOF-Observed","false")])
    raises(lambda: client(port).read("src","p/a",length=3)); srv.shutdown()

@probe("dup header: duplicate X-Drive-Observed-Size fails closed")
def _():
    srv, port = read_headers([("X-Drive-Observed-Size","3")])
    raises(lambda: client(port).read("src","p/a",length=3)); srv.shutdown()

@probe("dup header: stdlib get_all returns 2 values (raw behaviour check)")
def _():
    srv, port = read_headers([("X-Drive-Offset","0")])
    # confirm the actual stdlib parse yields two values, so the client's
    # len(values)!=1 guard is what fails it closed
    raw = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    raw.request("POST", "/v1/read", body=b"{}", headers={"Content-Type":"application/json","Content-Length":"2"})
    resp = raw.getresponse()
    vals = resp.headers.get_all("X-Drive-Offset")
    raw.close(); srv.shutdown()
    assert vals is not None and len(vals) == 2, f"stdlib returned {vals!r}"

@probe("dup header: malformed decimal observation header fails closed")
def _():
    srv, port = read_headers([("X-Drive-Observed-Mtime-Ns","12x")], drop=("X-Drive-Observed-Mtime-Ns",))
    raises(lambda: client(port).read("src","p/a",length=3)); srv.shutdown()

@probe("dup header: missing observation header fails closed")
def _():
    srv, port = read_headers([], drop=("X-Drive-Observed-Size",))
    raises(lambda: client(port).read("src","p/a",length=3)); srv.shutdown()

@probe("dup header: duplicate Content-Length reported (actual stdlib behaviour)")
def _():
    # send two Content-Length headers; record what http.client does and that the
    # client still fails closed or stays bounded (never reads unbounded)
    def r(h, b, rec):
        h.send_response(200); h.send_header("Content-Type","application/json")
        h.send_header("Content-Length","7"); h.send_header("Content-Length","7"); h.end_headers()
        h.wfile.write(b'{"ok":true,"result":{}}')
    srv, port = start(r)
    note = []
    try:
        client(port).list("src"); note.append("accepted")
    except DriveClientError: note.append("DriveClientError")
    except Exception as e: note.append("raw:"+type(e).__name__)
    srv.shutdown()
    print("      [note] duplicate Content-Length ->", note[0])


# ---------------------------------------------------------------------------
# 4. hostile body: truncated chunk + mid-body stall
# ---------------------------------------------------------------------------
@probe("hostile: truncated chunked read body -> safe error, read False/True")
def _():
    def r(h, b, rec):
        h.send_response(200); h.send_header("Content-Type","application/octet-stream")
        for k,v in [("X-Drive-Offset","0"),("X-Drive-Observed-Size","10"),("X-Drive-Observed-Mtime-Ns","1"),("X-Drive-EOF-Observed","false")]:
            h.send_header(k,v)
        h.send_header("Transfer-Encoding","chunked"); h.end_headers()
        h.wfile.write(b"a\r\nabc\r\n")   # declares 10, delivers 3, then closes
        h.close_connection = True
    srv, port = start(r)
    e = raises(lambda: client(port).read("src","p/a",length=8))
    assert type(e) is DriveClientError, type(e)
    assert e.code in ("unavailable","timeout"), e.code
    assert e.outcome_uncertain is False and e.retry_safe is True, (e.outcome_uncertain, e.retry_safe)
    srv.shutdown()

@probe("hostile: truncated chunked save body -> uncertain True/False")
def _():
    def r(h, b, rec):
        h.send_response(200); h.send_header("Content-Type","application/json")
        h.send_header("Transfer-Encoding","chunked"); h.end_headers()
        h.wfile.write(b"a\r\n{\"ok\"\r\n")   # partial frame, then close
        h.close_connection = True
    srv, port = start(r)
    e = raises(lambda: client(port).save("src","p/a",b"x"))
    assert type(e) is DriveClientError, type(e)
    assert e.outcome_uncertain is True and e.retry_safe is False, (e.outcome_uncertain, e.retry_safe)
    srv.shutdown()

@probe("hostile: mid-body stall read -> timeout, read False/True")
def _():
    def r(h, b, rec):
        h.send_response(200); h.send_header("Content-Type","application/octet-stream")
        for k,v in [("X-Drive-Offset","0"),("X-Drive-Observed-Size","10"),("X-Drive-Observed-Mtime-Ns","1"),("X-Drive-EOF-Observed","false")]:
            h.send_header(k,v)
        h.send_header("Content-Length","10"); h.end_headers()
        h.wfile.write(b"abc"); h.wfile.flush()
        time.sleep(2.0)   # stall past the 0.5s inactivity budget
    srv, port = start(r)
    t0 = time.time()
    e = raises(lambda: client(port, timeout=0.5).read("src","p/a",length=10))
    dt = time.time() - t0
    assert e.code == "timeout", e.code
    assert e.outcome_uncertain is False and e.retry_safe is True
    assert dt < 1.5, f"did not return promptly: {dt:.2f}s"
    srv.shutdown()

@probe("hostile: mid-body stall save -> timeout, uncertain True/False")
def _():
    def r(h, b, rec):
        h.send_response(200); h.send_header("Content-Type","application/json")
        h.send_header("Content-Length","20"); h.end_headers()
        h.wfile.write(b"{"); h.wfile.flush()
        time.sleep(2.0)
    srv, port = start(r)
    e = raises(lambda: client(port, timeout=0.5).save("src","p/a",b"x"))
    assert e.code == "timeout", e.code
    assert e.outcome_uncertain is True and e.retry_safe is False
    srv.shutdown()

@probe("hostile: mid-body error is redacted (no raw IncompleteRead text)")
def _():
    def r(h, b, rec):
        h.send_response(200); h.send_header("Content-Type","application/json")
        h.send_header("Transfer-Encoding","chunked"); h.end_headers()
        h.wfile.write(b"z\r\nab\r\n"); h.close_connection = True
    srv, port = start(r)
    e = raises(lambda: client(port).save("src","p/a",b"x"))
    txt = str(e) + repr(e) + "".join(str(a) for a in e.args)
    assert "IncompleteRead" not in txt and TOKEN not in txt, txt
    srv.shutdown()


# ---------------------------------------------------------------------------
# 5. conservative uncertainty + no retries
# ---------------------------------------------------------------------------
@probe("save: refused connection -> uncertain True/False")
def _():
    e = raises(lambda: client(dead_port()).save("src","p/a",b"x"))
    assert e.outcome_uncertain is True and e.retry_safe is False

@probe("save: oversize success body -> uncertain True/False")
def _():
    big = b"x" * 70000
    def r(h, b, rec): send(h, 200, big, ctype="application/json", declared=None, chunked=True)
    srv, port = start(r)
    e = raises(lambda: client(port).save("src","p/a",b"x"))
    assert e.outcome_uncertain is True and e.retry_safe is False
    srv.shutdown()

@probe("save: malformed error reply -> uncertain True/False")
def _():
    srv, port = start(lambda h,b,r: send(h, 500, b"garbage", ctype="application/json"))
    e = raises(lambda: client(port).save("src","p/a",b"x"))
    assert e.outcome_uncertain is True and e.retry_safe is False
    srv.shutdown()

@probe("read: refused connection -> uncertain False/True")
def _():
    e = raises(lambda: client(dead_port()).read("src","p/a"))
    assert e.outcome_uncertain is False and e.retry_safe is True

@probe("no retry: save hit exactly once on failure")
def _():
    srv, port = start(lambda h,b,r: send(h, 503, b'{"ok":false,"error":{"code":"busy"}}', ctype="application/json"))
    raises(lambda: client(port).save("src","p/a",b"x")); time.sleep(0.2)
    assert len(srv.records) == 1, len(srv.records); srv.shutdown()

@probe("no retry: read hit exactly once on failure")
def _():
    srv, port = start(lambda h,b,r: send(h, 503, b'{"ok":false,"error":{"code":"busy"}}', ctype="application/json"))
    raises(lambda: client(port).read("src","p/a")); time.sleep(0.2)
    assert len(srv.records) == 1, len(srv.records); srv.shutdown()


# ---------------------------------------------------------------------------
# 6. close ownership / redaction / bounds
# ---------------------------------------------------------------------------
@probe("close: connection+response closed on success")
def _():
    conn = _Conn(_Resp())
    c = _Seam(port=1, token=TOKEN); c._open = lambda: conn
    c.list("src")
    assert conn.closed and conn.resp.closed

@probe("close: connection+response closed on protocol error")
def _():
    conn = _Conn(_Resp(status=500, body=b"nope", ctype="application/json"))
    c = _Seam(port=1, token=TOKEN); c._open = lambda: conn
    raises(lambda: c.list("src"))
    assert conn.closed and conn.resp.closed

@probe("close: one fresh connection per call (no reuse)")
def _():
    c = _Seam(port=1, token=TOKEN)
    c.list("src"); c.find("src", name_contains="x"); c.save("src","p/a",b"x")
    assert len(c._opens) == 3 and len({id(x) for x in c._opens}) == 3

@probe("redaction: token/root/remote message never leak from error")
def _():
    evil = json.dumps({"ok":False,"error":{"code":"denied","outcome_uncertain":False,
        "retry_safe":True,"message":"boom "+TOKEN+" root="+ROOT}}).encode()
    srv, port = start(lambda h,b,r: send(h, 403, evil, ctype="application/json"))
    e = raises(lambda: client(port).save("src","p/a",b"x"))
    txt = str(e) + repr(e) + "".join(str(a) for a in e.args)
    assert TOKEN not in txt and ROOT not in txt and "boom" not in txt, txt
    assert e.code == "denied"
    srv.shutdown()

@probe("redaction: client repr hides token")
def _():
    r = repr(client(1234))
    assert TOKEN not in r and "redacted" in r.lower(), r

@probe("bounds: declared Content-Length over cap fails before body read")
def _():
    def r(h, b, rec):
        h.send_response(200); h.send_header("Content-Type","application/json")
        h.send_header("Content-Length","999999"); h.end_headers()   # no body sent
    srv, port = start(r)
    raises(lambda: client(port).list("src")); srv.shutdown()

@probe("bounds: chunked body of cap+1 fails (bounded read)")
def _():
    big = b"{" + b" " * 70000 + b"}"
    def r(h, b, rec): send(h, 200, big, ctype="application/json", declared=None, chunked=True)
    srv, port = start(r)
    raises(lambda: client(port).list("src")); srv.shutdown()

@probe("bounds: read reply longer than requested fails")
def _():
    srv, port = read_headers([], data=b"abcdef", declared=None, chunked=True)
    raises(lambda: client(port).read("src","p/a",length=3)); srv.shutdown()

@probe("bounds: exact-fill with eof_observed is protocol-invalid")
def _():
    srv, port = read_headers([], data=b"abc")   # eof=true, len==requested
    raises(lambda: client(port).read("src","p/a",length=3)); srv.shutdown()

@probe("bounds: short window with eof_observed accepted")
def _():
    srv, port = read_headers([], data=b"ab")
    rep = client(port).read("src","p/a",length=3)
    assert rep.data == b"ab" and rep.eof_observed is True
    srv.shutdown()


if __name__ == "__main__":
    ok = sum(1 for _, p, _ in R if p)
    for name, p, det in R:
        print(("PASS " if p else "FAIL ") + name + (("  :: " + det) if det else ""))
    print(f"\n{len(R)} probes, {ok} passed, {len(R)-ok} failed")
    raise SystemExit(0 if ok == len(R) else 1)
