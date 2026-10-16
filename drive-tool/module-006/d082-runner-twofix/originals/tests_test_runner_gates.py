#!/usr/bin/env python3
"""Self-tests for the d063 runner gates (stdlib only).

These exercise the runner's fail-closed gates directly, including the required
identity-TAMPER negative. They run on the author's sandbox only and make no
target claim. Run:

    python3 tests/test_runner_gates.py
    # or: python3 -m unittest discover -s tests
"""

from __future__ import annotations

import hashlib
import io
import os
import sys
import tarfile
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER_DIR = os.path.join(os.path.dirname(HERE), "runner")
sys.path.insert(0, RUNNER_DIR)

import run_cloud_stress as rcs  # noqa: E402


def _make_tar(members, path):
    """members: list of (name, kind, payload). kind in {file, symlink, dir}."""
    with tarfile.open(path, "w:gz") as t:
        for name, kind, payload in members:
            if kind == "file":
                data = payload.encode() if isinstance(payload, str) else payload
                info = tarfile.TarInfo(name)
                info.size = len(data)
                t.addfile(info, io.BytesIO(data))
            elif kind == "dir":
                info = tarfile.TarInfo(name)
                info.type = tarfile.DIRTYPE
                t.addfile(info)
            elif kind == "symlink":
                info = tarfile.TarInfo(name)
                info.type = tarfile.SYMTYPE
                info.linkname = payload
                t.addfile(info)


class BlobIdentityTests(unittest.TestCase):
    def test_empty_blob_vector(self):
        # git's canonical empty-blob sha1
        self.assertEqual(rcs.git_blob_sha1(b""),
                         "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391")

    def test_blob_matches_git_formula(self):
        data = b"hello world\n"
        want = hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()
        self.assertEqual(rcs.git_blob_sha1(data), want)

    def test_expected_set_shape(self):
        self.assertEqual(len(rcs.EXPECTED_BLOBS), 26)
        self.assertTrue(all(len(v) == 40 for v in rcs.EXPECTED_BLOBS.values()))


class VerifyIdentitiesTests(unittest.TestCase):
    def test_clean_tree_passes(self):
        with tempfile.TemporaryDirectory() as td:
            expected = {}
            for rel in ("drive_tool/local.py", "tests/test_local.py"):
                p = os.path.join(td, rel)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "wb") as fh:
                    fh.write(b"content of " + rel.encode())
                with open(p, "rb") as fh:
                    expected[rel] = rcs.git_blob_sha1(fh.read())
            problems, extra = rcs.verify_identities(td, expected)
            self.assertEqual(problems, [])
            self.assertEqual(extra, [])

    def test_tamper_is_detected(self):
        """Required negative: a mutated executable must be reported MISMATCH."""
        with tempfile.TemporaryDirectory() as td:
            rel = "drive_tool/local.py"
            p = os.path.join(td, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as fh:
                fh.write(b"ORIGINAL")
            expected = {rel: rcs.git_blob_sha1(b"ORIGINAL")}
            with open(p, "wb") as fh:      # tamper AFTER pinning
                fh.write(b"TAMPERED")
            problems, _ = rcs.verify_identities(td, expected)
            self.assertEqual(len(problems), 1)
            self.assertIn("MISMATCH", problems[0])
            self.assertIn(rel, problems[0])

    def test_missing_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            problems, _ = rcs.verify_identities(td, {"drive_tool/local.py": "0" * 40})
            self.assertTrue(problems and problems[0].startswith("MISSING"))


class SafeExtractTests(unittest.TestCase):
    def _extract(self, members):
        with tempfile.TemporaryDirectory() as td:
            tar = os.path.join(td, "a.tar.gz")
            _make_tar(members, tar)
            dest = os.path.join(td, "out")
            os.makedirs(dest)
            return rcs.safe_extract(tar, dest)

    def test_clean_archive_ok(self):
        n = self._extract([("top/", "dir", None),
                           ("top/drive_tool/", "dir", None),
                           ("top/drive_tool/local.py", "file", "x=1\n")])
        self.assertEqual(n, 3)

    def test_path_traversal_rejected(self):
        with self.assertRaises(RuntimeError):
            self._extract([("top/", "dir", None),
                           ("top/../evil.py", "file", "x")])

    def test_absolute_path_rejected(self):
        with self.assertRaises(RuntimeError):
            self._extract([("/etc/evil", "file", "x")])

    def test_symlink_member_rejected(self):
        with self.assertRaises(RuntimeError):
            self._extract([("top/", "dir", None),
                           ("top/link", "symlink", "/etc/passwd")])

    def test_oversized_member_rejected(self):
        big = b"A" * (rcs.MAX_FILE_BYTES + 1)
        with self.assertRaises(RuntimeError):
            self._extract([("top/", "dir", None), ("top/big.bin", "file", big)])

    def test_member_count_cap(self):
        members = [("top/", "dir", None)]
        members += [(f"top/f{i}", "file", "x") for i in range(rcs.MAX_MEMBERS + 5)]
        with self.assertRaises(RuntimeError):
            self._extract(members)


class MiscGateTests(unittest.TestCase):
    def test_find_src_root_requires_single_dir(self):
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "one"))
            self.assertTrue(rcs.find_src_root(td).endswith("one"))
            os.makedirs(os.path.join(td, "two"))
            with self.assertRaises(RuntimeError):
                rcs.find_src_root(td)

    def test_parse_unittest(self):
        ok = rcs.parse_unittest("Ran 506 tests in 5.2s\n\nOK\n")
        self.assertEqual(ok["ran"], 506)
        self.assertTrue(ok["ok"])
        bad = rcs.parse_unittest("Ran 10 tests in 1s\n\nFAILED (failures=2)\n")
        self.assertTrue(bad["failed"])

    def test_payload_sha_matches_pinned_constant(self):
        """Self-consistency: the pinned payload hash matches the shipped file."""
        path = os.path.join(RUNNER_DIR, "stress_checks.py")
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(rcs.sha256_file(path), rcs.STRESS_CHECKS_SHA256)

    def test_bounds_are_defined(self):
        self.assertLessEqual(rcs.MAX_CONCURRENT, 6)
        self.assertEqual(rcs.MAX_FIXTURE_BYTES, 32 * 1024 * 1024)
        self.assertEqual(rcs.MAX_WORKSPACE_BYTES, 128 * 1024 * 1024)
        self.assertLess(rcs.DEFAULT_OVERALL_DEADLINE, 20 * 60)


if __name__ == "__main__":
    unittest.main(verbosity=2)
