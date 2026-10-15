#!/usr/bin/env python3
"""Independent semantic mutation runner for D058 (fresh, not the builder's).

Copies the committed candidate tree per mutation, applies the mutation's
semantic edit(s) to drive_tool/file_service.py, verifies each edit applies
exactly once and the file still compiles, then runs the focused test module
under a bounded timeout. A timeout is recorded as a FAILURE, never a pass.
"""
import os
import shutil
import subprocess
import sys
import tempfile

CAND = "/scratch/work/candidate"
TARGET = "drive_tool/file_service.py"

# name -> list of (old, new) exact-string edits applied in order.
MUTATIONS = {
    "M1_skip_grant_lookup": [(
        "            agent = self._policy_table.authenticate(token)\n"
        "            grant = self._policy_table.authorize(agent.agent_id, source_id, operation)\n"
        "            return agent, grant\n",
        "            agent = self._policy_table.authenticate(token)\n"
        "            grant = agent.grants[0]\n"
        "            return agent, grant\n",
    )],
    "M2_alias_only_binding_key": [
        ("                    key = (policy.agent_id, grant.alias)\n",
         "                    key = (grant.alias,)\n"),
        ("            binding = self._bindings.get((agent_id, alias))\n",
         "            binding = self._bindings.get((alias,))\n"),
    ],
    "M3_bool_accepted_as_int": [(
        "    if type(value) is bool or not isinstance(value, int):\n"
        "        _raise_service_error(\"invalid\")\n"
        "    return int(value)\n",
        "    if not isinstance(value, int):\n"
        "        _raise_service_error(\"invalid\")\n"
        "    return int(value)\n",
    )],
    "M4_drop_save_uncertainty": [(
        "raise _translate_storage_exception(exc, is_write_in_flight=True) from None",
        "raise _translate_storage_exception(exc, is_write_in_flight=False) from None",
    )],
    "M5_close_ignores_active_leases": [(
        "            while self._active_leases > 0 or self._closing_adapters:\n"
        "                if self._closed:\n"
        "                    return True\n"
        "                remaining = deadline - time.monotonic()\n"
        "                if remaining <= 0.0:\n"
        "                    return False\n"
        "                self._cond.wait(timeout=remaining)\n",
        "",
    )],
    "M6_always_create_parents": [(
        "            if checked_create_parents:\n",
        "            if True:\n",
    )],
    "M7_double_close": [
        ("        deadline = time.monotonic() + float(timeout)\n"
         "        with self._cond:\n"
         "            self._draining = True\n"
         "            if self._closed:\n"
         "                return True\n\n"
         "            while self._active_leases > 0 or self._closing_adapters:\n"
         "                if self._closed:\n"
         "                    return True\n"
         "                remaining = deadline - time.monotonic()\n"
         "                if remaining <= 0.0:\n"
         "                    return False\n"
         "                self._cond.wait(timeout=remaining)\n\n"
         "            if self._closed:\n"
         "                return True\n"
         "            self._closing_adapters = True\n",
         "        deadline = time.monotonic() + float(timeout)\n"
         "        with self._cond:\n"
         "            self._draining = True\n"
         "            while self._active_leases > 0:\n"
         "                remaining = deadline - time.monotonic()\n"
         "                if remaining <= 0.0:\n"
         "                    return False\n"
         "                self._cond.wait(timeout=remaining)\n"
         "            self._closing_adapters = True\n"),
        ("                if not binding.closed:\n", "                if True:\n"),
    ],
}


def run_mutation(name, edits, pybin):
    work = tempfile.mkdtemp(prefix="mut_")
    tree = os.path.join(work, "tree")
    shutil.copytree(CAND, tree)
    path = os.path.join(tree, TARGET)
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    for old, new in edits:
        count = text.count(old)
        if count != 1:
            shutil.rmtree(work, ignore_errors=True)
            return name, pybin, f"SETUP-FAIL (old string count={count})"
        text = text.replace(old, new)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    chk = subprocess.run(
        [pybin, "-c", "import py_compile,sys; py_compile.compile(sys.argv[1], doraise=True)", path],
        capture_output=True, text=True)
    if chk.returncode != 0:
        shutil.rmtree(work, ignore_errors=True)
        return name, pybin, f"SETUP-FAIL (syntax: {chk.stderr.strip()[:160]})"
    env = dict(os.environ, PYTHONPATH=tree)
    try:
        proc = subprocess.run(
            [pybin, "-m", "unittest", "-v", "tests.test_file_service"],
            cwd=tree, env=env, capture_output=True, text=True, timeout=120)
        out = proc.stdout + proc.stderr
        if proc.returncode == 0:
            verdict = "NOT-CAUGHT"
        else:
            fails = sorted({ln.split(" ")[1] for ln in out.splitlines()
                            if ln.startswith(("FAIL:", "ERROR:"))})
            names = ",".join(f.split(" (")[0] for f in fails)
            verdict = f"CAUGHT rc={proc.returncode} failing=[{names}]"
    except subprocess.TimeoutExpired:
        verdict = "CAUGHT (TIMEOUT->failure)"
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return name, pybin, verdict


def main():
    pybins = [b for b in ("python3.11", "python3.12") if shutil.which(b)]
    print("MUTATION,PYTHON,VERDICT")
    for name, edits in MUTATIONS.items():
        for pybin in pybins:
            n, p, v = run_mutation(name, edits, pybin)
            print(f"{n},{p},{v}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
