#!/usr/bin/env python3
"""D097 independent real-socket HTTP probes (stdlib only, no builder logs).

Sub-commands
------------
delayed-busy   : hold all six workers at a REAL service-entry barrier, then a
                 seventh raw socket connects, waits 25 ms, and only then sends a
                 valid request.  Patched -> 503 busy envelope; pre-patch -> empty
                 reply (the D088/D094 defect).  Run with --repo pointing at the
                 candidate (patched) or the base (pre-patch).
close-once     : a normal request succeeds; close() then close() again; a new
                 connection after close is refused.
close-timed    : one worker is held in-handler; close(timeout=0.1) must return
                 False within its budget and must not close an unrelated live
                 descriptor; after release close() returns True.
busy-6plus1    : 6 held + 1 excess => exactly 6x200 + 1x503 busy.
"""
import argparse

import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from http_gate_d097 import (  # noqa: E402
    PERSONAS, build_policies, build_roots, _TOKENS, _raw_request, _raw_exchange,
    _status_code,
)

STALL_S = float(os.environ.get("D097_STALL_S", "0.060"))


class _Gate:
    def __init__(self, n):
        self._n = n
        self._lock = threading.Lock()
        self._count = 0
        self.entered = threading.Event()
        self.release = threading.Event()

    def enter(self):
        with self._lock:
            self._count += 1
            if self._count >= self._n:
                self.entered.set()
        self.release.wait(timeout=30.0)


def make_adapter(repo, base_dir, gate=None):
    sys.path.insert(0, repo)
    for m in ("drive_tool.http_adapter", "drive_tool.file_service",
              "drive_tool.service_client", "drive_tool.service_policy"):
        sys.modules.pop(m, None)
    from drive_tool.file_service import LocalFileService
    from drive_tool.http_adapter import DriveHTTPAdapter

    roots, _ = build_roots(base_dir)
    policies = build_policies(roots)

    class _GatedService(LocalFileService):
        _gate = gate

        def list(self, token, source_id, file_id="root", **kwargs):
            g = self._gate
            if g is not None:
                g.enter()
            return super().list(token, source_id, file_id, **kwargs)

    svc = _GatedService(policies)
    adapter = DriveHTTPAdapter(service=svc, port=0, socket_timeout=5.0)
    time.sleep(0.1)
    return adapter, svc, roots


def req_payload():
    return _raw_request(
        "/v1/list", _TOKENS[0],
        json.dumps({"source_id": "main", "file_id": "root",
                    "limit": 20, "offset": 0}).encode("ascii"))


def cmd_delayed_busy(repo):
    base = tempfile.mkdtemp(prefix="d097-probe-")
    adapter = None
    try:
        gate = _Gate(6)
        adapter, svc, _ = make_adapter(repo, base, gate=gate)
        req = req_payload()
        out = {}

        def occupier(i):
            raw = _raw_exchange(adapter.port, req, timeout=15.0)
            out[("occ", i)] = _status_code(raw)

        ts = [threading.Thread(target=occupier, args=(i,)) for i in range(6)]
        for t in ts:
            t.start()
        entered = gate.entered.wait(timeout=20.0)
        # seventh socket: connect, stall 25 ms, then send (the D088 gap)
        s = socket.create_connection(("127.0.0.1", adapter.port), timeout=10.0)
        try:
            time.sleep(STALL_S)
            s.sendall(req)
            s.settimeout(5.0)
            chunks = []
            while True:
                try:
                    ch = s.recv(4096)
                except socket.timeout:
                    break
                if not ch:
                    break
                chunks.append(ch)
            exc_raw = b"".join(chunks)
        finally:
            s.close()
        gate.release.set()
        for t in ts:
            t.join(timeout=15.0)
        exc = _status_code(exc_raw)
        occ_ok = sum(1 for i in range(6) if out.get(("occ", i)) == (200, None))
        return {
            "probe": "delayed-busy", "repo": repo, "entered": entered,
            "occupiers_ok": occ_ok, "excess_status_code": exc,
            "excess_bytes": len(exc_raw),
            "excess_body_head": exc_raw[:80].decode("latin-1"),
            "verdict": ("PASS" if exc == (503, "busy") and occ_ok == 6
                        else "FAIL"),
        }
    finally:
        if adapter is not None:
            try:
                adapter.close(timeout=5.0)
            except BaseException:
                pass
        shutil.rmtree(base, ignore_errors=True)


