"""D095/D094 real-socket 6+1 busy check, repeated.

Six occupiers hold every adapter slot through the post-response drain, then an
excess probe connects while no slot is free and sends NOTHING (a stalled peer).
A busy rejection must still deliver the 503 envelope; before the phase split the
pre-read consumed the whole 50 ms budget and the write never happened, so the
client saw an empty response (which the production client maps to `unavailable`).

Prints one line per cycle plus a verdict.  No production change is made here.
"""
import json
import socket
import sys
import tempfile
import threading
import time

sys.path.insert(0, ".")
from drive_tool.http_adapter import DriveHTTPAdapter
from drive_tool.service_policy import AgentPolicy, SourceGrant
import hashlib
import os

CYCLES = int(sys.argv[1]) if len(sys.argv) > 1 else 25
OCCUPIERS = 6
TOKEN = "d095-busy-" + "A" * 40


def build():
    base = tempfile.mkdtemp(prefix="d095-busy-")
    root = os.path.join(base, "main")
    os.makedirs(os.path.join(root, "savepool"), exist_ok=True)
    with open(os.path.join(root, "readme.txt"), "wb") as fh:
        fh.write(b"x" * 64)
    grant = SourceGrant(alias="main", root=os.path.realpath(root),
                        operations=frozenset(("find", "list", "read", "save")))
    policy = AgentPolicy(agent_id="agent-main",
                         token_sha256=hashlib.sha256(TOKEN.encode("ascii")).digest(),
                         grants=(grant,))
    return base, (policy,)


def read_all(sock, timeout):
    sock.settimeout(timeout)
    chunks = []
    while True:
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            break
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


def main():
    base, policies = build()
    adapter = DriveHTTPAdapter(policies, port=0, socket_timeout=5.0)
    time.sleep(0.1)
    body = json.dumps({"source_id": "main", "file_id": "root",
                       "limit": 20, "offset": 0}).encode("ascii")
    req = (b"POST /v1/list HTTP/1.1\r\nHost: 127.0.0.1\r\n"
           b"Authorization: Bearer " + TOKEN.encode("ascii") + b"\r\n"
           b"Content-Type: application/json\r\n"
           b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
           b"Connection: close\r\n\r\n" + body)

    rows = []
    try:
        for cycle in range(CYCLES):
            barrier = threading.Barrier(OCCUPIERS + 1)
            out = {}

            def occupier(i):
                barrier.wait(timeout=10.0)
                s = socket.create_connection(("127.0.0.1", adapter.port), timeout=5.0)
                try:
                    s.sendall(req)
                    time.sleep(0.030)          # keep the slot through the drain
                    raw = read_all(s, 2.0)
                    out[("occ", i)] = raw[:12]
                finally:
                    s.close()

            def excess():
                barrier.wait(timeout=10.0)
                time.sleep(0.010)
                s = socket.create_connection(("127.0.0.1", adapter.port), timeout=5.0)
                try:
                    raw = read_all(s, 3.0)     # stalled peer: send nothing
                    out["excess"] = raw
                finally:
                    s.close()

            ts = [threading.Thread(target=occupier, args=(i,)) for i in range(OCCUPIERS)]
            ts.append(threading.Thread(target=excess))
            for t in ts:
                t.start()
            for t in ts:
                t.join(timeout=10.0)

            raw = out.get("excess", b"")
            status = None
            code = None
            if raw[:8] == b"HTTP/1.1":
                try:
                    status = int(raw.split(b" ", 2)[1])
                except (IndexError, ValueError):
                    pass
                if b"\r\n\r\n" in raw:
                    try:
                        obj = json.loads(raw.split(b"\r\n\r\n", 1)[1].decode())
                        if obj.get("ok") is False:
                            code = obj["error"].get("code")
                    except Exception:  # noqa: BLE001
                        pass
            rows.append({"cycle": cycle, "excess_bytes": len(raw),
                         "excess_status": status, "excess_code": code})
            print("cycle %2d  excess bytes=%-4d status=%-4s code=%s"
                  % (cycle, len(raw), status, code))

        closed = adapter.close(timeout=10.0)
        busy = sum(1 for r in rows if r["excess_code"] == "busy")
        empty = sum(1 for r in rows if r["excess_bytes"] == 0)
        unavail = sum(1 for r in rows if r["excess_code"] == "unavailable")
        print()
        print("cycles=%d busy=%d empty=%d unavailable=%d closed=%s"
              % (CYCLES, busy, empty, unavail, closed))
        print("VERDICT:", "PASS" if (busy == CYCLES and empty == 0 and unavail == 0
                                     and closed) else "FAIL")
    finally:
        import shutil
        shutil.rmtree(base, ignore_errors=True)


main()
