"""D053 mutation runner.

Each mutation is applied to an ISOLATED COPY of the final NEW candidate tree
(never the committed candidate); the focused client test module is run on
3.11 and 3.12 and the copy is discarded. CAUGHT = the suite fails.
"""
import os
import shutil
import subprocess

SRC = "/scratch/repos/drive-tool-d053"
WORK = "/scratch/work/mutants-d053"
LOGS = "/scratch/work/d053/logs/mutations"
SRC_FILE = "drive_tool/service_client.py"

MUTATIONS = [
    # --- the six original D047-equivalent mutants -------------------------
    ("M1_unbounded_reply_read", SRC_FILE,
     "    data = resp.read(cap + 1)\n",
     "    data = resp.read()\n",
     "bounded reply read (never read unbounded)"),

    ("M2_lost_connection_close", SRC_FILE,
     "            try:\n"
     "                conn.close()\n"
     "            except Exception:  # noqa: BLE001 - best-effort cleanup\n"
     "                pass\n",
     "            pass  # mutation: connection close removed\n",
     "connection closed every call"),

    ("M3_automatic_save_retry", SRC_FILE,
     "        return self._dispatch(\n"
     "            \"/v1/save?\" + query,\n"
     "            data,\n"
     "            content_type=_READ_CONTENT_TYPE,\n"
     "            cap=_MAX_JSON_BODY,\n"
     "            mode=\"json\",\n"
     "            write_op=True,\n"
     "        )\n",
     "        for _attempt in range(2):\n"
     "            try:\n"
     "                return self._dispatch(\n"
     "                    \"/v1/save?\" + query,\n"
     "                    data,\n"
     "                    content_type=_READ_CONTENT_TYPE,\n"
     "                    cap=_MAX_JSON_BODY,\n"
     "                    mode=\"json\",\n"
     "                    write_op=True,\n"
     "                )\n"
     "            except DriveClientError:\n"
     "                if _attempt == 1:\n"
     "                    raise\n"
     "        raise AssertionError(\"unreachable\")\n",
     "no automatic retry on save"),

    ("M4_raw_remote_error_leak", SRC_FILE,
     "    return DriveClientError(code, outcome_uncertain=uncertain, retry_safe=retry_safe)\n",
     "    _leak = error.get(\"message\")\n"
     "    return DriveClientError(\n"
     "        code if not isinstance(_leak, str) else _leak,\n"
     "        outcome_uncertain=uncertain,\n"
     "        retry_safe=retry_safe,\n"
     "    )\n",
     "raw remote error text never leaks"),

    ("M5_cross_request_reuse", SRC_FILE,
     "        return http.client.HTTPConnection(_HOST, self._port, timeout=self._timeout)\n",
     "        conn = getattr(self, \"_cached\", None)\n"
     "        if conn is None:\n"
     "            conn = http.client.HTTPConnection(_HOST, self._port, timeout=self._timeout)\n"
     "            self._cached = conn\n"
     "        return conn\n",
     "a fresh connection per call (no reuse)"),

    ("M6_wrong_eof_handling", SRC_FILE,
     "    if received == request_length and eof_observed:\n"
     "        raise _ProtocolError()\n",
     "    pass  # mutation: exact-fill EOF check removed\n",
     "exact-fill window is not EOF"),

    # --- precise revert of the D053 new fix -------------------------------
    ("M7_revert_body_transport_fix", SRC_FILE,
     "        except DriveClientError:\n"
     "            # Already a safe local error (for example a parsed error envelope):\n"
     "            # propagate it unchanged rather than remapping it.\n"
     "            raise\n"
     "        except _TRANSPORT_ERRORS as exc:\n"
     "            # A transport failure while reading the response body (stall,\n"
     "            # truncation, reset or malformed chunk) must also become a safe\n"
     "            # DriveClientError with the conservative write/read uncertainty.\n"
     "            raise _wrap_transport(exc, write_op=write_op) from None\n",
     "",  # cleanly delete the added clauses (no pass-before-finally)
     "body transport errors map to a safe DriveClientError"),
]


def run(root, py):
    return subprocess.run(
        [py, "-m", "unittest", "tests.test_service_client", "-v"],
        cwd=root, capture_output=True, text=True,
    )


def main():
    os.makedirs(WORK, exist_ok=True)
    os.makedirs(LOGS, exist_ok=True)
    for name, relpath, old, new, intended in MUTATIONS:
        dest = os.path.join(WORK, name)
        if os.path.exists(dest):
            shutil.rmtree(dest)
        shutil.copytree(SRC, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        path = os.path.join(dest, relpath)
        text = open(path, encoding="utf-8").read()
        if text.count(old) != 1:
            print(f"{name}: APPLY_FAILED (matched {text.count(old)})")
            continue
        open(path, "w", encoding="utf-8").write(text.replace(old, new))

        results = {}
        for py in ("python3.11", "python3.12"):
            r = run(dest, py)
            combined = r.stdout + r.stderr
            open(os.path.join(LOGS, f"{name}.{py}.log"), "w", encoding="utf-8").write(combined)
            failed = [ln.split(" ")[1] for ln in combined.splitlines()
                      if ln.startswith("FAIL:") or ln.startswith("ERROR:")]
            lines = [ln for ln in combined.strip().splitlines() if ln.strip()]
            results[py] = {"exit": r.returncode, "failed": failed,
                           "last": lines[-1] if lines else "(none)"}
        caught = all(v["exit"] != 0 for v in results.values())
        print(f"{name}: {'CAUGHT' if caught else 'SURVIVED'}  (intended: {intended})")
        for py, v in results.items():
            print(f"    {py}: exit={v['exit']} | {v['last']} | {v['failed']}")
        shutil.rmtree(dest)


if __name__ == "__main__":
    main()
