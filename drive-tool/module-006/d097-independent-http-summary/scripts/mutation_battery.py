#!/usr/bin/env python3
"""D097 independent security-mutation battery.

For each security property (framing / auth / caps / once-only-close /
timed-close / busy-phase) apply ONE surgical semantic mutation to a private
copy of the candidate drive_tool/http_adapter.py, confirm the mutant still
compiles cleanly (no syntax false-positive), and run the targeted test class.

A mutation that the tests do NOT catch is a gate FAIL for that category.
The unmutated candidate must PASS the same class ("new pass").
"""
import json
import os
import shutil
import subprocess
import sys

CAND = "/scratch/work/candidate"
MUT_ROOT = "/scratch/work/d097/mutants"
REL = "drive_tool/http_adapter.py"

# (name, category, old_substring, new_substring, test_class)
MUTANTS = [
    ("m1_framing_nonpost", "framing",
     '        if method != b"POST" or version != b"HTTP/1.1":\n',
     '        if version != b"HTTP/1.1":\n',
     "FramingRejectionTests"),

    ("m2_auth_missing_allowed", "auth",
     '        auths = headers.get(b"authorization", [])\n'
     '        if len(auths) != 1:\n'
     '            raise _ReqErrorSignal(403, "denied", False, False)\n',
     '        auths = headers.get(b"authorization", [])\n'
     '        if len(auths) != 1:\n'
     '            return content_length, None\n',
     "AuthFirstZeroFsTests"),

    ("m3_caps_wire_gate_removed", "caps",
     '        if endpoint == "save":\n'
     '            if content_length > MAX_SAVE_BODY_BYTES:\n'
     '                raise _ReqErrorSignal(413, "too_large", False, False)\n'
     '        else:\n'
     '            if content_length > MAX_JSON_BODY_BYTES:\n'
     '                raise _ReqErrorSignal(413, "too_large", False, False)\n',
     '        pass\n',
     "CapabilityBoundaryTests"),

    ("m4_close_not_idempotent", "once-only-close",
     '            if self._closed:\n                return True\n',
     '            if False:\n                return True\n',
     "CloseBudgetTests"),

    ("m5_close_ignores_deadline", "timed-close",
     '        remaining = deadline - time.monotonic()\n'
     '        if remaining <= 0.0:\n'
     '            acquired = self._close_lock.acquire(blocking=False)\n'
     '        else:\n'
     '            acquired = self._close_lock.acquire(timeout=remaining)\n',
     '        remaining = deadline - time.monotonic()\n'
     '        if remaining <= 0.0:\n'
     '            acquired = self._close_lock.acquire(blocking=False)\n'
     '        else:\n'
     '            time.sleep(0.5)\n'
     '            acquired = self._close_lock.acquire(timeout=remaining)\n',
     "CloseBudgetTests"),

    ("m6_busy_monolithic_preread", "busy-phase",
     '        pre_read_deadline = min(\n'
     '            now + BUSY_PRE_READ_BUDGET_SECONDS,\n'
     '            busy_deadline - BUSY_WRITE_RESERVE_SECONDS,\n'
     '        )\n'
     '        remaining = pre_read_deadline - time.monotonic()\n',
     '        remaining = busy_deadline - time.monotonic()\n',
     "BusyPhaseBudgetTests"),
]


def run_class(repo, cls, py):
    env = dict(os.environ, PYTHONPATH=repo)
    p = subprocess.run(
        [py, "-m", "unittest", "-v", "test_http_adapter.%s" % cls],
        cwd=os.path.join(repo, "tests"), env=env,
        capture_output=True, text=True, timeout=180,
    )
    out = p.stdout + p.stderr
    tail = out.strip().splitlines()[-1] if out.strip() else ""
    return p.returncode, tail, out


def main():
    results = []
    shutil.rmtree(MUT_ROOT, ignore_errors=True)
    os.makedirs(MUT_ROOT, exist_ok=True)
    src = os.path.join(CAND, REL)

    for py in ("python3.11", "python3.12"):
        # new pass: unmutated candidate
        for name, cat, old, new, cls in [("m0_clean", "clean", None, None, None)] + MUTANTS:
            pass

    # baseline (unmutated) per class per interpreter
    classes = sorted({m[4] for m in MUTANTS})
    baseline = {}
    for py in ("python3.11", "python3.12"):
        for cls in classes:
            rc, tail, out = run_class(CAND, cls, py)
            baseline[(py, cls)] = (rc, tail)
            print("BASELINE %-12s %-28s rc=%s %s" % (py, cls, rc, tail))
    print()

    for name, cat, old, new, cls in MUTANTS:
        repo = os.path.join(MUT_ROOT, name)
        shutil.rmtree(repo, ignore_errors=True)
        shutil.copytree(CAND, repo)
        path = os.path.join(repo, REL)
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        if text.count(old) != 1:
            print("ERROR %s: anchor count=%d" % (name, text.count(old)))
            continue
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text.replace(old, new))
        # compile-clean check (no syntax false positive)
        compile_ok = {}
        for py in ("python3.11", "python3.12"):
            cp = subprocess.run([py, "-c", "import py_compile,sys; py_compile.compile(sys.argv[1], doraise=True)", path],
                                capture_output=True, text=True)
            compile_ok[py] = (cp.returncode == 0)
        entry = {"name": name, "category": cat, "class": cls, "compile": compile_ok}
        for py in ("python3.11", "python3.12"):
            rc, tail, out = run_class(repo, cls, py)
            killed = (rc != 0)
            base_rc = baseline[(py, cls)][0]
            entry[py] = {"rc": rc, "tail": tail, "killed": killed,
                         "baseline_rc": base_rc,
                         "baseline_passed": base_rc == 0}
            print("%-26s %-9s %-12s rc=%s killed=%s base_rc=%s | %s"
                  % (name, cat, py, rc, killed, base_rc, tail))
        results.append(entry)
        print()

    with open("/scratch/work/d097/logs/mutation_battery.json", "w") as fh:
        json.dump(results, fh, indent=2)
    print("wrote mutation_battery.json")


if __name__ == "__main__":
    main()
