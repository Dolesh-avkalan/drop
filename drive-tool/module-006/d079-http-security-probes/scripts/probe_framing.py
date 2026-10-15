"""D079 probe (Defect 1): framing bounds / bare-LF without CRLFCRLF.

Raw loopback sockets against the real adapter over synthetic roots.
socket_timeout is shortened to 1.0s to bound each case; the defect is about
WHICH response is produced (and how fast), not the absolute wait.
"""
import socket
import sys
import tempfile
import time

sys.path.insert(0, ".")
import tests.test_http_adapter as T
from drive_tool.http_adapter import DriveHTTPAdapter

ST = 1.0


def run(name, payload, half_close=False):
    base = tempfile.mkdtemp(prefix="d079-fr-")
    policies, _roots = T._standard_policies(base)
    a = DriveHTTPAdapter(policies, port=0, socket_timeout=ST)
    try:
        s = socket.create_connection(("127.0.0.1", a.port), timeout=ST + 3.0)
        t0 = time.monotonic()
        try:
            s.sendall(payload)
            if half_close:
                s.shutdown(socket.SHUT_WR)
            s.settimeout(ST + 3.0)
            data = b""
            while True:
                try:
                    chunk = s.recv(65536)
                except socket.timeout:
                    break
                if not chunk:
                    break
                data += chunk
            elapsed = time.monotonic() - t0
            first = data.split(b"\r\n", 1)[0].decode("latin-1") if data else "<no bytes>"
            code = ""
            if b'"code":"' in data:
                code = data.split(b'"code":"', 1)[1].split(b'"', 1)[0].decode()
            print("%-46s half=%-5s elapsed=%6.3fs bytes=%-5d status=%-32s code=%s"
                  % (name, half_close, elapsed, len(data), first, code or "-"))
        finally:
            s.close()
    finally:
        a.close(timeout=2.0)


valid = (b"POST /v1/list HTTP/1.1\r\nHost: 127.0.0.1\r\n"
         b"Content-Type: application/json\r\nContent-Length: 2\r\n"
         b"Connection: close\r\n\r\n{}")
run("control: valid request", valid)
run("overlong request line, no CRLFCRLF",
    b"POST /" + b"a" * 8200 + b" HTTP/1.1\r\n")
run("overlong request line, no CRLFCRLF", 
    b"POST /" + b"a" * 8200 + b" HTTP/1.1\r\n", half_close=True)
run("overlong header block, no CRLFCRLF",
    b"POST /v1/list HTTP/1.1\r\nX-Pad: " + b"a" * 16384 + b"\r\n")
run("overlong header block, no CRLFCRLF",
    b"POST /v1/list HTTP/1.1\r\nX-Pad: " + b"a" * 16384 + b"\r\n", half_close=True)
run("bare LF terminator", b"POST /v1/list HTTP/1.1\nHost: 127.0.0.1\n\n")
run("bare LF terminator", b"POST -v1/list HTTP/1.1\nHost: 127.0.0.1\n\n",
    half_close=True)
run("control: buffer > 24576 (size check fires)",
    b"POST /v1/list HTTP/1.1\r\nX-Pad: " + b"a" * 30000 + b"\r\n")
