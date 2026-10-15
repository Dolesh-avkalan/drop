
import os, sys, unittest

MODE = sys.argv[1]        # "asc" or "desc"
SRC = sys.argv[2]
TESTNAME = sys.argv[3]
REVERSE = (MODE == "desc")

_orig_scandir = os.scandir
_orig_listdir = os.listdir

def _key(e):
    return getattr(e, "name", e)

class _Iter:
    def __init__(self, items):
        self._it = iter(items)
    def __iter__(self):
        return self
    def __next__(self):
        return next(self._it)
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def close(self):
        pass

def _shim_scandir(path="."):
    entries = list(_orig_scandir(path))
    return _Iter(sorted(entries, key=_key, reverse=REVERSE))

def _shim_listdir(path="."):
    return sorted(_orig_listdir(path), reverse=REVERSE)

os.scandir = _shim_scandir
os.listdir = _shim_listdir

def _patch_modules():
    for m in list(sys.modules.values()):
        if m is None:
            continue
        try:
            if getattr(m, "scandir", None) is _orig_scandir:
                setattr(m, "scandir", _shim_scandir)
            if getattr(m, "listdir", None) is _orig_listdir:
                setattr(m, "listdir", _shim_listdir)
        except Exception:
            pass

sys.path.insert(0, SRC)
os.chdir(SRC)

_patch_modules()
loader = unittest.TestLoader()
suite = loader.loadTestsFromName(TESTNAME)
_patch_modules()
runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
result = runner.run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
