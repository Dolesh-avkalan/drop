"""D055 independent verification of the D053 body-transport fix (pin 53450a4).

Checks that a failure *while reading a response body* is mapped to a safe
DriveClientError with the correct uncertainty flags, code (timeout vs
unavailable), redaction, close ownership and no-retry.
"""
import http.server, os, socket, socketserver, struct, sys, threading, time
sys.path.insert(0, os.environ.get("D052_TREE", "/scratch/work/d053verify"))
from drive_tool.service_client import DriveClient, DriveClientError

TOKEN = "q" * 40
R = []

def rec(name, ok, det=""):
    R.append((name, ok, det))
    print(("PASS " if ok else "FAIL ") + name + (("  :: " + det) if det else ""))

class S(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

def start(handler):
    srv = S(("127.0.0.1", 0), handler); threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]

def hdr(h, ct, extra):
    h.send_response(200); h.send_header("Content-Type", ct)
    for k, v in extra: h.send_header(k, v)

READH = [("X-Drive-Offset","0"),("X-Drive-Observed-Size","10"),("X-Drive-Observed-Mtime-Ns","1"),("X-Drive-EOF-Observed","false")]

# 1. truncated chunked read body -> unavailable, read flags False/True
def t1():
    class H(http.server.BaseHTTPRequestHandler):
        protocol_version="HTTP/1.1"
        def log_message(s,*a): pass
        def do_POST(s):
            cl=s.headers.get("Content-Length"); s.rfile.read(int(cl)) if cl else None
            hdr(s,"application/octet-stream",READH); s.send_header("Transfer-Encoding","chunked"); s.end_headers()
            s.wfile.write(b"a\r\nabc\r\n"); s.close_connection=True
    srv,port=start(H)
    try:
        DriveClient(port=port,token=TOKEN).read("s","p/a",length=8); rec("read truncated body",False,"no raise")
    except DriveClientError as e:
        rec("read truncated body -> unavailable False/True", e.code=="unavailable" and e.outcome_uncertain is False and e.retry_safe is True, f"code={e.code} u={e.outcome_uncertain} r={e.retry_safe}")
    except BaseException as e:
        rec("read truncated body",False,f"RAW {type(e).__name__}")
    srv.shutdown()

# 2. truncated save body -> unavailable, save flags True/False
def t2():
    class H(http.server.BaseHTTPRequestHandler):
        protocol_version="HTTP/1.1"
        def log_message(s,*a): pass
        def do_POST(s):
            cl=s.headers.get("Content-Length"); s.rfile.read(int(cl)) if cl else None
            s.send_response(200); s.send_header("Content-Type","application/json")
            s.send_header("Transfer-Encoding","chunked"); s.end_headers()
            s.wfile.write(b"a\r\nabc\r\n"); s.close_connection=True
    srv,port=start(H)
    try:
        DriveClient(port=port,token=TOKEN).save("s","p/a",b"x"); rec("save truncated body",False,"no raise")
    except DriveClientError as e:
        rec("save truncated body -> unavailable True/False", e.code=="unavailable" and e.outcome_uncertain is True and e.retry_safe is False, f"code={e.code} u={e.outcome_uncertain} r={e.retry_safe}")
    except BaseException as e:
        rec("save truncated body",False,f"RAW {type(e).__name__}")
    srv.shutdown()

# 3. mid-body stall (server sleeps past client timeout) -> code timeout, read flags False/True
def t3():
    class H(http.server.BaseHTTPRequestHandler):
        protocol_version="HTTP/1.1"
        def log_message(s,*a): pass
        def do_POST(s):
            cl=s.headers.get("Content-Length"); s.rfile.read(int(cl)) if cl else None
            hdr(s,"application/octet-stream",READH); s.send_header("Content-Length","8"); s.end_headers()
            time.sleep(3.0)  # stall past the client's 0.5s inactivity budget
            try: s.wfile.write(b"12345678")
            except Exception: pass
            s.close_connection=True
    srv,port=start(H)
    t0=time.time()
    try:
        DriveClient(port=port,token=TOKEN,timeout=0.5).read("s","p/a",length=8); rec("read stalled body",False,"no raise")
    except DriveClientError as e:
        dt=time.time()-t0
        rec("read stalled body -> timeout False/True", e.code=="timeout" and e.outcome_uncertain is False and e.retry_safe is True, f"code={e.code} u={e.outcome_uncertain} r={e.retry_safe} dt={dt:.2f}s")
    except BaseException as e:
        rec("read stalled body",False,f"RAW {type(e).__name__}: {e}")
    srv.shutdown()

