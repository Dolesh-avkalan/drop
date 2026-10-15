# d078 (deepseek)

- status: done
- chat: https://chat.deepseek.com/a/chat/s/1f84891e-3244-44a0-ad98-75ef63a3cc1a
- model: deepseek (deepthink on, search off)
- finished: 2026-10-15T23:03:36Z

## Question

DeepSeek, minimal diff only for two D072-confirmed runner defects. Preserve17passingnegativegates/pins, default /tmp base allowed but workspace strictly descendant, dual-order test must actually execute no skips with intact fd support. No full rewrite/source edits/merge/deploy. Honest TESTS_NOT_RUN and oldfail/newpass plan.

(input files: Dolesh-avkalan/drive-tool:tasks/d078-runner-two-fixes.txt@eab4935bd73c6017a47267ae43e08284b44ea0d7)

## Answer

Minimal unified diff for runner/run_cloud_stress.py only. No source-under-test edits, no payload/pin/identity changes, no merge/deploy. I have not executed anything here: TESTS_NOT_RUN.

```diff
--- a/runner/run_cloud_stress.py
+++ b/runner/run_cloud_stress.py
@@
     ap.add_argument("--base-dir", default="/tmp",
-                    help="where to create the unique workspace (must resolve under /tmp)")
+                    help="where to create the unique workspace (must resolve to /tmp or under /tmp/)")
@@
-        if real_base == "/tmp" or not real_base.startswith("/tmp/"):
-            log(f"FATAL: --base-dir must resolve under /tmp/ (got {real_base!r})")
+        if real_base != "/tmp" and not real_base.startswith("/tmp/"):
+            log(f"FATAL: --base-dir must resolve to /tmp or under /tmp/ (got {real_base!r})")
             return 1
@@
 DUAL_ORDER_REPRO = r'''
-import os, sys, unittest
-
-MODE = sys.argv[1]        # "asc" or "desc"
-SRC = sys.argv[2]
-TESTNAME = sys.argv[3]
-REVERSE = (MODE == "desc")
-
-_orig_scandir = os.scandir
-_orig_listdir = os.listdir
-
-def _key(e):
-    return getattr(e, "name", e)
-
-class _Iter:
-    def __init__(self, items):
-        self._it = iter(items)
-    def __iter__(self):
-        return self
-    def __next__(self):
-        return next(self._it)
-    def __enter__(self):
-        return self
-    def __exit__(self, *a):
-        return False
-    def close(self):
-        pass
-
-def _shim_scandir(path="."):
-    entries = list(_orig_scandir(path))
-    return _Iter(sorted(entries, key=_key, reverse=REVERSE))
-
-def _shim_listdir(path="."):
-    return sorted(_orig_listdir(path), reverse=REVERSE)
-
-os.scandir = _shim_scandir
-os.listdir = _shim_listdir
-
-def _patch_modules():
-    for m in list(sys.modules.values()):
-        if m is None:
-            continue
-        try:
-            if getattr(m, "scandir", None) is _orig_scandir:
-                setattr(m, "scandir", _shim_scandir)
-            if getattr(m, "listdir", None) is _orig_listdir:
-                setattr(m, "listdir", _shim_listdir)
-        except Exception:
-            pass
-
-sys.path.insert(0, SRC)
-os.chdir(SRC)
-
-_patch_modules()
-loader = unittest.TestLoader()
-suite = loader.loadTestsFromName(TESTNAME)
-_patch_modules()
-runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
-result = runner.run(suite)
-sys.exit(0 if result.wasSuccessful() else 1)
+import importlib
+import os
+import sys
+import unittest
+
+MODE = sys.argv[1]        # "asc" or "desc"
+SRC = sys.argv[2]
+TESTNAME = sys.argv[3]
+REVERSE = (MODE == "desc")
+
+sys.path.insert(0, SRC)
+os.chdir(SRC)
+
+# Import the test module normally first: its LocalAdapter feature detection must
+# see the real os.scandir so the test is actually collected and run.
+MODNAME = TESTNAME.rsplit(".", 1)[0]
+importlib.import_module(MODNAME)
+
+# Apply the order override only to the adapter scan seam, after feature
+# detection, so file-descriptor support remains intact.
+import drive_tool.local as local
+
+_attr = local.LocalAdapter.__dict__.get("_os_scandir")
+if _attr is None:
+    raise RuntimeError("LocalAdapter._os_scandir seam not found")
+
+def _iter_from(entries):
+    class _Iter:
+        def __init__(self, items):
+            self._it = iter(items)
+        def __iter__(self):
+            return self
+        def __next__(self):
+            return next(self._it)
+        def close(self):
+            pass
+        def __enter__(self):
+            return self
+        def __exit__(self, *a):
+            return False
+    return _Iter(entries)
+
+def _ordered(entries):
+    return sorted(entries, key=lambda e: getattr(e, "name", e), reverse=REVERSE)
+
+if isinstance(_attr, staticmethod):
+    _orig = _attr.__func__
+    def _shim(path="."):
+        return _iter_from(_ordered(list(_orig(path))))
+    local.LocalAdapter._os_scandir = staticmethod(_shim)
+elif isinstance(_attr, classmethod):
+    _orig = _attr.__func__
+    def _shim(cls, path="."):
+        return _iter_from(_ordered(list(_orig(cls, path))))
+    local.LocalAdapter._os_scandir = classmethod(_shim)
+else:
+    _orig = _attr
+    def _shim(self, path="."):
+        return _iter_from(_ordered(list(_orig(self, path))))
+    local.LocalAdapter._os_scandir = _shim
+
+loader = unittest.TestLoader()
+suite = loader.loadTestsFromName(TESTNAME)
+runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
+result = runner.run(suite)
+sys.exit(0 if result.wasSuccessful() else 1)
 '''
@@
     results = {}
     for mode in ("asc", "desc"):
         r = run([py_path, script_path, mode, src, ORDER_SENSITIVE_TEST],
                 cwd=src, env=env, timeout=timeout)
+        parsed = parse_unittest(r["out"] + r["err"])
+        r.update(parsed)
         with open(os.path.join(ws, "logs", f"dual_order_{mode}.out"), "w") as fh:
             fh.write(f"$ {' '.join(r['cmd'])}\n\n{r['out']}\n--- stderr ---\n{r['err']}\n")
             fh.write(f"EXIT={r['rc']} timed_out={r['timed_out']} seconds={r['seconds']}\n")
+            fh.write(f"ran={r['ran']} skipped={r['skipped']} ok={r['ok']} failed={r['failed']}\n")
         results[mode] = {"rc": r["rc"], "timed_out": r["timed_out"],
-                         "seconds": r["seconds"]}
-    confirmed = (results["asc"]["rc"] == 0
-                 and results["desc"]["rc"] not in (0, None)
-                 and not results["desc"]["timed_out"])
+                         "seconds": r["seconds"], "ran": r["ran"],
+                         "skipped": r["skipped"], "ok": r["ok"],
+                         "failed": r["failed"]}
+    asc = results["asc"]
+    desc = results["desc"]
+    confirmed = (
+        asc["rc"] == 0
+        and asc["ran"] == 1
+        and asc["skipped"] == 0
+        and asc["ok"]
+        and not asc["timed_out"]
+        and desc["rc"] not in (0, None)
+        and desc["ran"] == 1
+        and desc["skipped"] == 0
+        and desc["failed"]
+        and not desc["timed_out"]
+    )
     return results, confirmed
```

