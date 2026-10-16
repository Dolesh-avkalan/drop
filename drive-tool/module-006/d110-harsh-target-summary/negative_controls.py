#!/usr/bin/env python3
"""d110 guard-negative controls (stdlib only).

Proves the runner's fail-closed guards are not no-ops: each control mutates a
clean input and asserts the corresponding guard fires.  These are HARNESS
controls, not product tests.

Run:  python3 negative_controls.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tarfile
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_harsh_d110 as R  # noqa: E402

ARCHIVE = sys.argv[1] if len(sys.argv) > 1 else "/scratch/work/d110/cand.tar.gz"
DRIVE_TOOL = sys.argv[2] if len(sys.argv) > 2 else "/scratch/work/d110/drive_tool"


def _extract_source(dest):
    src = os.path.join(dest, "src")
    shutil.copytree(DRIVE_TOOL, os.path.join(src, "drive_tool"))
    # strip any stale bytecode so the clean case is clean
    for dp, dn, fn in os.walk(os.path.join(src, "drive_tool")):
        for name in list(fn):
            if name.endswith(".pyc"):
                os.unlink(os.path.join(dp, name))
    os.makedirs(os.path.join(src, "tests"), exist_ok=True)
    with tarfile.open(ARCHIVE) as t:
        for m in t.getmembers():
            if "/tests/" in m.name and m.isfile():
                rel = m.name.split("/tests/", 1)[1]
                with open(os.path.join(src, "tests", rel), "wb") as fh:
                    fh.write(t.extractfile(m).read())
    return src


def main():
    results = []
    tmp = tempfile.mkdtemp(prefix="d110-neg-")
    try:
        # clean payload
        p = os.path.join(tmp, "harsh_checks_d110.py")
        shutil.copyfile(os.path.join(HERE, "harsh_checks_d110.py"), p)
        results.append(("N1a clean payload accepted",
                        R.verify_payload(p) == []))
        # tampered payload
        data = bytearray(open(p, "rb").read())
        data[-1] ^= 0x01
        open(p, "wb").write(bytes(data))
        results.append(("N1b tampered payload rejected",
                        any("sha256 mismatch" in x for x in R.verify_payload(p))))

        src = _extract_source(tmp)
        clean = R.verify_identities(src, R.EXPECTED_BLOBS)
        results.append(("N2a clean source accepted", clean == []))

        # N2b tampered source file
        with open(os.path.join(src, "drive_tool", "http_adapter.py"), "ab") as fh:
            fh.write(b"\n# tamper\n")
        probs = R.verify_identities(src, R.EXPECTED_BLOBS)
        results.append(("N2b tampered source rejected",
                        any("http_adapter.py" in x and "mismatch" in x for x in probs)))
        shutil.copyfile(os.path.join(DRIVE_TOOL, "http_adapter.py"),
                        os.path.join(src, "drive_tool", "http_adapter.py"))

        # N3 unexpected importable file anywhere
        with open(os.path.join(src, "drive_tool", "sitecustomize.py"), "w") as fh:
            fh.write("print('x')\n")
        probs = R.verify_identities(src, R.EXPECTED_BLOBS)
        results.append(("N3 extra importable file rejected",
                        any("sitecustomize.py" in x for x in probs)))
        os.unlink(os.path.join(src, "drive_tool", "sitecustomize.py"))

        # N4 unexpected tests/ file
        with open(os.path.join(src, "tests", "test_evil.py"), "w") as fh:
            fh.write("import os\n")
        probs = R.verify_identities(src, R.EXPECTED_BLOBS)
        results.append(("N4 extra tests file rejected",
                        any("test_evil.py" in x for x in probs)))
        os.unlink(os.path.join(src, "tests", "test_evil.py"))

        # N5 symlink in source
        os.symlink("/etc/passwd", os.path.join(src, "drive_tool", "link.py"))
        probs = R.verify_identities(src, R.EXPECTED_BLOBS)
        results.append(("N5 symlink in source rejected",
                        any("symlink" in x for x in probs)))
        os.unlink(os.path.join(src, "drive_tool", "link.py"))

        # N6 missing expected file
        os.unlink(os.path.join(src, "tests", "test_storage.py"))
        probs = R.verify_identities(src, R.EXPECTED_BLOBS)
        results.append(("N6 missing expected file rejected",
                        any("expected file missing" in x for x in probs)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    ok = all(v for _n, v in results)
    print("D110 guard-negative controls")
    print("=" * 32)
    for name, val in results:
        print("%-38s %s" % (name, "PASS" if val else "FAIL"))
    print("=" * 32)
    print("overall:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