# 4. mid-body stall on save -> code timeout, save flags True/False
def t4():
    class H(http.server.BaseHTTPRequestHandler):
        protocol_version="HTTP/1.1"
        def log_message(s,*a): pass
        def do_POST(s):
            cl=s.headers.get("Content-Length"); s.rfile.read(int(cl)) if cl else None
            s.send_response(200); s.send_header("Content-Type","application/json")
            s.send_header("Content-Length","8"); s.end_headers()
            time.sleep(3.0)
            try: s.wfile.write(b'{"ok":tr')
            except Exception: pass
            s.close_connection=True
    srv,port=start(H)
    try:
        DriveClient(port=port,token=TOKEN,timeout=0.5).save("s","p/a",b"x"); rec("save stalled body",False,"no raise")
    except DriveClientError as e:
        rec("save stalled body -> timeout True/False", e.code=="timeout" and e.outcome_uncertain is True and e.retry_safe is False, f"code={e.code} u={e.outcome_uncertain} r={e.retry_safe}")
    except BaseException as e:
        rec("save stalled body",False,f"RAW {type(e).__name__}: {e}")
    srv.shutdown()

# 5. close ownership on mid-body failure (seam) + redaction of body error
def t5():
    import http.client
    class Resp:
        status=200
        def getheader(s,n,d=None): return "application/json" if n.lower()=="content-type" else None
        @property
        def headers(s):
            class H:
                def get_all(self,n): return None
            return H()
        def read(s,n=None): raise http.client.IncompleteRead(b"", 10)
        def close(s): s.closed=True
    class Conn:
        def __init__(s,r): s.r=r; s.closed=False
        def request(s,*a,**k): pass
        def getresponse(s): return s.r
        def close(s): s.closed=True
    r=Resp(); c=Conn(r)
    class Seam(DriveClient):
        def _open(self): return c
    try:
        Seam(port=1,token=TOKEN).list("s")
    except DriveClientError as e:
        txt=str(e)+repr(e)
        rec("mid-body failure: conn+resp closed", c.closed and getattr(r,"closed",False))
        rec("mid-body failure: redacted", TOKEN not in txt and "IncompleteRead" not in txt)

# 6. no retry on body transport error (server hit once)
def t6():
    hits={"n":0}
    class H(http.server.BaseHTTPRequestHandler):
        protocol_version="HTTP/1.1"
        def log_message(s,*a): pass
        def do_POST(s):
            hits["n"]+=1
            cl=s.headers.get("Content-Length"); s.rfile.read(int(cl)) if cl else None
            s.send_response(200); s.send_header("Content-Type","application/json")
            s.send_header("Transfer-Encoding","chunked"); s.end_headers()
            s.wfile.write(b"a\r\nabc\r\n"); s.close_connection=True
    srv,port=start(H)
    try: DriveClient(port=port,token=TOKEN).save("s","p/a",b"x")
    except DriveClientError: pass
    time.sleep(0.2)
    rec("no retry on body transport error", hits["n"]==1, f"hits={hits['n']}")
    srv.shutdown()

for f in (t1,t2,t3,t4,t5,t6):
    try: f()
    except Exception as e: rec(f.__name__, False, repr(e)[:120])

npass=sum(1 for _,ok,_ in R if ok)
print(f"\n{len(R)} checks, {npass} passed, {len(R)-npass} failed")
sys.exit(0 if npass==len(R) else 1)
