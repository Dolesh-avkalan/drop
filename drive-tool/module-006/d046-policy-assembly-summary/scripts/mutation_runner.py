"""D046 mutation runner.

Each mutation is applied to an ISOLATED COPY of the final assembled tree
(never the committed candidate), the focused policy test module is run on
Python 3.11 and 3.12, and the copy is discarded. A mutation is CAUGHT when
the suite fails; SURVIVED when it stays green. Mutants are never committed.
"""
import os
import shutil
import subprocess
import sys

SRC = "/scratch/repos/drive-tool"
WORK = "/scratch/work/mutants"
LOGS = "/scratch/work/logs/mutations"

POLICY = "drive_tool/service_policy.py"
TESTS = "tests/test_service_policy.py"

# (name, relpath, old, new, intended_caught)
MUTATIONS = [
    ("M1_early_auth_return", POLICY,
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
     "test_compares_all_digests_no_early_return"),

    ("M2_duplicate_digest_acceptance", POLICY,
     "            if agent.token_sha256 in seen_digests:\n"
     "                raise ValueError('duplicate token digest')\n",
     "            if False and agent.token_sha256 in seen_digests:\n"
     "                raise ValueError('duplicate token digest')\n",
     "test_duplicate_token_digest_rejected"),

    ("M3_cross_agent_alias_fallback", POLICY,
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
     "test_same_alias_across_agents_isolated / test_unknown_agent_denied"),

    ("M4_readonly_save_bypass", POLICY,
     "                if grant.alias == source_alias:\n"
     "                    if operation in grant.operations:\n"
     "                        return grant\n"
     "                    raise PolicyDeniedError()\n",
     "                if grant.alias == source_alias:\n"
     "                    return grant\n",
     "test_read_only_denies_save / test_save_only_denies_read / test_caps_do_not_grant_absent_operations"),

    ("M5_malformed_root_acceptance", POLICY,
     "    if '\\x00' in value:\n"
     "        raise ValueError('root must not contain NUL')\n"
     "    if '\\\\' in value:\n"
     "        raise ValueError('root must not contain backslash')\n",
     "    pass\n",
     "test_root_nul_rejected / test_root_backslash_rejected"),

    ("M6_cap_upper_bound_bypass", POLICY,
     "    if value < 1 or value > MAX_TRANSFER_BYTES:\n"
     "        raise ValueError(f'{name} out of range')\n",
     "    if value < 1:\n"
     "        raise ValueError(f'{name} out of range')\n",
     "test_cap_too_large_rejected"),
]


def run_suite(root, py):
    return subprocess.run(
        [py, "-m", "unittest", "tests.test_service_policy", "-v"],
        cwd=root, capture_output=True, text=True,
    )


def main():
    os.makedirs(WORK, exist_ok=True)
    os.makedirs(LOGS, exist_ok=True)
    report = []
    for name, relpath, old, new, intended in MUTATIONS:
        dest = os.path.join(WORK, name)
        if os.path.exists(dest):
            shutil.rmtree(dest)
        shutil.copytree(SRC, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

        path = os.path.join(dest, relpath)
        text = open(path, encoding="utf-8").read()
        count = text.count(old)
        if count != 1:
            report.append((name, "APPLY_FAILED", f"old text matched {count} times", intended))
            print(f"{name}: APPLY_FAILED (matched {count})")
            continue
        open(path, "w", encoding="utf-8").write(text.replace(old, new))

        results = {}
        for py in ("python3.11", "python3.12"):
            r = run_suite(dest, py)
            combined = r.stdout + r.stderr
            log = os.path.join(LOGS, f"{name}.{py}.log")
            open(log, "w", encoding="utf-8").write(combined)
            lines = [ln for ln in combined.strip().splitlines() if ln.strip()]
            last = lines[-1] if lines else "(no output)"
            failed_names = []
            for ln in combined.splitlines():
                if ln.startswith("FAIL:") or ln.startswith("ERROR:"):
                    failed_names.append(ln.split(" ")[1])
            results[py] = {"exit": r.returncode, "last": last, "failed": failed_names}
        caught = all(v["exit"] != 0 for v in results.values())
        status = "CAUGHT" if caught else "SURVIVED"
        report.append((name, status, results, intended))
        print(f"{name}: {status}")
        for py, v in results.items():
            print(f"    {py}: exit={v['exit']} | {v['last']} | failed={v['failed']}")
        shutil.rmtree(dest)

    print("\n=== SUMMARY ===")
    for name, status, detail, intended in report:
        print(f"{name}: {status}  (intended: {intended})")


if __name__ == "__main__":
    main()
