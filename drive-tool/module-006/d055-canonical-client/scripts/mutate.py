"""D052 independent re-execution of the D047 builder mutations.

Applies each builder mutation to a private copy of the candidate tree,
compile-checks the mutant (proving the failure is semantic, not a syntax/import
error), then runs the D047 test file against the mutant.
"""
from __future__ import annotations
import os, shutil, subprocess, sys, py_compile

import os as _os
CAND = _os.environ.get("D052_TREE", "/scratch/work/candidate")
WORK = "/scratch/work/d052-mutants"
SRC = "drive_tool/service_client.py"
TESTS = "tests/test_service_client.py"

MUTATIONS = [
    ("M1_unbounded_reply_read", "read whole response instead of at most cap+1",
     "    data = resp.read(cap + 1)\n", "    data = resp.read()\n"),
    ("M2_lost_connection_close", "do not close connection on the way out",
     "                conn.close()\n", "                pass  # mutation: lost close\n"),
    ("M3_automatic_save_retry", "retry save automatically once on failure",
     ("        return self._dispatch(\n"
      '            "/v1/save?" + query,\n'
      "            data,\n"
      "            content_type=_READ_CONTENT_TYPE,\n"
      "            cap=_MAX_JSON_BODY,\n"
      '            mode="json",\n'
      "            write_op=True,\n"
      "        )\n"),
     ("        for _attempt in range(2):\n"
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
      "        return None\n")),
    ("M4_raw_remote_error_leakage", "embed remote message into error code",
     '    return DriveClientError(code, outcome_uncertain=uncertain, retry_safe=retry_safe)\n',
     '    return DriveClientError(code + ":" + str(error.get("message", "")), outcome_uncertain=uncertain, retry_safe=retry_safe)\n'),
    ("M5_cross_request_connection_reuse", "cache and reuse one HTTPConnection across calls",
     "        return http.client.HTTPConnection(_HOST, self._port, timeout=self._timeout)\n",
     ("        cached = getattr(self, \"_cached_conn\", None)\n"
      "        if cached is None:\n"
      "            cached = http.client.HTTPConnection(_HOST, self._port, timeout=self._timeout)\n"
      "            self._cached_conn = cached\n"
      "        return cached\n")),
    ("M6_wrong_eof_handling", "accept exact-fill window that claims eof_observed",
     ("    if received == request_length and eof_observed:\n"
      "        raise _ProtocolError()\n"),
     "    pass  # mutation: wrong EOF handling\n"),
    ("M7_revert_body_transport_fix", "revert D053 mid-body transport mapping",
     ("        except _TRANSPORT_ERRORS as exc:\n"
      "            # A transport failure while reading the response body (stall,\n"
      "            # truncation, reset or malformed chunk) must also become a safe\n"
      "            # DriveClientError with the conservative write/read uncertainty.\n"
      "            raise _wrap_transport(exc, write_op=write_op) from None\n"),
     ""),
    ("M8_remove_prefix_enforcement", "drop the mandatory 'p/' canonical prefix check",
     ("    if not file_id.startswith(_CANONICAL_PREFIX):\n"
      "        raise ValueError(\"non-root file_id must start with 'p/'\")\n"),
     "    pass  # mutation: prefix enforcement removed\n"),
]

def run(interp):
    print(f"===== {interp} =====")
    rows = []
    for name, desc, old, new in MUTATIONS:
        work = os.path.join(WORK, interp.replace(".", "_"), name)
        shutil.rmtree(work, ignore_errors=True)
        shutil.copytree(CAND, work, ignore=shutil.ignore_patterns(".git"))
        path = os.path.join(work, SRC)
        src = open(path, encoding="utf-8").read()
        n = src.count(old)
        if n != 1:
            rows.append((name, "SETUP-ERROR", f"anchor count={n}"))
            continue
        open(path, "w", encoding="utf-8").write(src.replace(old, new))
        # compile check -> semantic, not syntax
        try:
            py_compile.compile(path, doraise=True)
            compiles = True
        except py_compile.PyCompileError as e:
            compiles = False
            rows.append((name, "SYNTAX-ERROR", str(e)[:60]))
            continue
        proc = subprocess.run([interp, "-m", "unittest", "tests.test_service_client"],
                              cwd=work, capture_output=True, text=True)
        out = proc.stdout + "\n" + proc.stderr
        failed = [l for l in out.splitlines() if l.startswith("FAIL: ") or l.startswith("ERROR: ")]
        caught = proc.returncode != 0
        rows.append((name, "CAUGHT" if caught else "NOT-CAUGHT", f"{len(failed)} failing; compiles={compiles}"))
        os.makedirs(os.path.join(WORK, "logs"), exist_ok=True)
        open(os.path.join(WORK, "logs", f"{name}.{interp}.log"), "w").write(out)
    for r in rows:
        print("  ", ",".join(r))
    return rows

if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "python3.12")
