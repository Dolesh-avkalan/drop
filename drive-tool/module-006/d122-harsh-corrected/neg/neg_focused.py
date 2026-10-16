#!/usr/bin/env python3
"""D122 focused negatives: write-exception clean FAIL, 6-way barrier entered,
child-hang bounded kill/reap. Loads the corrected payload; no product file is
changed on disk."""
import os, sys, time, json, importlib.util, subprocess

REPO = "/scratch/work/src/drive-tool-337e4c713829af76615472eb47b81244ff399528"
CORRECTED = "/scratch/work/d122/harsh_checks_d110.corrected.py"
sys.path.insert(0, REPO)

spec = importlib.util.spec_from_file_location("d122p", CORRECTED)
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)

from drive_tool.service_client import DriveClient, DriveClientError

out = {}

# ---- NEG1: writer failure must be a clean FAIL, not an unhashable ERROR ----
orig_save = DriveClient.save
state = {"seed": False}


def patched_save(self, source_id, file_id, data, **kw):
    if file_id == "p/savepool/race_over.bin":
        if not state["seed"]:
            state["seed"] = True
            return orig_save(self, source_id, file_id, data, **kw)
        raise DriveClientError("busy", outcome_uncertain=False, retry_safe=True)
    return orig_save(self, source_id, file_id, data, **kw)


DriveClient.save = patched_save
try:
    r = P.stage_concurrent_ops(REPO, 120.0)
    out["NEG1"] = {
        "result": r.get("result"),
        "overwrite_error_count": r.get("overwrite_error_count"),
        "overwrite_errors": r.get("overwrite_errors"),
        "has_overwrite_problem": any("concurrent overwrite errors" in p
                                     for p in (r.get("problems") or [])),
        "is_unhashable_error": r.get("result") == "ERROR",
    }
finally:
    DriveClient.save = orig_save
print("NEG1 write-exception path:", json.dumps(out["NEG1"]))
sys.stdout.flush()

# ---- NEG2: 6-way one-shot barriers actually entered ----
r2 = P.stage_concurrent_ops(REPO, 120.0)
out["NEG2"] = {"result": r2.get("result"),
               "create_entered": r2.get("create_entered"),
               "multi_entered": r2.get("multi_entered"),
               "create_winners": r2.get("create_winners"),
               "create_exists": r2.get("create_exists"),
               "lease_max_held": r2.get("lease_max_held")}
print("NEG2 6-way barrier:", json.dumps(out["NEG2"]))
sys.stdout.flush()

# ---- NEG4: a hanging child must be killed and reaped within the bound ----
rfd, wfd = os.pipe()
proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3600)"],
                        pass_fds=(wfd,), start_new_session=True)
os.close(wfd)
t0 = time.monotonic()
res = P._collect_proc(proc, rfd, timeout=5.0)
dt = time.monotonic() - t0
alive = proc.poll() is None
if alive:
    try:
        os.killpg(os.getpgid(proc.pid), 9)
    except OSError:
        pass
    proc.wait(timeout=10)
out["NEG4"] = {"elapsed_s": round(dt, 2), "returncode": proc.returncode,
               "child_error": res.get("child_error"), "bounded": dt < 20.0,
               "reaped": proc.returncode is not None}
print("NEG4 child-hang:", json.dumps(out["NEG4"]))
print("NEG_SUMMARY:", json.dumps(out))
