#!/usr/bin/env python3
"""D119 repro D: run the PATCHED payload's concurrent_ops under CPU contention
and resource_pressure, to show new-pass (old-fail -> new-pass).

Loads the patched payload as a module; does not modify any product file.
"""
import os, sys, time, signal, importlib.util

REPO = "/scratch/work/src/drive-tool-337e4c713829af76615472eb47b81244ff399528"
PATCHED = "/scratch/work/d119/harsh_checks_d110.patched.py"

spec = importlib.util.spec_from_file_location("patched_d110", PATCHED)
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)


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
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    mode = sys.argv[2] if len(sys.argv) > 2 else "all"
    print("nproc", os.cpu_count(), "iters", n, "mode", mode)
    pids = cpu_hogs(4)
    time.sleep(0.2)
    fails = 0
    try:
        if mode != "res":
            for i in range(n):
                r = P.stage_concurrent_ops(REPO, 120.0)
                if r.get("result") != "PASS":
                    fails += 1
                    print("  iter %d FAIL problems=%s" % (i, r.get("problems")))
                sys.stdout.flush()
            print("PATCHED concurrent_ops: %d/%d FAIL (expected 0)" % (fails, n))
            r = P.stage_concurrent_ops(REPO, 120.0)
            print("  sample: result=%s lease_max_held=%s overwrite_errors=%s torn=%s"
                  % (r.get("result"), r.get("lease_max_held"),
                     r.get("overwrite_errors"), r.get("torn_count")))
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
    if mode == "conc":
        return
    print("\n== PATCHED resource_pressure ==")
    rp = P.stage_resource_pressure(REPO, 300.0)
    print("  result:", rp.get("result"))
    print("  R2:", rp.get("R2_memory_pressure"))
    print("  R1 ok:", (rp.get("R1_cpu_saturation") or {}).get("ok"))
    print("  R3:", {k: (rp.get("R3_emfile") or {}).get(k) for k in ("result", "mapped", "raw", "recovery_ok")})
    print("  problems:", rp.get("problems"))


if __name__ == "__main__":
    main()
