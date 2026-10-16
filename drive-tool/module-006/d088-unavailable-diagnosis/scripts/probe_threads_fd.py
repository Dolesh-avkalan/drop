"""D085 counter probe: adapter thread census and fd delta while live."""
import os
import sys
import tempfile
import threading

sys.path.insert(0, ".")
import tests.test_http_adapter as T
from drive_tool.http_adapter import DriveHTTPAdapter


def nfd():
    return len(os.listdir("/proc/self/fd"))


base = tempfile.mkdtemp(prefix="d085-thr-")
policies, _r = T._standard_policies(base)
before = threading.active_count()
fd0 = nfd()
a = DriveHTTPAdapter(policies, port=0, socket_timeout=5.0)
live = threading.active_count()
fd1 = nfd()
names = sorted(t.name for t in threading.enumerate() if t.name.startswith("drive-http"))
closed = a.close(timeout=5.0)
after = threading.active_count()
print("threads: before=%d live=%d after_close=%d (expected adapter threads=%d)"
      % (before, live, after, T.THRESHOLDS["expected_adapter_threads"]))
print("adapter threads:", names)
print("fd: before=%d live=%d closed=%s" % (fd0, fd1, closed))
import shutil
shutil.rmtree(base, ignore_errors=True)
