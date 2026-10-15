"""Focused isolated mutation checks for drive_tool.service_client (D047).

Each mutation is applied to a private copy of the repository; the D047 test
file is then run against the mutant. A mutation is "caught" when the suite
fails (non-zero exit). Raw logs are written next to this script.

Run:  python3.12 run_mutations.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

BASE = "/scratch/repos/drive-tool"
OUT = "/scratch/work/d047-evidence/mutations"
SRC = "drive_tool/service_client.py"

MUTATIONS = [
    (
        "M1_unbounded_reply_read",
        "read the whole response instead of at most cap+1",
        "    data = resp.read(cap + 1)\n",
        "    data = resp.read()\n",
    ),
    (
        "M2_lost_connection_close",
        "do not close the connection on the way out",
        "                conn.close()\n",
        "                pass  # mutation: lost close\n",
    ),
    (
        "M3_automatic_save_retry",
        "retry save automatically once on failure",
        (
            "        return self._dispatch(\n"
            '            "/v1/save?" + query,\n'
            "            data,\n"
            "            content_type=_READ_CONTENT_TYPE,\n"
            "            cap=_MAX_JSON_BODY,\n"
            '            mode="json",\n'
            "            write_op=True,\n"
            "        )\n"
        ),
        (
            "        for _attempt in range(2):\n"
            "            try:\n"
            "                return self._dispatch(\n"
            '                    "/v1/save?" + query,\n'
            "                    data,\n"
            "                    content_type=_READ_CONTENT_TYPE,\n"
            "                    cap=_MAX_JSON_BODY,\n"
            '                    mode="json",\n'
            "                    write_op=True,\n"
            "                )\n"
            "            except DriveClientError:\n"
            "                pass\n"
            "        return None\n"
        ),
    ),
    (
        "M4_raw_remote_error_leakage",
        "embed the remote error message into the error code",
        "    return DriveClientError(code, outcome_uncertain=uncertain, retry_safe=retry_safe)\n",
        "    return DriveClientError(code + \":\" + str(error.get(\"message\", \"\")), "
        "outcome_uncertain=uncertain, retry_safe=retry_safe)\n",
    ),
    (
        "M5_cross_request_connection_reuse",
        "cache and reuse one HTTPConnection across calls",
        "        return http.client.HTTPConnection(_HOST, self._port, timeout=self._timeout)\n",
        (
            "        cached = getattr(self, \"_cached_conn\", None)\n"
            "        if cached is None:\n"
            "            cached = http.client.HTTPConnection(_HOST, self._port, timeout=self._timeout)\n"
            "            self._cached_conn = cached\n"
            "        return cached\n"
        ),
    ),
    (
        "M6_wrong_eof_handling",
        "accept an exact-fill window that claims eof_observed",
        (
            "    if received == request_length and eof_observed:\n"
            "        raise _ProtocolError()\n"
        ),
        "    pass  # mutation: wrong EOF handling\n",
    ),
]


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    results = []
    for name, description, old, new in MUTATIONS:
        work = os.path.join("/scratch/work/d047-mutants", name)
        shutil.rmtree(work, ignore_errors=True)
        shutil.copytree(BASE, work, ignore=shutil.ignore_patterns(".git"))
        path = os.path.join(work, SRC)
        with open(path, "r", encoding="utf-8") as handle:
            source = handle.read()
        count = source.count(old)
        if count != 1:
            results.append((name, "SETUP-ERROR", "anchor count=%d" % count))
            continue
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(source.replace(old, new))

        proc = subprocess.run(
            [sys.executable, "-m", "unittest", "tests.test_service_client"],
            cwd=work,
            capture_output=True,
            text=True,
        )
        with open(os.path.join(OUT, name + ".log"), "w", encoding="utf-8") as handle:
            handle.write(proc.stdout)
            handle.write(proc.stderr)
        caught = proc.returncode != 0
        combined = proc.stdout + "\n" + proc.stderr
        failed = [
            line.split(" ")[1]
            for line in combined.splitlines()
            if line.startswith("FAIL: ") or line.startswith("ERROR: ")
        ]
        results.append(
            (name, "CAUGHT" if caught else "NOT-CAUGHT", "%d failing test(s)" % len(failed))
        )

    print("mutation,result,detail")
    for row in results:
        print(",".join(row))
    return 0 if all(r[1] == "CAUGHT" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
