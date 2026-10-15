#!/usr/bin/env python3
"""D058 independent backend audit - semantic mutation harness.

For each of the 7 semantic mutations, copy the published candidate tree to a
temp dir, apply the exact string edit(s) to drive_tool/file_service.py (asserting
each old string occurs exactly once), then run the focused suite:

    PYTHONPATH=. python3.<v> -m unittest -v tests.test_file_service

under a 120s timeout. A mutation is CAUGHT when the run FAILS (non-zero exit) or
times out; NOT-CAUGHT when the run passes. This harness is a reproduction run
only: it never edits the candidate tree in place.

Usage:
    python3 reproduce_mutations.py [--cand /path/to/candidate] [--out mutations.txt]
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

CAND_DEFAULT = "/scratch/work/cand"
TARGET = os.path.join("drive_tool", "file_service.py")
FOCUSED = ["-m", "unittest", "-v", "tests.test_file_service"]
PYTHONS = ["python3.11", "python3.12"]
TIMEOUT = 120

# (name, [(old, new), ...]) -- each old must occur exactly once in file_service.py
MUTATIONS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "M1_skip_grant_lookup",
        [
            (
                "            grant = self._policy_table.authorize(agent.agent_id, source_id, operation)\n",
                "            grant = agent.grants[0]\n",
            ),
        ],
    ),
    (
        "M2_alias_only_binding_key",
        [
            (
                "                    key = (policy.agent_id, grant.alias)\n",
                "                    key = (grant.alias,)\n",
            ),
            (
                "            binding = self._bindings.get((agent_id, alias))\n",
                "            binding = self._bindings.get((alias,))\n",
            ),
        ],
    ),
    (
        "M3_bool_accepted_as_int",
        [
            (
                "    if type(value) is bool or not isinstance(value, int):\n",
                "    if not isinstance(value, int):\n",
            ),
        ],
    ),
    (
        "M4_drop_save_uncertainty",
        [
            (
                "raise _translate_storage_exception(exc, is_write_in_flight=True) from None",
                "raise _translate_storage_exception(exc, is_write_in_flight=False) from None",
            ),
        ],
    ),
    (
        "M5_close_ignores_active_leases",
        [
            (
                "            while self._active_leases > 0 or self._closing_adapters:\n"
                "                if self._closed:\n"
                "                    return True\n"
                "                remaining = deadline - time.monotonic()\n"
                "                if remaining <= 0.0:\n"
                "                    return False\n"
                "                self._cond.wait(timeout=remaining)\n",
                "",
            ),
        ],
    ),
    (
        "M6_always_create_parents",
        [
            (
                "            if checked_create_parents:\n",
                "            if True:\n",
            ),
        ],
    ),
    (
        "M7_double_close",
        [
            (
                "        deadline = time.monotonic() + float(timeout)\n"
                "        with self._cond:\n"
                "            self._draining = True\n"
                "            if self._closed:\n"
                "                return True\n"
                "\n"
                "            while self._active_leases > 0 or self._closing_adapters:\n"
                "                if self._closed:\n"
                "                    return True\n"
                "                remaining = deadline - time.monotonic()\n"
                "                if remaining <= 0.0:\n"
                "                    return False\n"
                "                self._cond.wait(timeout=remaining)\n"
                "\n"
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
                "            self._closing_adapters = True\n",
            ),
            (
                "                if not binding.closed:\n",
                "                if True:\n",
            ),
        ],
    ),
]


def apply_edits(src_text: str, edits: list[tuple[str, str]], name: str) -> str:
    for old, new in edits:
        count = src_text.count(old)
        assert count == 1, (
            f"{name}: expected old string to occur exactly once, found {count}\n"
            f"--- old ---\n{old!r}"
        )
        src_text = src_text.replace(old, new)
    return src_text


def failing_tests(output: str) -> list[str]:
    names: list[str] = []
    for line in output.splitlines():
        stripped = line.rstrip()
        if stripped.endswith("... FAIL") or stripped.endswith("... ERROR"):
            names.append(stripped[: -len("... FAIL")].strip().rstrip("."))
    return names


def run_one(cand: str, pythons: list[str], timeout: int) -> list[dict]:
    rows: list[dict] = []
    for name, edits in MUTATIONS:
        for py in pythons:
            tmp = tempfile.mkdtemp(prefix=f"d058_{name}_")
            tree = os.path.join(tmp, "tree")
            try:
                shutil.copytree(cand, tree)
                target_path = os.path.join(tree, TARGET)
                with open(target_path, "r", encoding="utf-8") as fh:
                    src = fh.read()
                mutated = apply_edits(src, edits, name)
                with open(target_path, "w", encoding="utf-8") as fh:
                    fh.write(mutated)

                env = dict(os.environ)
                env["PYTHONPATH"] = "."
                cmd = [py, *FOCUSED]
                timed_out = False
                try:
                    proc = subprocess.run(
                        cmd,
                        cwd=tree,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                    )
                    out = proc.stdout + proc.stderr
                    exit_code = proc.returncode
                except subprocess.TimeoutExpired as exc:
                    timed_out = True
                    exit_code = None
                    out = ""
                    if exc.stdout:
                        out += exc.stdout if isinstance(exc.stdout, str) else exc.stdout.decode("utf-8", "replace")
                    if exc.stderr:
                        out += exc.stderr if isinstance(exc.stderr, str) else exc.stderr.decode("utf-8", "replace")

                if timed_out:
                    verdict = "CAUGHT"
                    fails = [f"TIMEOUT after {timeout}s"]
                elif exit_code != 0:
                    verdict = "CAUGHT"
                    fails = failing_tests(out) or [f"(non-zero exit {exit_code}; see raw output)"]
                else:
                    verdict = "NOT-CAUGHT"
                    fails = []

                rows.append(
                    {
                        "mutation": name,
                        "python": py,
                        "verdict": verdict,
                        "failing": fails,
                        "exit_code": exit_code,
                        "timed_out": timed_out,
                        "raw": out,
                    }
                )
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cand", default=CAND_DEFAULT)
    ap.add_argument("--out", default=None)
    ap.add_argument("--timeout", type=int, default=TIMEOUT)
    ap.add_argument("--pythons", default=",".join(PYTHONS))
    ap.add_argument("--append", action="store_true")
    args = ap.parse_args()

    pythons = [p.strip() for p in args.pythons.split(",") if p.strip()]
    cand = os.path.abspath(args.cand)
    lines: list[str] = []
    lines.append("D058 independent backend audit - semantic mutation results")
    lines.append(f"candidate tree: {cand}")
    lines.append(f"pythons: {', '.join(pythons)}  timeout: {args.timeout}s")
    lines.append("focused command: PYTHONPATH=. <python> -m unittest -v tests.test_file_service")
    lines.append("")
    lines.append("A timeout counts as CAUGHT.")
    lines.append("")

    rows = run_one(cand, pythons, args.timeout)

    # Summary table
    lines.append("=== TABLE (mutation | python | verdict | failing tests) ===")
    for r in rows:
        fails = "; ".join(r["failing"]) if r["failing"] else "-"
        lines.append(f"{r['mutation']} | {r['python']} | {r['verdict']} | {fails}")
    lines.append("")

    # Raw per-mutation failure lines
    lines.append("=== RAW PER-MUTATION OUTPUT ===")
    for r in rows:
        lines.append("")
        lines.append(f"----- {r['mutation']} / {r['python']} -> {r['verdict']} (exit={r['exit_code']}, timeout={r['timed_out']}) -----")
        lines.append("failing test names:")
        if r["failing"]:
            for f in r["failing"]:
                lines.append(f"  {f}")
        else:
            lines.append("  (none)")
        lines.append("--- raw stdout+stderr verbatim ---")
        lines.append(r["raw"].rstrip("\n"))
        lines.append("--- end raw ---")

    text = "\n".join(lines) + "\n"
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
