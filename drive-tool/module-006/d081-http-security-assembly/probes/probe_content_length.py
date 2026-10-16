"""D079 probe (Defect 2): Content-Length digit-count priority + leading zeros."""
import socket
import sys
import tempfile
import time

sys.path.insert(0, ".")
import tests.test_http_adapter as T
from drive_tool.http_adapter import DriveHTTPAdapter

ST = 2.0
AUTH = b"Authorization: Bearer " + T._MAIN_TOKEN.encode("ascii")


def frame(headers, body=b""):
    return (b"POST /v1/list HTTP/1.1\r\n"
            + b"".join(h + b"\r\n" for h in headers) + b"\r\n" + body)


def run(name, headers, body=b""):
    base = tempfile.mkdtemp(prefix="d079-cl-")
    policies, _roots = T._standard_policies(base)
    a = DriveHTTPAdapter(policies, port=0, socket_timeout=ST)
    try:
        s = socket.create_connection(("127.0.0.1", a.port), timeout=ST + 3.0)
        try:
            s.sendall(frame(headers, body))
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
            first = data.split(b"\r\n", 1)[0].decode("latin-1") if data else "<no bytes>"
            code = ""
            if b'"code":"' in data:
                code = data.split(b'"code":"', 1)[1].split(b'"', 1)[0].decode()
            print("%-52s status=%-30s code=%s" % (name, first, code or "-"))
        finally:
            s.close()
    finally:
        a.close(timeout=2.0)


run("c1 huge CL, no Authorization",
    [b"Host: 127.0.0.1", b"Content-Length: 99999999999",
     b"Content-Type: application/json"])
run("c2 huge CL, valid auth, CT text/plain",
    [b"Host: 127.0.0.1", AUTH, b"Content-Type: text/plain",
     b"Content-Length: 99999999999"])
run("c3 leading zeros CL 00000000002, valid auth+CT, body {}",
    [b"Host: 127.0.0.1", AUTH, b"Content-Type: application/json",
     b"Content-Length: 00000000002"], b"{}")
run("c4 control 11-digit CL, valid auth+CT json",
    [b"Host: 127.0.0.1", AUTH, b"Content-Type: application/json",
     b"Content-Length: 99999999999"])
run("c5 control CL 2, valid auth+CT json, body {}",
    [b"Host: 127.0.0.1", AUTH, b"Content-Type: application/json",
     b"Content-Length: 2"], b"{}")
