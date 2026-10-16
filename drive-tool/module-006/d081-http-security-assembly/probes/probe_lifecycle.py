"""D079 probe (Defect 4): startup 6-slot readiness, repeated close(), handoff."""
import collections
import socket
import sys
import tempfile
import threading
import time

sys.path.insert(0, ".")
import tests.test_http_adapter as T
from drive_tool.http_adapter import DriveHTTPAdapter

VALID = (b"POST /v1/list HTTP/1.1\r\nHost: 127.0.0.1\r\n"
         b"Content-Type: application/json\r\nContent-Length: 2\r\n"
         b"Connection: close\r\n\r\n{}")


def status_of(data):
    return data.split(b"\r\n", 1)[0].decode("latin-1") if data else "<no bytes>"


def one_request(port, out, i):
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=5.0)
        s.sendall(VALID)
        s.settimeout(5.0)
        data = b""
        while True:
            try:
                c = s.recv(65536)
            except socket.timeout:
                break
            if not c:
                break
            data += c
        out[i] = status_of(data)
        s.close()
    except Exception as e:  # noqa: BLE001
        out[i] = "ERR:%s" % type(e).__name__


print("== 4.1 startup 6-slot readiness (6 concurrent requests right after __init__) ==")
trials = 40
tally = collections.Counter()
for _ in range(trials):
    base = tempfile.mkdtemp(prefix="d079-lc1-")
    policies, _r = T._standard_policies(base)
    a = DriveHTTPAdapter(policies, port=0, socket_timeout=3.0)
    port = a.port
    out = [None] * 6
    ts = [threading.Thread(target=one_request, args=(port, out, i)) for i in range(6)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=8.0)
    a.close(timeout=5.0)
    for r in out:
        tally["busy_503" if r and "503" in r else
              "ok_403" if r and "403" in r else
              "ok_200" if r and "200" in r else str(r)] += 1
print("  trials=%d requests=%d tally=%s" % (trials, trials * 6, dict(tally)))

print()
print("== 4.2 repeated close() re-invokes _wake_listener() after the listener is closed ==")
base = tempfile.mkdtemp(prefix="d079-lc2-")
policies, _r = T._standard_policies(base)
svc = T.InstrumentedService(policies)
a = DriveHTTPAdapter(service=svc, port=0, socket_timeout=5.0)
port = a.port
wakes = []
orig_wake = a._wake_listener


def counting_wake():
    wakes.append((a._port, a._listener.fileno() if a._listener else "closed"))
    return orig_wake()


a._wake_listener = counting_wake
svc.block = True
svc.block_target = 1
svc.block_timeout = 10.0
th = threading.Thread(target=lambda: _inflight(port), daemon=True)


def _inflight(p):
    try:
        T.DriveClient(port=p, token=T._MAIN_TOKEN, timeout=8.0).list("main", limit=5)
    except Exception:  # noqa: BLE001
        pass


th.start()
print("  gate entered:", svc.entered.wait(timeout=5.0))
print("  close#1(timeout=0.1) ->", a.close(timeout=0.1), " wake_calls=", len(wakes))
svc.release_gate()
th.join(timeout=8.0)
time.sleep(0.2)
srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
bound = False
for _ in range(20):
    try:
        srv.bind(("127.0.0.1", port))
        srv.listen(4)
        bound = True
        break
    except OSError:
        time.sleep(0.05)
print("  rebind released port %d -> %s" % (port, bound))
srv.settimeout(1.5)
r2 = a.close(timeout=0.3)
print("  close#2(timeout=0.3) ->", r2, " wake_calls=", len(wakes), " targets=", wakes)
if bound:
    try:
        conn, _ = srv.accept()
        print("  RESULT: wake-connect REACHED the released port (our listener accepted)")
        conn.close()
    except socket.timeout:
        print("  RESULT: no connection reached our listener")
print("  close#3(timeout=5.0) ->", a.close(timeout=5.0))
try:
    srv.close()
except OSError:
    pass

print()
print("== 4.3 idle connection handed off; close() does not close it ==")
for k in range(3):
    base = tempfile.mkdtemp(prefix="d079-lc3-")
    policies, _r = T._standard_policies(base)
    a = DriveHTTPAdapter(policies, port=0, socket_timeout=2.0)
    port = a.port
    c = socket.create_connection(("127.0.0.1", port), timeout=5.0)
    time.sleep(0.02)
    t0 = time.monotonic()
    r = a.close(timeout=0.05)
    tc = time.monotonic() - t0
    c.settimeout(6.0)
    data = b""
    try:
        while True:
            ch = c.recv(65536)
            if not ch:
                break
            data += ch
    except socket.timeout:
        pass
    el = time.monotonic() - t0
    print("  trial %d: close(0.05)=%-5s returned in %.3fs; client got %d bytes after "
          "%.3fs status=%s" % (k, r, tc, len(data), el, status_of(data)))
    c.close()
    a.close(timeout=5.0)
