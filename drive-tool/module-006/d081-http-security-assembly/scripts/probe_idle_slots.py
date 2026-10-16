"""D081 probe: is the six-slot admission table populated synchronously?

Counts len(DriveHTTPAdapter._idle_slots) immediately after construction.
On the corrected __init__ all six slots are registered before any thread can
run; on the pre-patch __init__ the table is filled asynchronously by the
worker threads, so this is the deterministic seam for the startup property.
"""
import collections
import sys
import tempfile

sys.path.insert(0, ".")
import tests.test_http_adapter as T
from drive_tool.http_adapter import DriveHTTPAdapter

TRIALS = 200
tally = collections.Counter()
for _ in range(TRIALS):
    base = tempfile.mkdtemp(prefix="d081-idle-")
    policies, _r = T._standard_policies(base)
    a = DriveHTTPAdapter(policies, port=0, socket_timeout=1.0)
    tally[len(a._idle_slots)] += 1
    a.close(timeout=2.0)
print("len(_idle_slots) right after __init__ over %d trials: %s"
      % (TRIALS, dict(tally)))
print("MAX_IN_FLIGHT_OPERATIONS =", T.MAX_IN_FLIGHT_OPERATIONS)
