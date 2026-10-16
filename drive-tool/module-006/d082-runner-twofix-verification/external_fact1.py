import importlib
import os
import sys

SRC = sys.argv[1]
TESTNAME = sys.argv[2]

value = TESTNAME.rsplit(".", 1)[0]
print("modname_value =", repr(value))

sys.path.insert(0, SRC)
os.chdir(SRC)

try:
    importlib.import_module(value)
except BaseException as exc:
    print("raised_exception_type =", type(exc).__name__)
    print("exception_message =", str(exc))
else:
    print("raised_exception_type = None")
    print("exception_message = <no exception raised>")
