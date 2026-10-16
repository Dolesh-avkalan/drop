
import importlib
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
MODNAME = TESTNAME.rsplit(".", 2)[0]
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
