#!/usr/bin/env python3.12
"""Isolated semantic mutation runner for D054 (drive_tool/file_service.py).

For each mutation: copy the committed drive_tool/ + tests/ tree into a fresh
dir, apply a single semantic edit to file_service.py, and run the focused test
module under a bounded timeout. A mutation is CAUGHT when the focused tests
fail; ESCAPED when they still pass. Timeouts are recorded as failures, never
as passes.
"""
import hashlib
import os
import shutil
import subprocess
import sys

SRC = "/scratch/work/dt-work"
OUT = "/scratch/work/mutations"
PY = sys.executable

MUTATIONS = [
    (
        "M1_skip_grant_lookup",
        [("            grant = self._policy_table.authorize(agent.agent_id, source_id, operation)",
          "            grant = agent.grants[0]  # MUTANT: skip per-(agent,alias,op) grant lookup")],
        "tests.test_file_service",
    ),
    (
        "M2_alias_key_collision",
        [("                    key = (policy.agent_id, grant.alias)",
          "                    key = grant.alias  # MUTANT: key by alias only"),
         ("            binding = self._bindings.get((agent_id, alias))",
          "            binding = self._bindings.get(alias)  # MUTANT: alias-only lookup")],
        "tests.test_file_service",
    ),
    (
        "M3_invalid_option_reaches_io",
        [("    if type(value) is bool or not isinstance(value, int):\n        _raise_service_error(\"invalid\")\n    return int(value)",
          "    if not isinstance(value, int):  # MUTANT: bool accepted\n        _raise_service_error(\"invalid\")\n    return int(value)")],
        "tests.test_file_service",
    ),
    (
        "M4_dropped_save_uncertainty",
        [("            raise _translate_storage_exception(exc, is_write_in_flight=True) from None",
          "            raise _translate_storage_exception(exc, is_write_in_flight=False) from None  # MUTANT")],
        "tests.test_file_service",
    ),
    (
        "M5_close_ignores_active_leases",
        [("            while self._active_leases > 0 or self._closing_adapters:\n                if self._closed:\n                    return True\n                remaining = deadline - time.monotonic()\n                if remaining <= 0.0:\n                    return False\n                self._cond.wait(timeout=remaining)",
          "            pass  # MUTANT: close immediately, ignore active leases")],
        "tests.test_file_service",
    ),
    (
        "M6_always_create_parents",
        [("            if checked_create_parents:\n                built_parts: list[str] = []",
          "            if True:  # MUTANT: ignore create_parents flag\n                built_parts: list[str] = []")],
        "tests.test_file_service",
    ),
    (
        "M7_double_close",
        [("            while self._active_leases > 0 or self._closing_adapters:",
          "            while self._active_leases > 0:  # MUTANT: no in-progress-close guard"),
         ("                if not binding.closed:\n                    binding.closed = True",
          "                if True:  # MUTANT: no already-closed guard\n                    binding.closed = True")],
        "tests.test_file_service",
    ),
]


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    baseline_src = os.path.join(SRC, "drive_tool", "file_service.py")
    print("mutated-file baseline sha256:", sha256(baseline_src))
    summary = []
    for name, edits, module in MUTATIONS:
        work = os.path.join(OUT, name)
        os.makedirs(work)
        shutil.copytree(os.path.join(SRC, "drive_tool"), os.path.join(work, "drive_tool"))
        shutil.copytree(os.path.join(SRC, "tests"), os.path.join(work, "tests"))
        target = os.path.join(work, "drive_tool", "file_service.py")
        text = open(target).read()
        for old, new in edits:
            if text.count(old) != 1:
                print(f"{name}: SETUP ERROR, old_text occurs {text.count(old)} times")
                summary.append((name, "SETUP_ERROR", ""))
                break
            text = text.replace(old, new)
        else:
            open(target, "w").write(text)
            # compile check
            cc = subprocess.run([PY, "-m", "py_compile", target], capture_output=True, text=True)
            if cc.returncode != 0:
                print(f"{name}: MUTANT DOES NOT COMPILE\n{cc.stderr}")
                summary.append((name, "COMPILE_ERROR", ""))
                continue
            env = dict(os.environ, PYTHONPATH=work)
            try:
                proc = subprocess.run(
                    [PY, "-m", "unittest", module, "-v"],
                    cwd=work, env=env, capture_output=True, text=True, timeout=120,
                )
                out = proc.stdout + proc.stderr
                rc = proc.returncode
            except subprocess.TimeoutExpired as exc:
                out = (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
                rc = -1
                out += "\nTIMEOUT (recorded as failure, not pass)\n"
            log = os.path.join(OUT, f"{name}.log")
            open(log, "w").write(out)
            failed = [l.split(" ")[1] for l in out.splitlines() if l.startswith(("FAIL:", "ERROR:"))]
            status = "CAUGHT" if rc != 0 else "ESCAPED"
            print(f"{name}: {status} (rc={rc}) failing={sorted(set(failed))}")
            summary.append((name, status, ",".join(sorted(set(failed)))))
            continue
        # setup error path
    with open(os.path.join(OUT, "mutation-summary.txt"), "w") as fh:
        for name, status, failed in summary:
            fh.write(f"{name}\t{status}\t{failed}\n")
    print("SUMMARY")
    for row in summary:
        print("  ", row)


if __name__ == "__main__":
    main()
