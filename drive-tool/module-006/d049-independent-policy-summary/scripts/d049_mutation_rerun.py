"""D049 independent mutation re-runner.

Applies each of the six D046 mutations to an ISOLATED copy of the candidate
tree, then, for each mutant, verifies:
  (a) the mutant source still COMPILES and IMPORTS (no syntax/import fake catch),
  (b) the focused policy suite FAILS (exit != 0),
  (c) the intended test(s) are among the failures,
  (d) at least one failure is a real assertion failure (AssertionError / assertRaises),
      i.e. the catch is semantic, not an accidental import/attribute error.
The mutant copy is discarded. Mutants are never written into the candidate.
"""
from __future__ import annotations

import os
import py_compile
import shutil
import subprocess
import sys

SRC = "/scratch/work/d049/candidate"
WORK = "/scratch/work/d049/mutants"
LOGS = "/scratch/work/d049/logs/mutations"

POLICY = "drive_tool/service_policy.py"

# (name, old, new, intended_test_substrings)
MUTATIONS = [
    ("M1_early_auth_return",
     "        match: AgentPolicy | None = None\n"
     "        for agent, stored in zip(self._agents, self._digests):\n"
     "            if hmac.compare_digest(candidate, stored):\n"
     "                match = agent\n"
     "        if match is None:\n"
     "            raise PolicyDeniedError()\n"
     "        return match\n",
     "        for agent, stored in zip(self._agents, self._digests):\n"
     "            if hmac.compare_digest(candidate, stored):\n"
     "                return agent\n"
     "        raise PolicyDeniedError()\n",
     ["test_compares_all_digests_no_early_return"]),

    ("M2_duplicate_digest_acceptance",
     "            if agent.token_sha256 in seen_digests:\n"
     "                raise ValueError('duplicate token digest')\n",
     "            if False and agent.token_sha256 in seen_digests:\n"
     "                raise ValueError('duplicate token digest')\n",
     ["test_duplicate_token_digest_rejected"]),

    ("M3_cross_agent_alias_fallback",
     "            agent = self._by_id.get(agent_id)\n"
     "            if agent is None:\n"
     "                raise PolicyDeniedError()\n"
     "            for grant in agent.grants:\n"
     "                if grant.alias == source_alias:\n"
     "                    if operation in grant.operations:\n"
     "                        return grant\n"
     "                    raise PolicyDeniedError()\n"
     "            raise PolicyDeniedError()\n",
     "            agent = self._by_id.get(agent_id)\n"
     "            if agent is None:\n"
     "                raise PolicyDeniedError()\n"
     "            for other in self._agents:\n"
     "                for grant in other.grants:\n"
     "                    if grant.alias == source_alias and operation in grant.operations:\n"
     "                        return grant\n"
     "            raise PolicyDeniedError()\n",
     ["test_same_alias_across_agents_isolated"]),

    ("M4_readonly_save_bypass",
     "                if grant.alias == source_alias:\n"
     "                    if operation in grant.operations:\n"
     "                        return grant\n"
     "                    raise PolicyDeniedError()\n",
     "                if grant.alias == source_alias:\n"
     "                    return grant\n",
     ["test_read_only_denies_save", "test_save_only_denies_read",
      "test_caps_do_not_grant_absent_operations"]),

    ("M5_malformed_root_acceptance",
     "    if '\\x00' in value:\n"
     "        raise ValueError('root must not contain NUL')\n"
     "    if '\\\\' in value:\n"
     "        raise ValueError('root must not contain backslash')\n",
     "    pass\n",
     ["test_root_nul_rejected", "test_root_backslash_rejected"]),

    ("M6_cap_upper_bound_bypass",
     "    if value < 1 or value > MAX_TRANSFER_BYTES:\n"
     "        raise ValueError(f'{name} out of range')\n",
     "    if value < 1:\n"
     "        raise ValueError(f'{name} out of range')\n",
     ["test_cap_too_large_rejected"]),
]


def run_policy(root, py):
    return subprocess.run(
        [py, "-m", "unittest", "tests.test_service_policy", "-v"],
        cwd=root, capture_output=True, text=True,
    )


def main():
    os.makedirs(WORK, exist_ok=True)
    os.makedirs(LOGS, exist_ok=True)
    overall_ok = True
    for name, old, new, intended in MUTATIONS:
        dest = os.path.join(WORK, name)
        if os.path.exists(dest):
            shutil.rmtree(dest)
        shutil.copytree(SRC, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        path = os.path.join(dest, POLICY)
        text = open(path, encoding="utf-8").read()
        n = text.count(old)
        if n != 1:
            print(f"{name}: APPLY_FAILED (matched {n})")
            overall_ok = False
            continue
        open(path, "w", encoding="utf-8").write(text.replace(old, new))

        # (a) compiles + imports
        compiles = True
        try:
            py_compile.compile(path, doraise=True)
        except py_compile.PyCompileError as e:
            compiles = False
        imp = subprocess.run([sys.executable, "-c", "import drive_tool.service_policy"],
                             cwd=dest, capture_output=True, text=True)
        imports = imp.returncode == 0

        row = {"compiles": compiles, "imports": imports, "runs": {}}
        for py in ("python3.11", "python3.12"):
            r = run_policy(dest, py)
            out = r.stdout + r.stderr
            open(os.path.join(LOGS, f"{name}.{py}.log"), "w", encoding="utf-8").write(out)
            failed = [ln.split(" ")[1] for ln in out.splitlines()
                      if ln.startswith("FAIL:") or ln.startswith("ERROR:")]
            ftype = []
            for ln in out.splitlines():
                if "AssertionError" in ln:
                    ftype.append("AssertionError")
                if "SyntaxError" in ln or "ImportError" in ln or "ModuleNotFoundError" in ln:
                    ftype.append("SYNTAX_IMPORT")
            row["runs"][py] = {"exit": r.returncode, "failed": failed, "ftype": ftype}

        intended_hit = all(
            any(i in f for f in row["runs"][py]["failed"]) for py in row["runs"] for i in intended
        )
        all_fail = all(v["exit"] != 0 for v in row["runs"].values())
        semantic = all(("AssertionError" in v["ftype"]) and ("SYNTAX_IMPORT" not in v["ftype"])
                       for v in row["runs"].values())
        caught = compiles and imports and all_fail and intended_hit and semantic
        status = "CAUGHT" if caught else "PROBLEM"
        if not caught:
            overall_ok = False
        print(f"{name}: {status} | compiles={compiles} imports={imports} "
              f"intended_hit={intended_hit} semantic={semantic}")
        for py, v in row["runs"].items():
            print(f"    {py}: exit={v['exit']} failed={v['failed']} ftype={sorted(set(v['ftype']))}")
        shutil.rmtree(dest)

    print("\n=== INDEPENDENT MUTATION SUMMARY:", "ALL 6 CAUGHT (semantic)" if overall_ok else "PROBLEM", "===")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