def cmd_busy_6plus1(repo):
    base = tempfile.mkdtemp(prefix="d097-probe-")
    adapter = None
    try:
        gate = _Gate(6)
        adapter, svc, _ = make_adapter(repo, base, gate=gate)
        req = req_payload()
        out = {}

        def occupier(i):
            out[("occ", i)] = _status_code(_raw_exchange(adapter.port, req, timeout=15.0))

        ts = [threading.Thread(target=occupier, args=(i,)) for i in range(6)]
        for t in ts:
            t.start()
        entered = gate.entered.wait(timeout=20.0)
        exc = _status_code(_raw_exchange(adapter.port, req, timeout=15.0))
        gate.release.set()
        for t in ts:
            t.join(timeout=15.0)
        occ_ok = sum(1 for i in range(6) if out.get(("occ", i)) == (200, None))
        return {"probe": "busy-6plus1", "repo": repo, "entered": entered,
                "occupiers_ok": occ_ok, "excess": exc,
                "verdict": "PASS" if exc == (503, "busy") and occ_ok == 6 else "FAIL"}
    finally:
        if adapter is not None:
            try:
                adapter.close(timeout=5.0)
            except BaseException:
                pass
        shutil.rmtree(base, ignore_errors=True)


def cmd_close_once(repo):
    base = tempfile.mkdtemp(prefix="d097-probe-")
    adapter = None
    try:
        adapter, svc, _ = make_adapter(repo, base)
        req = req_payload()
        first = _status_code(_raw_exchange(adapter.port, req, timeout=5.0))
        c1 = adapter.close(timeout=5.0)
        c2 = adapter.close(timeout=5.0)
        c3 = adapter.close(timeout=5.0)
        port = adapter.port
        refused = False
        try:
            _raw_exchange(port, req, timeout=1.0)
        except Exception:
            refused = True
        return {"probe": "close-once", "repo": repo, "first_response": first,
                "close1": c1, "close2": c2, "close3": c3,
                "new_conn_refused": refused,
                "verdict": "PASS" if (first == (200, None) and c1 and c2 and c3
                                      and refused) else "FAIL"}
    finally:
        if adapter is not None:
            try:
                adapter.close(timeout=5.0)
            except BaseException:
                pass
        shutil.rmtree(base, ignore_errors=True)


def cmd_close_timed(repo):
    base = tempfile.mkdtemp(prefix="d097-probe-")
    adapter = None
    try:
        gate = _Gate(1)
        adapter, svc, _ = make_adapter(repo, base, gate=gate)
        req = req_payload()
        res = {}

        def in_flight():
            try:
                res["r"] = _status_code(_raw_exchange(adapter.port, req, timeout=15.0))
            except Exception as exc:  # noqa: BLE001
                res["r"] = ("exc", type(exc).__name__)

        t = threading.Thread(target=in_flight)
        t.start()
        entered = gate.entered.wait(timeout=10.0)
        # an unrelated live descriptor close() must not touch
        pl, pr = socket.socketpair()
        fd_before = len(os.listdir("/proc/self/fd"))
        start = time.monotonic()
        c1 = adapter.close(timeout=0.1)
        elapsed = time.monotonic() - start
        fd_after = len(os.listdir("/proc/self/fd"))
        pr.sendall(b"ping")
        alive = pl.recv(4) == b"ping"
        pl.close()
        pr.close()
        gate.release.set()
        t.join(timeout=15.0)
        c2 = adapter.close(timeout=5.0)
        return {"probe": "close-timed", "repo": repo, "entered": entered,
                "close_budget_result": c1, "elapsed_s": round(elapsed, 3),
                "fd_before": fd_before, "fd_after": fd_after,
                "unrelated_desc_alive": alive, "final_close": c2,
                "verdict": "PASS" if (c1 is False and elapsed < 0.15
                                      and alive and c2 is True) else "FAIL"}
    finally:
        if adapter is not None:
            try:
                adapter.close(timeout=5.0)
            except BaseException:
                pass
        shutil.rmtree(base, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--probe", required=True,
                    choices=("delayed-busy", "busy-6plus1", "close-once",
                             "close-timed"))
    args = ap.parse_args()
    fn = {"delayed-busy": cmd_delayed_busy, "busy-6plus1": cmd_busy_6plus1,
          "close-once": cmd_close_once, "close-timed": cmd_close_timed}[args.probe]
    print(json.dumps(fn(args.repo), indent=2))


if __name__ == "__main__":
    main()
