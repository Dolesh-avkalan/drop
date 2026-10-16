#!/usr/bin/env python3
"""D119 repro A: run the first-D110 concurrent_ops stage under CPU contention,
counting busy rejects and max concurrently-served connections via monkeypatch.

Reads only; changes no product file. Prints one line per iteration.
"""
import os, sys, json, time, signal

REPO = "/scratch/work/src/drive-tool-337e4c713829af76615472eb47b81244ff399528"
sys.path.insert(0, REPO)
sys.path.insert(0, "/scratch/work/d119/d110src")

import drive_tool.http_adapter as HA

BUSY = {"n": 0}
SERVED = {"cur": 0, "max": 0}
_busy = HA.DriveHTTPAdapter._busy_reject
_serve = HA.DriveHTTPAdapter._serve

def busy(self, conn):
    BUSY["n"] += 1
    return _busy(self, conn)

def serve(self, conn):
    SERVED["cur"] += 1
    if SERVED["cur"] > SERVED["max"]:
        SERVED["max"] = SERVED["cur"]
    try:
        return _serve(self, conn)
    finally:
        SERVED["cur"] -= 1

HA.DriveHTTPAdapter._busy_reject = busy
HA.DriveHTTPAdapter._serve = serve

import harsh_checks_d110 as H


def cpu_hogs(n):
    pids = []
    for _ in range(n):
        pid = os.fork()
        if pid == 0:
            try:
                os.nice(15)
                import hashlib
                while True:
                    hashlib.pbkdf2_hmac("sha256", b"x" * 64, b"y" * 16, 20000)
            except BaseException:
                pass
            os._exit(0)
        pids.append(pid)
    return pids


def main():
    n_iter = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    hogs = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    print("nproc", os.cpu_count(), "hogs", hogs, "iters", n_iter)
    pids = cpu_hogs(hogs)
    time.sleep(0.2)
    fails = 0
    try:
        for i in range(n_iter):
            BUSY["n"] = 0
            SERVED["max"] = 0
            t0 = time.monotonic()
            res = H.stage_concurrent_ops(REPO, 120.0)
            dt = time.monotonic() - t0
            ok = res.get("result") == "PASS"
            if not ok:
                fails += 1
            print("iter %2d %s %.2fs busy=%d served_max=%d problems=%s"
                  % (i, res.get("result"), dt, BUSY["n"], SERVED["max"],
                     res.get("problems")))
            sys.stdout.flush()
    finally:
        for p in pids:
            try:
                os.kill(p, signal.SIGKILL)
            except ProcessLookupError:
                pass
        for p in pids:
            try:
                os.waitpid(p, 0)
            except ChildProcessError:
                pass
    print("TOTAL fails=%d/%d" % (fails, n_iter))


if __name__ == "__main__":
    main()
