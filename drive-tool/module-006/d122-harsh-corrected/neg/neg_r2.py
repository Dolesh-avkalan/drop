#!/usr/bin/env python3
"""D122 R2 negatives.

mode=normal : corrected payload, R2 must PASS with vm_kb_before/ballast/peak
              and mem_error == "MemoryError".
mode=nomem  : the child never raises MemoryError -> R2 (and the stage) must FAIL.
"""
import os, sys, json, importlib.util

REPO = "/scratch/work/src/drive-tool-337e4c713829af76615472eb47b81244ff399528"
CORRECTED = "/scratch/work/d122/harsh_checks_d110.corrected.py"
sys.path.insert(0, REPO)

spec = importlib.util.spec_from_file_location("d122p", CORRECTED)
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "normal"
    if mode == "nomem":
        old = ('    mem_error = None\n'
               '    grow = bytearray()\n'
               '    try:\n'
               '        for _ in range(200):\n'
               '            grow.extend(b"\\x00" * (8 * 1024 * 1024))\n'
               '    except MemoryError:\n'
               '        mem_error = "MemoryError"\n')
        assert P._R2_CHILD_SRC.count(old) == 1, "grow block not found"
        # keep `grow` defined so the child still runs; only skip the allocation
        P._R2_CHILD_SRC = P._R2_CHILD_SRC.replace(old, '    mem_error = None\n    grow = bytearray()\n')
        print("nomem mutant applied (child never raises MemoryError)")
    rp = P.stage_resource_pressure(REPO, 300.0)
    print("stage result:", rp.get("result"))
    print("R2:", json.dumps(rp.get("R2_memory_pressure"), default=str))
    print("R1 ok:", (rp.get("R1_cpu_saturation") or {}).get("ok"))
    print("R3:", {k: (rp.get("R3_emfile") or {}).get(k) for k in ("result", "mapped", "raw", "recovery_ok")})
    print("problems:", rp.get("problems"))


if __name__ == "__main__":
    main()
