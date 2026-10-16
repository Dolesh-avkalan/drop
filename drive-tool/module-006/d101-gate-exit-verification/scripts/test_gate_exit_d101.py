#!/usr/bin/env python3
"""D101 gate-exit unit suite -- negative injections prove a false pass impossible.

This suite imports the REAL corrected harness (``http_gate_d101.py``) and
exercises its actual aggregate + exit path.  It does not reimplement the
logic under test:

  * ``_aggregate_gate`` is the harness function itself;
  * ``main(["--gate", ...])`` is the harness entry point, so the return
    value IS the process exit code the CLI would produce.

Every injection below makes some required stage FAIL / MISSING / SKIPPED /
ERROR / TIMEOUT and asserts the gate is NONZERO.  The exhaustive truth table
sweeps every status for every required stage (7**4 combinations) and asserts
the gate passes for exactly one combination -- all four stages PASS.
"""
import contextlib
import importlib.util
import io
import itertools
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HARNESS = os.path.join(HERE, "http_gate_d101.py")


def load_harness():
    spec = importlib.util.spec_from_file_location("http_gate_d101", HARNESS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


H = load_harness()
REQ = H.REQUIRED_STAGES
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def stage(result):
    return {"result": result, "problems": [] if result == "PASS" else ["injected %s" % result]}


def patch_stages(**by_name):
    """Install fake stage runners; returns a call log for the injected names."""
    calls = {"selfcheck": 0, "smoke600": 0, "soak10000": 0, "saturation_6plus1": 0}

    def fake_selfcheck():
        calls["selfcheck"] += 1
        return by_name.get("selfcheck", stage("PASS"))

    def fake_run_stage(repo, total, valid, ro, tag):
        calls[tag] += 1
        return by_name.get(tag, stage("PASS"))

    def fake_saturation(repo):
        calls["saturation_6plus1"] += 1
        return by_name.get("saturation_6plus1", stage("PASS"))

    H.selfcheck = fake_selfcheck
    H.run_stage = fake_run_stage
    H.run_saturation = fake_saturation
    return calls


def gate_rc():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = H.main(["--gate", "--repo", "/nonexistent-repo-not-touched"])
    return rc


# --------------------------------------------------------------------------
# 1. happy path: all four required stages PASS -> exit 0
# --------------------------------------------------------------------------
patch_stages()
rc = gate_rc()
check("all-pass exit 0", rc == 0, "rc=%r" % rc)

# --------------------------------------------------------------------------
# 2. each required stage failing -> nonzero, and the run-order rules hold
# --------------------------------------------------------------------------
calls = patch_stages(selfcheck="FAIL")
rc = gate_rc()
check("selfcheck FAIL -> nonzero", rc != 0, "rc=%r" % rc)
check("selfcheck FAIL -> smoke not run", calls["smoke600"] == 0,
      "smoke calls=%d" % calls["smoke600"])
check("selfcheck FAIL -> saturation not run", calls["saturation_6plus1"] == 0)

calls = patch_stages(smoke600="FAIL")
rc = gate_rc()
check("smoke FAIL -> nonzero", rc != 0, "rc=%r" % rc)
check("smoke FAIL -> NO soak after smoke fail", calls["soak10000"] == 0,
      "soak calls=%d" % calls["soak10000"])
check("smoke FAIL -> NO saturation after smoke fail", calls["saturation_6plus1"] == 0)

patch_stages(soak10000="FAIL")
rc = gate_rc()
check("soak FAIL -> nonzero", rc != 0, "rc=%r" % rc)

patch_stages(saturation_6plus1="FAIL")
rc = gate_rc()
check("saturation FAIL -> nonzero", rc != 0, "rc=%r" % rc)

# --------------------------------------------------------------------------
# 3. skipped / missing / error / timeout injections -> nonzero
# --------------------------------------------------------------------------
patch_stages(smoke600="SKIPPED")
check("smoke SKIPPED -> nonzero", gate_rc() != 0)

patch_stages(smoke600="ERROR")
check("smoke ERROR -> nonzero", gate_rc() != 0)

patch_stages(soak10000="TIMEOUT")
check("soak TIMEOUT -> nonzero", gate_rc() != 0)

# a stage that RAISES must not look like a pass
def raising_stage(repo, total, valid, ro, tag):
    if tag == "smoke600":
        raise RuntimeError("injected crash")
    return stage("PASS")


def raising_selfcheck():
    return stage("PASS")


H.selfcheck = raising_selfcheck
H.run_stage = raising_stage
H.run_saturation = lambda repo: stage("PASS")
check("stage raising -> nonzero", gate_rc() != 0)

# a stage that RAISES TimeoutError must not look like a pass
def timeout_stage(repo, total, valid, ro, tag):
    if tag == "soak10000":
        raise TimeoutError("injected timeout")
    return stage("PASS")


H.run_stage = timeout_stage
check("stage TimeoutError -> nonzero", gate_rc() != 0)

# a stage that returns a non-dict must not look like a pass
H.run_stage = lambda repo, total, valid, ro, tag: "PASS"  # truthy but not a dict
check("stage non-dict return -> nonzero", gate_rc() != 0)

# --------------------------------------------------------------------------
# 4. aggregate truth table -- direct, exhaustive
# --------------------------------------------------------------------------
STATUSES = (None, "PASS", "FAIL", "SKIPPED", "ERROR", "TIMEOUT", "MISSING")
combos = 0
false_passes = []
for combo in itertools.product(STATUSES, repeat=len(REQ)):
    stages = {}
    for name, status in zip(REQ, combo):
        stages[name] = None if status is None else {"result": status}
    ok, problems = H._aggregate_gate(stages)
    combos += 1
    should_pass = all(s == "PASS" for s in combo)
    if ok != should_pass:
        false_passes.append((combo, ok))
check("aggregate truth table exhaustive (%d combos)" % combos, combos == len(STATUSES) ** len(REQ))
check("aggregate passes for EXACTLY the all-PASS combination",
      not false_passes and combos == len(STATUSES) ** len(REQ),
      "false passes=%r" % false_passes)

# --------------------------------------------------------------------------
# 5. no false pass via the real entry point across the truth table
# --------------------------------------------------------------------------
rc_false_pass = []
for combo in itertools.product(STATUSES, repeat=len(REQ)):
    by = {}
    for name, status in zip(REQ, combo):
        by[name] = None if status is None else stage(status)
    # a None injection means the stage function returns a dict with result None
    for name in REQ:
        if by[name] is None:
            by[name] = {"result": None}
    patch_stages(**by)
    rc = gate_rc()
    should_zero = all(s == "PASS" for s in combo)
    if (rc == 0) != should_zero:
        rc_false_pass.append((combo, rc))
check("entry-point exit matches truth table (no false pass)",
      not rc_false_pass, "mismatches=%r" % rc_false_pass[:3])

# --------------------------------------------------------------------------
# 6. the real exit mapping on a genuine aggregate dict
# --------------------------------------------------------------------------
allpass = {n: stage("PASS") for n in REQ}
ok, _ = H._aggregate_gate(allpass)
check("all-PASS aggregate ok", ok)
for n in REQ:
    bad = dict(allpass)
    bad[n] = stage("FAIL")
    ok2, probs = H._aggregate_gate(bad)
    check("one-FAIL (%s) aggregate not ok" % n, not ok2, str(probs))

# --------------------------------------------------------------------------
summary = {
    "harness": "d101-gate-exit-unit-suite",
    "python": sys.version.split()[0],
    "checks": [{"name": n, "ok": o, "detail": d} for n, o, d in results],
    "passed": sum(1 for _, o, _ in results if o),
    "failed": sum(1 for _, o, _ in results if not o),
    "total": len(results),
    "truth_table_combos": combos,
    "false_passes": false_passes,
    "entry_point_mismatches": rc_false_pass,
}
out = os.path.join(HERE, "..", "logs", "d101_gate_exit_unit_%s.json" % sys.version.split()[0])
with open(out, "w", encoding="utf-8") as fh:
    json.dump(summary, fh, indent=2, sort_keys=True)
print("\n%d/%d checks passed; truth-table combos=%d; false passes=%d"
      % (summary["passed"], summary["total"], combos, len(false_passes) + len(rc_false_pass)))
sys.exit(0 if summary["failed"] == 0 else 1)
