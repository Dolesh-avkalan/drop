"""D076 diagnostic (NOT a fix, not a test): prove the post-lease save-uncertainty
guard is sensitive to a genuinely post-publish failure, and that cleanup holds.

Runs three fault injections against the real adapter over synthetic roots:
  1. _os_link   (the OLD, mis-seamed primitive) with overwrite=True
  2. _os_rename AFTER the real rename  (true post-publish failure)
  3. _os_rename BEFORE the real rename (pre-publish failure)
"""
import errno
import os
import sys
import tempfile

sys.path.insert(0, ".")
from drive_tool import local_write
from drive_tool.http_adapter import DriveHTTPAdapter
from drive_tool.service_client import DriveClient, DriveClientError
from tests import test_http_adapter as T


def run(label, primitive, *, before):
    base = tempfile.mkdtemp(prefix="d076-diag-")
    policies, roots = T._standard_policies(base)
    adapter = DriveHTTPAdapter(policies, port=0, socket_timeout=5.0)
    client = DriveClient(port=adapter.port, token=T._MAIN_TOKEN, timeout=5.0)
    pool = os.path.join(roots["main"], "savepool")
    target = os.path.join(pool, "fault.bin")
    orig = getattr(local_write.LocalWriter, primitive)

    def boom(self, *a, **k):
        if not before:
            orig(self, *a, **k)
        raise OSError(errno.EIO, "injected failure")

    setattr(local_write.LocalWriter, primitive, boom)
    try:
        try:
            client.save("main", "p/savepool/fault.bin", b"FAULT-PAYLOAD",
                        overwrite=True)
            outcome = "SAVE SUCCEEDED (no error)"
        except DriveClientError as exc:
            outcome = ("DriveClientError(code=%s, uncertain=%s, retry_safe=%s)"
                       % (exc.code, exc.outcome_uncertain, exc.retry_safe))
    finally:
        setattr(local_write.LocalWriter, primitive, orig)
    published = os.path.exists(target)
    payload = open(target, "rb").read() if published else None
    leftovers = [n for n in os.listdir(pool)
                 if n.startswith(local_write.TEMP_PREFIX)]
    adapter.close(timeout=5.0)
    print("%-26s overwrite=True -> %s | published=%s bytes=%r | temp_leftovers=%d"
          % (label, outcome, published, payload, len(leftovers)))


run("_os_link (old test seam)", "_os_link", before=False)
run("_os_rename post-publish", "_os_rename", before=False)
run("_os_rename pre-publish", "_os_rename", before=True)
