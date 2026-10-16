#!/usr/bin/env python3
"""Apply the exact D078 patch to the D072 corrected runner (v2).

Only runner/run_cloud_stress.py is touched. Four textual regions are replaced,
matching the four hunks of d078-runner-two-fixes.md. Raw strings are used so
literal backslash-n sequences inside the embedded repro are preserved exactly.
"""
import difflib
import hashlib
import sys

SRC = "/scratch/work/d082/d082bundle/runner/run_cloud_stress.py"

with open(SRC, "r") as fh:
    text = fh.read()
orig = text

# ---- hunk 1: help string ---------------------------------------------------
old1 = (
    '    ap.add_argument("--base-dir", default="/tmp",\n'
    '                    help="where to create the unique workspace (must resolve under /tmp)")\n'
)
new1 = (
    '    ap.add_argument("--base-dir", default="/tmp",\n'
    '                    help="where to create the unique workspace (must resolve to /tmp or under /tmp/)")\n'
)
assert text.count(old1) == 1, ("hunk1", text.count(old1))
text = text.replace(old1, new1)

# ---- hunk 2: containment condition -----------------------------------------
old2 = (
    '        if real_base == "/tmp" or not real_base.startswith("/tmp/"):\n'
    '            log(f"FATAL: --base-dir must resolve under /tmp/ (got {real_base!r})")\n'
)
new2 = (
    '        if real_base != "/tmp" and not real_base.startswith("/tmp/"):\n'
    '            log(f"FATAL: --base-dir must resolve to /tmp or under /tmp/ (got {real_base!r})")\n'
)
assert text.count(old2) == 1, ("hunk2", text.count(old2))
text = text.replace(old2, new2)

# ---- hunk 3: DUAL_ORDER_REPRO body (index-sliced old, raw new) -------------
start_marker = "DUAL_ORDER_REPRO = r'''\n"
end_marker = "'''\n\ndef run_dual_order_repro("
i = text.index(start_marker) + len(start_marker)
j = text.index(end_marker, i)
old3 = text[i:j]          # exact, taken from the file

new3 = r'''import importlib
import os
import sys
import unittest

MODE = sys.argv[1]        # "asc" or "desc"
SRC = sys.argv[2]
TESTNAME = sys.argv[3]
REVERSE = (MODE == "desc")

sys.path.insert(0, SRC)
os.chdir(SRC)

# Import the test module normally first: its LocalAdapter feature detection must
# see the real os.scandir so the test is actually collected and run.
MODNAME = TESTNAME.rsplit(".", 1)[0]
importlib.import_module(MODNAME)

# Apply the order override only to the adapter scan seam, after feature
# detection, so file-descriptor support remains intact.
import drive_tool.local as local

_attr = local.LocalAdapter.__dict__.get("_os_scandir")
if _attr is None:
    raise RuntimeError("LocalAdapter._os_scandir seam not found")

def _iter_from(entries):
    class _Iter:
        def __init__(self, items):
            self._it = iter(items)
        def __iter__(self):
            return self
        def __next__(self):
            return next(self._it)
        def close(self):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
    return _Iter(entries)

def _ordered(entries):
    return sorted(entries, key=lambda e: getattr(e, "name", e), reverse=REVERSE)

if isinstance(_attr, staticmethod):
    _orig = _attr.__func__
    def _shim(path="."):
        return _iter_from(_ordered(list(_orig(path))))
    local.LocalAdapter._os_scandir = staticmethod(_shim)
elif isinstance(_attr, classmethod):
    _orig = _attr.__func__
    def _shim(cls, path="."):
        return _iter_from(_ordered(list(_orig(cls, path))))
    local.LocalAdapter._os_scandir = classmethod(_shim)
else:
    _orig = _attr
    def _shim(self, path="."):
        return _iter_from(_ordered(list(_orig(self, path))))
    local.LocalAdapter._os_scandir = _shim

loader = unittest.TestLoader()
suite = loader.loadTestsFromName(TESTNAME)
runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
result = runner.run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
'''
text = text[:i] + new3 + text[j:]

# ---- hunk 4: run_dual_order_repro body (index-sliced old, raw new) ---------
start4 = '    results = {}\n    for mode in ("asc", "desc"):'
end4 = "    return results, confirmed\n"
i4 = text.index(start4)
j4 = text.index(end4, i4) + len(end4)
old4 = text[i4:j4]        # exact, taken from the file

new4 = r'''    results = {}
    for mode in ("asc", "desc"):
        r = run([py_path, script_path, mode, src, ORDER_SENSITIVE_TEST],
                cwd=src, env=env, timeout=timeout)
        parsed = parse_unittest(r["out"] + r["err"])
        r.update(parsed)
        with open(os.path.join(ws, "logs", f"dual_order_{mode}.out"), "w") as fh:
            fh.write(f"$ {' '.join(r['cmd'])}\n\n{r['out']}\n--- stderr ---\n{r['err']}\n")
            fh.write(f"EXIT={r['rc']} timed_out={r['timed_out']} seconds={r['seconds']}\n")
            fh.write(f"ran={r['ran']} skipped={r['skipped']} ok={r['ok']} failed={r['failed']}\n")
        results[mode] = {"rc": r["rc"], "timed_out": r["timed_out"],
                         "seconds": r["seconds"], "ran": r["ran"],
                         "skipped": r["skipped"], "ok": r["ok"],
                         "failed": r["failed"]}
    asc = results["asc"]
    desc = results["desc"]
    confirmed = (
        asc["rc"] == 0
        and asc["ran"] == 1
        and asc["skipped"] == 0
        and asc["ok"]
        and not asc["timed_out"]
        and desc["rc"] not in (0, None)
        and desc["ran"] == 1
        and desc["skipped"] == 0
        and desc["failed"]
        and not desc["timed_out"]
    )
    return results, confirmed
'''
text = text[:i4] + new4 + text[j4:]

with open(SRC, "w") as fh:
    fh.write(text)

print("old bytes:", len(orig))
print("new bytes:", len(text))
print("new sha256:", hashlib.sha256(text.encode()).hexdigest())
print("hunk3 old len:", len(old3), "new len:", len(new3))
print("hunk4 old len:", len(old4), "new len:", len(new4))
print()
diff = difflib.unified_diff(orig.splitlines(True), text.splitlines(True),
                            fromfile="a/runner/run_cloud_stress.py",
                            tofile="b/runner/run_cloud_stress.py", n=0)
sys.stdout.writelines(diff)
