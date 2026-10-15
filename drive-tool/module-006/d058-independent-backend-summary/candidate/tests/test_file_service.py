"""Unit tests for drive_tool.file_service (D050)."""

from __future__ import annotations

import errno
import hashlib
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

import drive_tool.file_service as file_service_module
from drive_tool.file_service import LocalFileService, ServiceError
from drive_tool.local import LocalAdapter, UnsafePathError
from drive_tool.service_policy import AgentPolicy, SourceGrant
from drive_tool.storage import ROOT_ID

def _token_digest(token: str) -> bytes:
    # AgentPolicy.token_sha256 is the raw 32-byte SHA-256 digest, not hex.
    return hashlib.sha256(token.encode("utf-8")).digest()

_TOKEN_PAD = "0123456789abcdef0123456789abcdef"

def _pad_token(base: str) -> str:
    # service_policy requires a 32..256 char visible-ASCII bearer token.
    return (base + _TOKEN_PAD)[:40]

def _make_grant(
    alias: str,
    root: Path,
    *,
    operations: frozenset[str] = frozenset({"list", "find", "read", "save"}),
    max_read_bytes: int = 1048576,
    max_write_bytes: int = 1048576,
) -> SourceGrant:
    try:
        return SourceGrant(
            alias=alias,
            root=root,
            operations=operations,
            max_read_bytes=max_read_bytes,
            max_write_bytes=max_write_bytes,
        )
    except TypeError:
        return SourceGrant(
            alias=alias,
            root=str(root),
            operations=operations,
            max_read_bytes=max_read_bytes,
            max_write_bytes=max_write_bytes,
        )

def _make_agent(
    agent_id: str,
    token: str,
    grants: tuple[SourceGrant, ...],
) -> AgentPolicy:
    return AgentPolicy(
        agent_id=agent_id,
        token_sha256=_token_digest(token),
        grants=grants,
    )

def _count_open_fds() -> int | None:
    for fd_dir in ("/proc/self/fd", "/dev/fd"):
        if os.path.isdir(fd_dir):
            try:
                return len(os.listdir(fd_dir))
            except OSError:
                return None
    return None

class LocalFileServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="d050_file_service_")
        self.base_dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _mkdir(self, rel: str) -> Path:
        path = self.base_dir / rel
        path.mkdir(parents=True, exist_ok=True)
        return path

    def test_six_identities_and_config_limits(self) -> None:
        policies: list[AgentPolicy] = []
        for idx in range(6):
            root = self._mkdir(f"agent_{idx}")
            (root / "id.txt").write_bytes(f"agent-{idx}".encode("utf-8"))
            grant = _make_grant("work", root)
            policies.append(
                _make_agent(f"agent-{idx}", _pad_token(f"secret-token-{idx}-value"), (grant,))
            )

        service = LocalFileService(tuple(policies))
        try:
            for idx in range(6):
                res = service.read(_pad_token(f"secret-token-{idx}-value"), "work", "p/id.txt")
                self.assertEqual(res.data, f"agent-{idx}".encode("utf-8"))
        finally:
            self.assertTrue(service.close())

        # Reject >6 configured agents before opening any LocalAdapter.
        extra_root = self._mkdir("agent_6")
        seven_policies = tuple(policies) + (
            _make_agent("agent-6", _pad_token("secret-token-6-value"), (_make_grant("work", extra_root),)),
        )
        with mock.patch.object(file_service_module, "LocalAdapter") as adapter_spy:
            with self.assertRaises(ValueError):
                LocalFileService(seven_policies)
            adapter_spy.assert_not_called()

        # Reject >32 total grants across <=6 agents before opening any LocalAdapter.
        many_grants_policies: list[AgentPolicy] = []
        for idx in range(6):
            grants = tuple(
                _make_grant(f"src{g}", self._mkdir(f"cap_{idx}_{g}"))
                for g in range(6)
            )  # 6 * 6 = 36 > 32
            many_grants_policies.append(
                _make_agent(f"agent-{idx}", _pad_token(f"many-token-{idx}-value"), grants)
            )
        with mock.patch.object(file_service_module, "LocalAdapter") as adapter_spy:
            with self.assertRaises(ValueError):
                LocalFileService(tuple(many_grants_policies))
            adapter_spy.assert_not_called()

    def test_two_agents_same_alias_different_roots(self) -> None:
        root_a = self._mkdir("root_a")
        root_b = self._mkdir("root_b")
        (root_a / "only_a.txt").write_bytes(b"alpha-content")
        (root_b / "only_b.txt").write_bytes(b"bravo-content")

        token_a = _pad_token("token-agent-alpha-001")
        token_b = _pad_token("token-agent-bravo-002")
        service = LocalFileService(
            (
                _make_agent("alpha", token_a, (_make_grant("shared", root_a),)),
                _make_agent("bravo", token_b, (_make_grant("shared", root_b),)),
            )
        )
        try:
            res_a = service.read(token_a, "shared", "p/only_a.txt")
            self.assertEqual(res_a.data, b"alpha-content")

            res_b = service.read(token_b, "shared", "p/only_b.txt")
            self.assertEqual(res_b.data, b"bravo-content")

            with self.assertRaises(ServiceError) as ctx_a:
                service.read(token_a, "shared", "p/only_b.txt")
            self.assertEqual(ctx_a.exception.code, "not_found")

            service.save(token_a, "shared", "p/written.txt", b"from-alpha")
            self.assertTrue((root_a / "written.txt").is_file())
            self.assertFalse((root_b / "written.txt").exists())
        finally:
            self.assertTrue(service.close())

    def test_readonly_denial_and_no_leaked_metadata(self) -> None:
        root = self._mkdir("ro_root")
        (root / "existing.txt").write_bytes(b"top-secret-payload")
        token = _pad_token("ro-agent-token-xyz")
        ro_grant = _make_grant(
            "docs",
            root,
            operations=frozenset({"list", "find", "read"}),
            max_write_bytes=1024,
        )
        service = LocalFileService((_make_agent("reader", token, (ro_grant,)),))
        try:
            with self.assertRaises(ServiceError) as existing_exc:
                service.save(token, "docs", "p/existing.txt", b"overwrite-attempt", overwrite=True)
            with self.assertRaises(ServiceError) as missing_exc:
                service.save(token, "docs", "p/nonexistent/file.txt", b"new-attempt")

            for err in (existing_exc.exception, missing_exc.exception):
                self.assertEqual(err.code, "denied")
                self.assertFalse(err.outcome_uncertain)
                self.assertFalse(err.retry_safe)
                self.assertIsNone(err.__cause__)
                rendered = f"{err} {err!r}"
                self.assertNotIn(str(root), rendered)
                self.assertNotIn(token, rendered)
                self.assertNotIn("existing.txt", rendered)
                self.assertNotIn("top-secret-payload", rendered)

            self.assertEqual(
                (existing_exc.exception.code, existing_exc.exception.message),
                (missing_exc.exception.code, missing_exc.exception.message),
            )
        finally:
            self.assertTrue(service.close())

    def test_startup_rollback_closes_earlier_adapters_once(self) -> None:
        valid_root_1 = self._mkdir("valid_1")
        valid_root_2 = self._mkdir("valid_2")
        missing_root_3 = self.base_dir / "does_not_exist_3"

        close_counts: list[LocalAdapter] = []
        opened_adapters: list[LocalAdapter] = []
        orig_close = LocalAdapter.close
        orig_init = LocalAdapter.__init__

        def counting_close(adapter_self: LocalAdapter) -> None:
            close_counts.append(adapter_self)
            orig_close(adapter_self)

        def recording_init(adapter_self: LocalAdapter, *args, **kwargs) -> None:
            orig_init(adapter_self, *args, **kwargs)
            opened_adapters.append(adapter_self)

        grants = (
            _make_grant("g1", valid_root_1),
            _make_grant("g2", valid_root_2),
            _make_grant("g3", missing_root_3),
        )
        policy = _make_agent("agent-rollback", _pad_token("rollback-token-123"), grants)

        with (
            mock.patch.object(LocalAdapter, "__init__", recording_init),
            mock.patch.object(
                LocalAdapter, "close", autospec=True, side_effect=counting_close
            ),
        ):
            with self.assertRaises(Exception):
                LocalFileService((policy,))

        # The two adapters that opened successfully are each closed exactly once;
        # the never-opened (failed) adapter is not a rollback target.
        self.assertEqual(len(opened_adapters), 2)
        self.assertNotEqual(opened_adapters[0], opened_adapters[1])
        for adapter in opened_adapters:
            self.assertEqual(close_counts.count(adapter), 1)
        self.assertFalse(missing_root_3.exists())

    def test_auth_before_any_per_request_adapter_call(self) -> None:
        root = self._mkdir("auth_order_root")
        token = _pad_token("valid-agent-token-999")
        ro_grant = _make_grant(
            "vault",
            root,
            operations=frozenset({"list"}),
        )
        service = LocalFileService((_make_agent("agent1", token, (ro_grant,)),))
        try:
            with mock.patch.object(
                file_service_module,
                "_parse_file_id",
                side_effect=AssertionError("_parse_file_id must not run before auth"),
            ) as parse_spy:
                # Bad token with invalid file_id and invalid options still fails with denied before parsing.
                with self.assertRaises(ServiceError) as bad_tok:
                    service.list("wrong-token", "vault", "../escape", limit=-5)
                self.assertEqual(bad_tok.exception.code, "denied")

                # Unauthorized operation ("read") with invalid file_id/options fails with denied before parsing.
                with self.assertRaises(ServiceError) as bad_op:
                    service.read(token, "vault", "root", offset=-1, length=0)
                self.assertEqual(bad_op.exception.code, "denied")

                # Unauthorized alias with invalid file_id fails with denied before parsing.
                with self.assertRaises(ServiceError) as bad_alias:
                    service.list(token, "unknown_alias", "../escape")
                self.assertEqual(bad_alias.exception.code, "denied")

                parse_spy.assert_not_called()
        finally:
            self.assertTrue(service.close())

    def test_invalid_options_and_caps_perform_no_io(self) -> None:
        root = self._mkdir("validation_root")
        (root / "sample.txt").write_bytes(b"hello")
        token = _pad_token("validation-token-123")
        grant = _make_grant("src", root, max_read_bytes=1024, max_write_bytes=512)
        service = LocalFileService((_make_agent("agent", token, (grant,)),))
        binding = service._bindings[("agent", "src")]

        try:
            with (
                mock.patch.object(binding.adapter, "read_range") as read_spy,
                mock.patch.object(binding.adapter, "list_children") as list_spy,
                mock.patch.object(binding.adapter, "scan_children") as scan_spy,
                mock.patch.object(binding.writer, "write_bytes") as write_spy,
                mock.patch.object(binding.writer, "mkdir") as mkdir_spy,
            ):
                invalid_calls = [
                    lambda: service.list(token, "src", limit=0),
                    lambda: service.list(token, "src", limit=101),
                    lambda: service.list(token, "src", limit=True),
                    lambda: service.list(token, "src", offset=-1),
                    lambda: service.list(token, "src", offset=False),
                    lambda: service.list(token, "src", name_contains="x" * 257),
                    lambda: service.find(token, "src", name_contains=""),
                    lambda: service.find(token, "src", name_contains="x" * 257),
                    lambda: service.find(token, "src", name_contains="ok", limit=101),
                    lambda: service.find(token, "src", name_contains="ok", max_entries=0),
                    lambda: service.find(token, "src", name_contains="ok", max_entries=2001),
                    lambda: service.find(token, "src", name_contains="ok", max_depth=-1),
                    lambda: service.find(token, "src", name_contains="ok", max_depth=17),
                    lambda: service.read(token, "src", ROOT_ID),
                    lambda: service.read(token, "src", "p/sample.txt", offset=True),
                    lambda: service.read(token, "src", "p/sample.txt", length=0),
                    lambda: service.read(
                        token,
                        "src",
                        "p/sample.txt",
                        offset=(1 << 63) - 1,
                        length=1,
                    ),
                    lambda: service.save(token, "src", ROOT_ID, b"abc"),
                    lambda: service.save(token, "src", "p/sample.txt", "not-bytes"),  # type: ignore[arg-type]
                    lambda: service.save(token, "src", "p/sample.txt", b"abc", overwrite=1),  # type: ignore[arg-type]
                    lambda: service.save(token, "src", "p/sample.txt", b"abc", create_parents=0),  # type: ignore[arg-type]
                    lambda: service.save(
                        token,
                        "src",
                        "p/" + "/".join(f"d{i}" for i in range(17)) + "/leaf.txt",
                        b"abc",
                    ),
                ]

                for call in invalid_calls:
                    with self.assertRaises(ServiceError) as ctx:
                        call()
                    self.assertEqual(ctx.exception.code, "invalid")
                    self.assertFalse(ctx.exception.outcome_uncertain)
                    self.assertFalse(ctx.exception.retry_safe)

                with self.assertRaises(ServiceError) as read_cap_ctx:
                    service.read(token, "src", "p/sample.txt", length=1025)
                self.assertEqual(read_cap_ctx.exception.code, "too_large")
                self.assertFalse(read_cap_ctx.exception.outcome_uncertain)
                self.assertFalse(read_cap_ctx.exception.retry_safe)

                with self.assertRaises(ServiceError) as write_cap_ctx:
                    service.save(token, "src", "p/sample.txt", b"x" * 513)
                self.assertEqual(write_cap_ctx.exception.code, "too_large")
                self.assertFalse(write_cap_ctx.exception.outcome_uncertain)
                self.assertFalse(write_cap_ctx.exception.retry_safe)

                read_spy.assert_not_called()
                list_spy.assert_not_called()
                scan_spy.assert_not_called()
                write_spy.assert_not_called()
                mkdir_spy.assert_not_called()
        finally:
            self.assertTrue(service.close())

    def test_list_and_find_metadata_and_partial_skip_contract(self) -> None:
        root = self._mkdir("list_find_root")
        (root / "alpha_note.txt").write_bytes(b"1234")
        (root / "beta_note.txt").write_bytes(b"123456")
        sub = root / "subdir"
        sub.mkdir()
        (sub / "deep_note.txt").write_bytes(b"99")
        # Symlink inside subdir that search.find must omit rather than follow.
        os.symlink(root / "alpha_note.txt", sub / "linked_note.txt")
        # Unreadable subtree: a real permission denial must appear in skipped.
        locked = root / "locked_note_dir"
        locked.mkdir()
        (locked / "hidden_note.txt").write_bytes(b"0")
        os.chmod(locked, 0o000)

        token = _pad_token("list-find-token-777")
        service = LocalFileService(
            (_make_agent("agent", token, (_make_grant("files", root),)),)
        )
        try:
            page1 = service.list(token, "files", ROOT_ID, limit=2, offset=0)
            self.assertEqual(set(page1.keys()), {"items", "next_offset"})
            self.assertEqual(len(page1["items"]), 2)
            self.assertEqual(page1["next_offset"], 2)
            for item in page1["items"]:
                self.assertEqual(
                    set(item.keys()),
                    {"ref", "name", "parent_id", "kind", "size_bytes"},
                )
                self.assertEqual(set(item["ref"].keys()), {"source_id", "file_id"})
                self.assertEqual(item["ref"]["source_id"], "files")
                self.assertEqual(item["parent_id"], ROOT_ID)

            found = service.find(
                token,
                "files",
                ROOT_ID,
                name_contains="note",
                limit=10,
                max_entries=2000,
                max_depth=4,
            )
            self.assertEqual(
                set(found.keys()),
                {"items", "truncated", "reason", "inspected", "skipped"},
            )
            self.assertIsInstance(found["skipped"], list)
            found_ids = [item["ref"]["file_id"] for item in found["items"]]
            self.assertIn("p/alpha_note.txt", found_ids)
            self.assertIn("p/beta_note.txt", found_ids)
            self.assertIn("p/subdir/deep_note.txt", found_ids)
            self.assertNotIn("p/subdir/linked_note.txt", found_ids)
            self.assertNotIn("p/locked_note_dir/hidden_note.txt", found_ids)
            # An omitted symlink is not a skipped subtree, but the unreadable
            # directory is: it must be reported and mark the walk incomplete.
            self.assertTrue(any("locked_note_dir" in s for s in found["skipped"]))
            self.assertTrue(found["truncated"])
            self.assertEqual(found["reason"], "skipped")
        finally:
            os.chmod(locked, 0o755)
            self.assertTrue(service.close())

    def test_read_large_sparse_range_and_exact_eof(self) -> None:
        root = self._mkdir("sparse_root")
        sparse_path = root / "sparse.bin"
        with open(sparse_path, "wb") as f:
            f.truncate(2 * 1024 * 1024)
            f.seek(1024 * 1024)
            f.write(b"MARKER")
            f.seek(2 * 1024 * 1024 - 4)
            f.write(b"TAIL")

        token = _pad_token("sparse-token-456")
        service = LocalFileService(
            (_make_agent("agent", token, (_make_grant("store", root),)),)
        )
        try:
            mid = service.read(token, "store", "p/sparse.bin", offset=1024 * 1024, length=10)
            self.assertEqual(mid.data, b"MARKER\x00\x00\x00\x00")
            self.assertFalse(mid.eof_observed)

            tail = service.read(
                token,
                "store",
                "p/sparse.bin",
                offset=2 * 1024 * 1024 - 4,
                length=4,
            )
            self.assertEqual(tail.data, b"TAIL")
            # Exact-fill window: no pread inside the window returned b'', so the
            # accepted no-lookahead contract reports eof_observed=False.
            self.assertFalse(tail.eof_observed)

            at_eof = service.read(
                token,
                "store",
                "p/sparse.bin",
                offset=2 * 1024 * 1024,
                length=64,
            )
            self.assertEqual(at_eof.data, b"")
            self.assertTrue(at_eof.eof_observed)
        finally:
            self.assertTrue(service.close())

    def test_save_no_overwrite_collision_and_explicit_overwrite(self) -> None:
        root = self._mkdir("overwrite_root")
        (root / "report.txt").write_bytes(b"original-bytes")
        token = _pad_token("overwrite-token-321")
        service = LocalFileService(
            (_make_agent("agent", token, (_make_grant("work", root),)),)
        )
        try:
            with self.assertRaises(ServiceError) as ctx:
                service.save(token, "work", "p/report.txt", b"new-bytes", overwrite=False)
            self.assertEqual(ctx.exception.code, "exists")
            self.assertTrue(ctx.exception.outcome_uncertain)
            self.assertFalse(ctx.exception.retry_safe)
            self.assertEqual((root / "report.txt").read_bytes(), b"original-bytes")

            res = service.save(
                token,
                "work",
                "p/report.txt",
                b"replaced-bytes",
                overwrite=True,
                create_parents=False,
            )
            self.assertEqual(
                res,
                {
                    "ref": {"source_id": "work", "file_id": "p/report.txt"},
                    "bytes_written": len(b"replaced-bytes"),
                    "parents_may_have_been_created": False,
                },
            )
            self.assertEqual((root / "report.txt").read_bytes(), b"replaced-bytes")
        finally:
            self.assertTrue(service.close())

    def test_save_creates_missing_parents_in_one_call(self) -> None:
        root = self._mkdir("parents_root")
        token = _pad_token("parents-token-654")
        service = LocalFileService(
            (_make_agent("agent", token, (_make_grant("work", root),)),)
        )
        try:
            with self.assertRaises(ServiceError) as missing_parent_ctx:
                service.save(
                    token,
                    "work",
                    "p/a/b.txt",
                    b"payload",
                    overwrite=False,
                    create_parents=False,
                )
            self.assertEqual(missing_parent_ctx.exception.code, "not_found")
            self.assertTrue(missing_parent_ctx.exception.outcome_uncertain)
            self.assertFalse(missing_parent_ctx.exception.retry_safe)

            saved = service.save(
                token,
                "work",
                "p/a/b.txt",
                b"payload",
                overwrite=False,
                create_parents=True,
            )
            self.assertEqual(
                saved,
                {
                    "ref": {"source_id": "work", "file_id": "p/a/b.txt"},
                    "bytes_written": 7,
                    "parents_may_have_been_created": True,
                },
            )
            self.assertEqual((root / "a" / "b.txt").read_bytes(), b"payload")
        finally:
            self.assertTrue(service.close())

    def test_save_symlink_parent_refused_and_outside_untouched(self) -> None:
        root = self._mkdir("symlink_root")
        outside = self._mkdir("outside_target")
        os.symlink(outside, root / "escape_dir")

        token = _pad_token("symlink-token-111")
        service = LocalFileService(
            (_make_agent("agent", token, (_make_grant("work", root),)),)
        )
        try:
            with self.assertRaises(ServiceError) as ctx:
                service.save(
                    token,
                    "work",
                    "p/escape_dir/sub/pwned.txt",
                    b"malicious",
                    overwrite=True,
                    create_parents=True,
                )
            self.assertEqual(ctx.exception.code, "denied")
            self.assertTrue(ctx.exception.outcome_uncertain)
            self.assertFalse(ctx.exception.retry_safe)
            self.assertEqual(list(outside.iterdir()), [])
        finally:
            self.assertTrue(service.close())

    def test_save_post_publish_fsync_failure_flags_uncertainty(self) -> None:
        # Labelled fault injection: simulate post-os.replace directory fsync EIO failure.
        root = self._mkdir("fsync_fault_root")
        token = _pad_token("fsync-token-222")
        service = LocalFileService(
            (_make_agent("agent", token, (_make_grant("work", root),)),)
        )
        binding = service._bindings[("agent", "work")]
        orig_write_bytes = binding.writer.write_bytes

        def fault_injected_write_bytes(parent, name, data, *, overwrite=False):
            orig_write_bytes(parent, name, data, overwrite=overwrite)
            raise OSError(errno.EIO, f"fsync failed on {root}/secret_dir")

        try:
            with mock.patch.object(
                binding.writer,
                "write_bytes",
                side_effect=fault_injected_write_bytes,
            ):
                with self.assertRaises(ServiceError) as ctx:
                    service.save(token, "work", "p/committed.txt", b"secret-file-bytes")

            err = ctx.exception
            self.assertEqual(err.code, "unavailable")
            self.assertTrue(err.outcome_uncertain)
            self.assertFalse(err.retry_safe)
            self.assertIsNone(err.__cause__)
            self.assertEqual((root / "committed.txt").read_bytes(), b"secret-file-bytes")
            self.assertNotIn(str(root), str(err))
            self.assertNotIn("secret-file-bytes", str(err))
        finally:
            self.assertTrue(service.close())

    def test_static_error_redaction_and_no_cause_leak(self) -> None:
        root = self._mkdir("redaction_root")
        token = _pad_token("super-sensitive-bearer-token")
        service = LocalFileService(
            (_make_agent("agent", token, (_make_grant("work", root),)),)
        )
        binding = service._bindings[("agent", "work")]

        try:
            # Labelled fault injection: raise UnsafePathError carrying sensitive details.
            with mock.patch.object(
                binding.adapter,
                "read_range",
                side_effect=UnsafePathError(f"blocked path {root}/private for {token}"),
            ):
                with self.assertRaises(ServiceError) as ctx:
                    service.read(token, "work", "p/doc.txt")

            err = ctx.exception
            self.assertEqual(err.code, "denied")
            self.assertFalse(err.outcome_uncertain)
            self.assertFalse(err.retry_safe)
            self.assertIsNone(err.__cause__)
            self.assertTrue(err.__suppress_context__)
            for text in (str(err), repr(err), *map(str, err.args)):
                self.assertNotIn(str(root), text)
                self.assertNotIn(token, text)
                self.assertNotIn("private", text)
        finally:
            self.assertTrue(service.close())

    def test_concurrent_blocked_read_and_close_timeout_keeps_fd_alive(self) -> None:
        # Labelled fault injection: block read_range on an Event while close(timeout) runs.
        root = self._mkdir("concurrent_read_root")
        (root / "data.txt").write_bytes(b"live-descriptor-data")
        token = _pad_token("concurrent-token-888")
        service = LocalFileService(
            (_make_agent("agent", token, (_make_grant("work", root),)),)
        )
        binding = service._bindings[("agent", "work")]
        orig_read_range = binding.adapter.read_range
        entered_read = threading.Event()
        release_read = threading.Event()

        def blocking_read_range(ref, *, offset=0, length=None):
            entered_read.set()
            release_read.wait(timeout=5.0)
            return orig_read_range(ref, offset=offset, length=length)

        read_outcomes: list[object] = []

        def worker() -> None:
            try:
                res = service.read(token, "work", "p/data.txt")
                read_outcomes.append(res.data)
            except BaseException as exc:
                read_outcomes.append(exc)

        with mock.patch.object(
            binding.adapter,
            "read_range",
            side_effect=blocking_read_range,
        ):
            t = threading.Thread(target=worker)
            t.start()
            self.assertTrue(entered_read.wait(timeout=2.0))

            # Timed-out close must return False and keep the active adapter open.
            self.assertFalse(service.close(timeout=0.03))
            self.assertFalse(binding.closed)

            # New requests after drain starts are rejected immediately as unavailable.
            with self.assertRaises(ServiceError) as drain_ctx:
                service.list(token, "work")
            self.assertEqual(drain_ctx.exception.code, "unavailable")
            self.assertFalse(drain_ctx.exception.outcome_uncertain)
            self.assertTrue(drain_ctx.exception.retry_safe)

            # Unblock the in-flight read and verify it succeeds using the still-open adapter.
            release_read.set()
            t.join(timeout=2.0)
            self.assertEqual(read_outcomes, [b"live-descriptor-data"])

            # Subsequent close finishes draining and returns True.
            self.assertTrue(service.close(timeout=2.0))
            self.assertTrue(binding.closed)

    def test_concurrent_closes_close_once_and_reject_new_leases(self) -> None:
        root = self._mkdir("concurrent_close_root")
        (root / "item.txt").write_bytes(b"content")
        token = _pad_token("concurrent-close-token")
        service = LocalFileService(
            (_make_agent("agent", token, (_make_grant("work", root),)),)
        )
        binding = service._bindings[("agent", "work")]
        orig_read_range = binding.adapter.read_range
        orig_close = binding.adapter.close
        entered = threading.Event()
        unblock = threading.Event()
        close_calls = 0
        close_lock = threading.Lock()

        def slow_read(ref, *, offset=0, length=None):
            entered.set()
            unblock.wait(timeout=5.0)
            return orig_read_range(ref, offset=offset, length=length)

        def tracked_close() -> None:
            nonlocal close_calls
            with close_lock:
                close_calls += 1
            orig_close()

        with (
            mock.patch.object(binding.adapter, "read_range", side_effect=slow_read),
            mock.patch.object(binding.adapter, "close", side_effect=tracked_close),
        ):
            op_thread = threading.Thread(
                target=lambda: service.read(token, "work", "p/item.txt")
            )
            op_thread.start()
            self.assertTrue(entered.wait(timeout=2.0))

            close_results: list[bool] = []
            close_threads = [
                threading.Thread(
                    target=lambda: close_results.append(service.close(timeout=3.0))
                )
                for _ in range(4)
            ]
            for ct in close_threads:
                ct.start()

            unblock.set()
            op_thread.join(timeout=2.0)
            for ct in close_threads:
                ct.join(timeout=2.0)

            self.assertEqual(close_results, [True, True, True, True])
            self.assertEqual(close_calls, 1)

            with self.assertRaises(ServiceError) as post_close_ctx:
                service.read(token, "work", "p/item.txt")
            self.assertEqual(post_close_ctx.exception.code, "unavailable")

    def test_fd_stability_and_resource_accounting_after_close(self) -> None:
        baseline_fds = _count_open_fds()
        roots = [self._mkdir(f"fd_root_{i}") for i in range(4)]
        for r in roots:
            (r / "f.txt").write_bytes(b"ok")

        grants = tuple(_make_grant(f"g{i}", roots[i]) for i in range(4))
        token = _pad_token("fd-stability-token")
        service = LocalFileService((_make_agent("agent", token, grants),))
        for i in range(4):
            self.assertEqual(service.read(token, f"g{i}", "p/f.txt").data, b"ok")
            self.assertEqual(len(service.list(token, f"g{i}")["items"]), 1)

        self.assertTrue(service.close(timeout=2.0))
        self.assertEqual(service._active_leases, 0)
        if baseline_fds is not None:
            self.assertEqual(_count_open_fds(), baseline_fds)

if __name__ == "__main__":
    unittest.main()
