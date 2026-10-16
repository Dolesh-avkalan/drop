"""D085 gated smoke/soak runner (fixed D064 bounds).

Runs the module's own run_smoke (600 calls, 1 agent) and run_soak (10,000 calls,
6 agents) against the real adapter over synthetic roots and prints every counter
the workload returns, plus a thread census.  Usage: run_smoke_soak.py [smoke|soak]
"""
import json
import sys
import tempfile
import threading
import time

sys.path.insert(0, ".")
import tests.test_http_adapter as T

which = sys.argv[1] if len(sys.argv) > 1 else "smoke"
base = tempfile.mkdtemp(prefix="d085-gate-")
policies, _roots = T._standard_policies(base)
budget = T.THRESHOLDS["max_stage_seconds"]
print("stage=%s  calls=%s  agents=%s  concurrency=%s  outer_budget=%ss"
      % (which, T.SMOKE_CALLS if which == "smoke" else T.SOAK_CALLS,
         1 if which == "smoke" else len(T._SOAK_AGENTS),
         T.MAX_IN_FLIGHT_OPERATIONS, budget))
threads_before = threading.active_count()
t0 = time.monotonic()
if which == "smoke":
    res = T.run_smoke(policies, stage_budget=budget)
else:
    res = T.run_soak(policies, stage_budget=budget)
elapsed = time.monotonic() - t0
threads_after = threading.active_count()
print("threads_before=%d threads_after=%d (expected adapter threads=%d)"
      % (threads_before, threads_after, T.THRESHOLDS["expected_adapter_threads"]))
print("wall_seconds=%.3f" % elapsed)
print(json.dumps(res, indent=2, sort_keys=True, default=str))
import shutil
shutil.rmtree(base, ignore_errors=True)
print("RESULT:", res.get("result"))
