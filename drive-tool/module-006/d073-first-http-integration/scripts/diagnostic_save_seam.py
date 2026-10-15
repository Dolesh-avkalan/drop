"""D073 diagnostic (NOT a fix): classify the save-uncertainty failure.

Shows that the injected fault fires only on the publish primitive the test
actually exercised. `LocalWriter.write_bytes` uses `_os_link` when
overwrite=False and `_os_rename` when overwrite=True. The committed D067 test
patches `_os_link` but saves with overwrite=True, so no fault fires and the
save legitimately succeeds -> DriveClientError not raised (a harness probe-seam
mismatch, not a production defect).
"""
import errno, sys, tempfile
sys.path.insert(0, ".")
from drive_tool import local_write
from drive_tool.http_adapter import DriveHTTPAdapter
from drive_tool.service_client import DriveClient, DriveClientError
from tests import test_http_adapter as T


def run(primitive, overwrite):
    base = tempfile.mkdtemp(prefix="d073-diag-")
    policies, _roots = T._standard_policies(base)
    adapter = DriveHTTPAdapter(policies, port=0, socket_timeout=5.0)
    client = DriveClient(port=adapter.port, token=T._MAIN_TOKEN, timeout=5.0)
    orig = getattr(local_write.LocalWriter, primitive)

    def boom(self, *a, **k):
        orig(self, *a, **k)          # publish really happens
        raise OSError(errno.EIO, "injected post-publish failure")

    setattr(local_write.LocalWriter, primitive, boom)
    try:
        try:
            client.save("main", "p/savepool/diag.bin", b"DIAG-PAYLOAD", overwrite=overwrite)
            outcome = "SAVE SUCCEEDED (no error)"
        except DriveClientError as exc:
            outcome = "DriveClientError(code=%s, uncertain=%s, retry_safe=%s)" % (
                exc.code, exc.outcome_uncertain, exc.retry_safe)
    finally:
        setattr(local_write.LocalWriter, primitive, orig)
        adapter.close(timeout=5.0)
    print("patch %-10s overwrite=%-5s -> %s" % (primitive, overwrite, outcome))


run("_os_link", False)     # no-overwrite publish primitive
run("_os_link", True)      # committed test: wrong primitive for overwrite=True
run("_os_rename", True)    # correct primitive for overwrite=True