What this fixes:

- B-D072-1: default --base-dir=/tmp is now allowed as a base directory. The final workspace is still canonicalised and rejected if its realpath is exactly /tmp or escapes /tmp/. So /tmp is a valid base, never a final workspace.

- B-D072-2: the dual-order repro no longer replaces global os.scandir/os.listdir before import. It imports the test module normally so LocalAdapter feature detection sees real fd support, then overrides only LocalAdapter._os_scandir after detection. If that seam is missing it raises, not skips. The confirmation now requires Ran 1 test, skipped=0, and for desc a real FAILED/nonzero result.

Preserved:

- COMMIT, EXPECTED_BLOBS, STRESS_CHECKS_SHA256, payload identity, all 26 pinned file identities.

- Strict overall suite gate: a failing committed suite still sets suite_diagnostic_continue=True, still runs smoke/soak/edges for evidence, and still exits nonzero.

- 17 existing negative gates N1–N9, N11–N18 unchanged; N10 is the one intended to move old-fail → new-pass.

Honest status: TESTS_NOT_RUN. No Python 3.11/3.12 execution, no sandbox run, no target run, no install, no merge/deploy, no source-under-test edits.

Old-fail / new-pass plan for 3.11 and 3.12:

| check | old D069/D072 observed | new expected |
| --- | --- | --- |
| py_compile 3.11 / 3.12 | OK | OK |
| default invocation python3 run_cloud_stress.py | FATAL: --base-dir must resolve under /tmp/ (got '/tmp'), rc=1 | no FATAL; creates /tmp/d063-b7f8d17b-* mode 0700 |
| dual-order asc | rc=0, often OK (skipped=1) | Ran 1 test, skipped=0, OK, rc=0 |
| dual-order desc | rc=0, OK (skipped=1), confirmed=False | Ran 1 test, skipped=0, FAILED, rc=1 |
| confirmed_order_sensitive_defect | False | True |
| N10 negative gate | FAIL | PASS |
| N1–N9, N11–N18 | 17 PASS | 17 PASS preserved |
| overall suite gate | strict FAIL if 506 suite fails | strict FAIL preserved; diagnostic continue preserved |

No full rewrite, no source edits, no merge/deploy.
