"""D079 probe (Defect 3): already-buffered trailing bytes vs a pipelined request.

Counts LocalFileService executions via the real-service instrumented seam.
"""
import socket
import sys
import tempfile

sys.path.insert(0, ".")
import tests.test_http_adapter as T
from drive_tool.http_adapter import DriveHTTPAdapter

ST = 2.0
AUTH = b"Authorization: Bearer " + T._MAIN_TOKEN.encode("ascii")


def run(name, payload):
    base = tempfile.mkdtemp(prefix="d079-pi-")
    policies, _r = T._standard_policies(base)
    svc = T.InstrumentedService(policies)
    a = DriveHTTPAdapter(service=svc, port=0, socket_timeout=ST)
    try:
        c = socket.create_connection(("127.0.0.1", a.port), timeout=ST + 3)
        c.sendall(payload)
        c.settimeout(ST + 3)
        data = b""
        while True:
            try:
                ch = c.recv(65536)
            except socket.timeout:
                break
            if not ch:
                break
            data += ch
        first = data.split(b"\r\n", 1)[0].decode("latin-1") if data else "<no bytes>"
        calls = list(svc.calls)
        print("%-44s status=%-22s service_calls=%d %s"
              % (name, first, len(calls), calls[:2]))
        c.close()
    finally:
        a.close(timeout=2.0)


def hdr(cl):
    return (b"POST /v1/list HTTP/1.1\r\nHost: 127.0.0.1\r\n" + AUTH
            + b"\r\nContent-Type: application/json\r\nContent-Length: "
            + str(cl).encode() + b"\r\nConnection: close\r\n\r\n")


run("A already-buffered > CL (CL=100, 200 sent)", hdr(100) + b"x" * 200)
run("B control CL=2 body {}", hdr(2) + b"{}")

import json  # noqa: E402
# Valid list payload padded with legal JSON whitespace so the body exceeds one
# _RECV_CHUNK (4096) and is therefore NOT fully buffered during Phase A.
core = json.dumps({"source_id": "main", "file_id": "root", "limit": 5,
                   "offset": 0}, separators=(",", ":")).encode()
payload = core + b" " * (6000 - len(core))
req2 = hdr(2) + b"{}"
run("C pipelined req1(CL=%d)+req2" % len(payload), hdr(len(payload)) + payload + req2)
run("D pipelined req1(CL=%d)+req2 again" % len(payload),
    hdr(len(payload)) + payload + req2)
