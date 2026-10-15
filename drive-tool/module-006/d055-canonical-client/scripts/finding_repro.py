"""D052 finding repro: mid-body transport failure leaks a raw exception.

A server that declares a body larger than it delivers (truncated chunked stream,
or a short read against a declared Content-Length) makes the client's bounded
body read raise http.client.IncompleteRead. That happens *after* the
conn.request/getresponse guard, so it is not wrapped: the raw exception escapes
instead of a safe DriveClientError. Applies to read, list/find and save.
"""
import http.server, os, socketserver, sys, threading, json
sys.path.insert(0, os.environ.get("D052_TREE", "/scratch/work/candidate"))
from drive_tool.service_client import DriveClient, DriveClientError

TOKEN = "z" * 40

def make(handler_mode):
    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *a): pass
        def do_POST(self):
            cl = self.headers.get("Content-Length")
            if cl: self.rfile.read(int(cl))
            h = self
            h.send_response(200)
            h.send_header("Content-Type", "application/octet-stream" if handler_mode == "read" else "application/json")
            for k, v in [("X-Drive-Offset","0"),("X-Drive-Observed-Size","100"),
                         ("X-Drive-Observed-Mtime-Ns","1"),("X-Drive-EOF-Observed","false")]:
                h.send_header(k, v)
            # declare a 100-byte chunk, deliver 3 bytes, then close mid-body
            h.send_header("Transfer-Encoding", "chunked")
            h.end_headers()
            h.wfile.write(b"64\r\nabc\r\n")
            h.close_connection = True
    class S(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
    srv = S(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]

def attempt(label, fn):
    try:
        fn()
        print(f"{label}: NO EXCEPTION (unexpected)")
    except DriveClientError as e:
        print(f"{label}: DriveClientError(code={e.code!r}, outcome_uncertain={e.outcome_uncertain}, retry_safe={e.retry_safe})  [SAFE]")
    except BaseException as e:
        print(f"{label}: RAW {type(e).__module__}.{type(e).__name__}: {e}  [LEAKED]")

for mode, label, call in [
    ("read", "read  truncated body", lambda c: c.read("s", "p/a", length=8)),
    ("json", "list  truncated body", lambda c: c.list("s")),
    ("json", "save  truncated body", lambda c: c.save("s", "p/a", b"x")),
]:
    srv, port = make(mode)
    attempt(label, lambda port=port, call=call: call(DriveClient(port=port, token=TOKEN)))
    srv.shutdown()
