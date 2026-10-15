# d050 (gemini)

- status: done
- chat: https://gemini.google.com/app/d75caccb6796507d
- model: 4 argon (thinking: medium)
- finished: 2026-10-15T17:12:35Z

## Question

Gemini, implement D050's exact two-file synchronous file-service operation layer and tests. This is the backend component of the future HTTP service, not a server/deployment task. Use the supplied pinned contract/API context; do not duplicate pending policy/client/range modules or invent a resolver. Prefer downloadable files; necessary complete FILE-block fallback allowed if artifacts unavailable. No actual execution ->TESTS_NOT_RUN. No installs, real roots, credentials, pushes, merge or deployment. Keep explanation short; source/test files complete. Model4Argon with medium thinking is deliberate task-level choice. End STATUS: GENERATED.

(input files: Dolesh-avkalan/drive-tool:tasks/d050-file-service-implementation.md@8eac68b98481b86e7ae164a5835063584c15fdcb)

## Answer

Implementation of the synchronous local file-service operation layer (drive_tool/file_service.py) and its unit test suite (tests/test_file_service.py) for D050.

### Summary of Implementation & Test Intent

- Lifecycle & Lease Control (LocalFileService): Enforces configuration limits (<= 6 agents, <= 32 total grants) before opening any adapters, constructs PolicyTable and per-(agent_id, source_alias) (LocalAdapter, LocalWriter) bindings with max_list_entries=2000, and rolls back already-opened adapters once on startup failure while preserving the original exception. Operations borrow per-call leases under a short condition lock that is never held during filesystem I/O. close(timeout=...) stops new leases immediately, waits up to timeout for in-flight leases, leaves active descriptors untouched on timeout (False), and closes each adapter once when drained (True).

- Pre-I/O Security & Validation Boundary: Every operation checks drain status, authenticates token, and authorizes (agent_id, source_id, operation) via PolicyTable before parsing file_id or validating options, and validates all option types/bounds before borrowing a lease or performing any filesystem I/O.

- Error Redaction & Uncertainty Semantics (ServiceError): Restricts error output to fixed static messages and codes (invalid, denied, not_found, exists, too_large, busy, unavailable, timeout) with suppressed exception context (from None, __cause__ = None). Post-lease save failures set outcome_uncertain=True, retry_safe=False; pre-FS auth/option failures set outcome_uncertain=False, retry_safe=False; pre-FS drain and read-only unavailable failures set outcome_uncertain=False, retry_safe=True.

- Test Intent (tests/test_file_service.py): Covers 6 configured identities and startup cap enforcement, multi-agent alias isolation across distinct roots, read-only/unauthenticated denial with zero metadata leakage, startup rollback on invalid later roots, strict auth-before-parse/I/O ordering, option validation with zero adapter calls, list/find metadata and skipped: list[str] contracts, sparse file range reads and EOF semantics, save overwrite refusal, top-down parent creation, symlink traversal refusal, labelled post-publish directory fsync fault injection (outcome_uncertain=True), concurrent blocked read during close(timeout) followed by drain completion, concurrent close() single-close guarantee, and file-descriptor stability after drain.

### Source / API Ambiguities Noted

1. Read-only error retry_safe classification: The specification states "Auth/options failures before FS: uncertainFalse/retry_safeFalse. Read-only storage/unavailable errors may retry safely under same policy." This implementation sets retry_safe=True when outcome_uncertain=False and code in {"unavailable", "busy", "timeout"}, keeping deterministic storage outcomes (not_found, denied, exists, too_large, invalid) at retry_safe=False so that PolicyDeniedError and post-lease UnsafePathError/ReadOnlyError remain indistinguishable (code="denied", outcome_uncertain=False, retry_safe=False).

2. Read-only grant max_write_bytes handling in LocalWriter: If a pending SourceGrant candidate allows max_write_bytes == 0 on grants without "save" while LocalWriter requires max_write_bytes >= 1, LocalFileService.__init__ attempts LocalWriter(adapter, max_write_bytes=grant.max_write_bytes) first and only stores writer = None if LocalWriter rejects a non-positive cap on a grant that does not authorize "save".

FILE: drive_tool/file_service.py

```python
"""Synchronous local file-service operation layer (D050)."""

from __future__ import annotations

import math
import threading
import time
from typing import TYPE_CHECKING, Any

from drive_tool import search
from drive_tool.listing import ListingService
from drive_tool.local import (
    AdapterClosedError,
    LocalAdapter,
    LocalStorageError,
    ReadLimitExceededError,
    UnsafePathError,
    UnsupportedEntryError,
    UnsupportedPlatformError,
    _parse_file_id,
)
from drive_tool.local_write import LocalWriter, WriteLimitExceededError
from drive_tool.service_policy import (
    AgentPolicy,
    PolicyDeniedError,
    PolicyTable,
    SourceGrant,
)
from drive_tool.storage import (
     ROOT_ID,
    AlreadyExistsError,
    EnumerationLimitError,
    FileMetadata,
    FileRef,
    IsDirectoryError,
    NotDirectoryError,
    NotFoundError,
    ReadOnlyError,
    SourceMismatchError,
    StorageError,
)

if TYPE_CHECKING:
    from drive_tool.local import RangeReadResult

__all__ = [
    "LocalFileService",
    "ServiceError",
]

MAX_CONFIGURED_AGENTS = 6
MAX_CONFIGURED_GRANTS = 32
SERVICE_MAX_LIST_ENTRIES = 2000
SERVICE_MAX_LIMIT = 100
SERVICE_MAX_FIND_ENTRIES = 2000
SERVICE_MAX_DEPTH = 16
SERVICE_MAX_READ_BYTES = 1_048_576
SERVICE_MAX_NAME_CONTAINS = 256
MAX_INT64 = (1 << 63) - 1

_STATIC_ERROR_MESSAGES: dict[str, str] = {
    "invalid": "invalid request parameters",
    "denied": "operation denied",
    "not_found": "requested resource not found",
    "exists": "target resource already exists",
    "too_large": "request or resource exceeds configured limit",
    "busy": "service is busy",
    "unavailable": "service or storage is unavailable",
    "timeout": "operation timed out",
}

_RETRY_SAFE_CODES: frozenset[str] = frozenset({"unavailable", "busy", "timeout"})

class ServiceError(Exception):
    """Redacted boundary error with fixed code and retry/uncertainty metadata."""

    __slots__ = ("code", "outcome_uncertain", "retry_safe", "message")

    def __init__(
        self,
        code: str,
        *,
        outcome_uncertain: bool = False,
        retry_safe: bool = False,
    ) -> None:
        if code not in _STATIC_ERROR_MESSAGES:
            raise ValueError(f"unsupported ServiceError code: {code!r}")
        if type(outcome_uncertain) is not bool or type(retry_safe) is not bool:
            raise TypeError("outcome_uncertain and retry_safe must be exact bools")

        static_message = _STATIC_ERROR_MESSAGES[code]
        super().__init__(static_message)
        self.code: str = code
        self.outcome_uncertain: bool = outcome_uncertain
        self.retry_safe: bool = retry_safe
        self.message: str = static_message
        self.__cause__ = None
        self.__context__ = None
        self.__suppress_context__ = True

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"

    def __repr__(self) -> str:
        return (
            f"ServiceError(code={self.code!r}, "
            f"outcome_uncertain={self.outcome_uncertain!r}, "
            f"retry_safe={self.retry_safe!r})"
        )

class _GrantBinding:
    """Internal grant-scoped adapter/writer pair."""

    __slots__ = ("grant", "adapter", "writer", "closed")

    def __init__(
        self,
        grant: SourceGrant,
        adapter: LocalAdapter,
        writer: LocalWriter | None,
    ) -> None:
        self.grant = grant
        self.adapter = adapter
        self.writer = writer
        self.closed = False

def _raise_service_error(
    code: str,
    *,
    outcome_uncertain: bool = False,
    retry_safe: bool = False,
) -> Never:
    raise ServiceError(
        code,
        outcome_uncertain=outcome_uncertain,
        retry_safe=retry_safe,
    ) from None

def _require_nonbool_int(value: Any) -> int:
    if type(value) is bool or not isinstance(value, int):
        _raise_service_error("invalid")
    return int(value)

def _require_exact_bool(value: Any) -> bool:
    if type(value) is not bool:
        _raise_service_error("invalid")
    return value

def _parse_canonical_parts(file_id: Any, *, allow_root: bool) -> tuple[str, ...]:
    if not isinstance(file_id, str):
        _raise_service_error("invalid")
    try:
        parts = _parse_file_id(file_id)
    except UnsafePathError:
        _raise_service_error("denied")
    except (LocalStorageError, StorageError, ValueError, TypeError):
        _raise_service_error("invalid")

    if not isinstance(parts, tuple):
        _raise_service_error("invalid")
    if not parts and not allow_root:
        _raise_service_error("invalid")
    return parts

def _serialize_metadata(meta: FileMetadata) -> dict[str, Any]:
    return {
        "ref": {
            "source_id": meta.ref.source_id,
            "file_id": meta.ref.file_id,
        },
        "name": meta.name,
        "parent_id": meta.parent_id,
        "kind": meta.kind,
        "size_bytes": meta.size_bytes,
    }

def _translate_storage_exception(
    exc: Exception,
    *,
    is_write_in_flight: bool,
) -> ServiceError:
    if isinstance(exc, ServiceError):
        return exc

    if isinstance(exc, PolicyDeniedError):
        code = "denied"
    elif isinstance(exc, NotFoundError):
        code = "not_found"
    elif isinstance(exc, AlreadyExistsError):
        code = "exists"
    elif isinstance(exc, (UnsafePathError, ReadOnlyError)):
        code = "denied"
    elif isinstance(
        exc,
        (
            EnumerationLimitError,
            ReadLimitExceededError,
            WriteLimitExceededError,
        ),
    ):
        code = "too_large"
    elif isinstance(exc, (IsDirectoryError, NotDirectoryError)):
        code = "invalid"
    elif isinstance(
        exc,
        (
            AdapterClosedError,
            UnsupportedEntryError,
            UnsupportedPlatformError,
            SourceMismatchError,
            LocalStorageError,
            StorageError,
            OSError,
        ),
    ):
        code = "unavailable"
    elif isinstance(exc, ValueError):
        code = "invalid"
    else:
        raise exc

    if is_write_in_flight:
        return ServiceError(code, outcome_uncertain=True, retry_safe=False)
    return ServiceError(
        code,
        outcome_uncertain=False,
        retry_safe=(code in _RETRY_SAFE_CODES),
    )

class LocalFileService:
    """Synchronous grant-isolated local file operation layer."""

    def __init__(self, policies: tuple[AgentPolicy, ...]) -> None:
        if not isinstance(policies, tuple):
            raise ValueError("policies must be a tuple of AgentPolicy instances")
        if len(policies) > MAX_CONFIGURED_AGENTS:
            raise ValueError(
                f"configured agents ({len(policies)}) exceed maximum {MAX_CONFIGURED_AGENTS}"
            )

        total_grants = 0
        for policy in policies:
            if not isinstance(policy, AgentPolicy):
                raise ValueError("all policy entries must be AgentPolicy instances")
            if not isinstance(policy.grants, tuple):
                raise ValueError("policy.grants must be a tuple of SourceGrant instances")
            for grant in policy.grants:
                if not isinstance(grant, SourceGrant):
                    raise ValueError("all grants must be SourceGrant instances")
            total_grants += len(policy.grants)

        if total_grants > MAX_CONFIGURED_GRANTS:
            raise ValueError(
                f"total configured grants ({total_grants}) exceed maximum {MAX_CONFIGURED_GRANTS}"
            )

        self._policy_table = PolicyTable(policies)
        self._cond = threading.Condition(threading.Lock())
        self._active_leases = 0
        self._draining = False
        self._closing_adapters = False
        self._closed = False
        self._bindings: dict[tuple[str, str], _GrantBinding] = {}
        self._binding_list: list[_GrantBinding] = []

        opened_adapters: list[LocalAdapter] = []
        try:
            for policy in policies:
                for grant in policy.grants:
                    key = (policy.agent_id, grant.alias)
                    adapter = LocalAdapter(
                        grant.alias,
                        grant.root,
                        max_read_bytes=grant.max_read_bytes,
                        max_list_entries=SERVICE_MAX_LIST_ENTRIES,
                    )
                    opened_adapters.append(adapter)

                    writer: LocalWriter | None
                    try:
                        writer = LocalWriter(
                            adapter,
                            max_write_bytes=grant.max_write_bytes,
                        )
                    except (ValueError, TypeError):
                        if "save" not in grant.operations and not grant.max_write_bytes:
                            writer = None
                        else:
                            raise

                    binding = _GrantBinding(grant=grant, adapter=adapter, writer=writer)
                    self._bindings[key] = binding
                    self._binding_list.append(binding)
        except BaseException:
            for adapter in reversed(opened_adapters):
                try:
                    adapter.close()
                except Exception:
                    pass
            raise

    def _ensure_not_draining(self) -> None:
        with self._cond:
            if self._draining or self._closed:
                _raise_service_error(
                    "unavailable",
                    outcome_uncertain=False,
                    retry_safe=True,
                )

    def _authenticate_and_authorize(
        self,
        token: Any,
        source_id: Any,
        operation: str,
    ) -> tuple[AgentPolicy, SourceGrant]:
        self._ensure_not_draining()
        try:
            agent = self._policy_table.authenticate(token)
            grant = self._policy_table.authorize(agent.agent_id, source_id, operation)
            return agent, grant
        except PolicyDeniedError:
            _raise_service_error("denied", outcome_uncertain=False, retry_safe=False)
        except (TypeError, ValueError):
            _raise_service_error("invalid", outcome_uncertain=False, retry_safe=False)

    def _acquire_binding_lease(self, agent_id: str, alias: str) -> _GrantBinding:
        with self._cond:
            if self._draining or self._closed:
                _raise_service_error(
                    "unavailable",
                    outcome_uncertain=False,
                    retry_safe=True,
                )
            binding = self._bindings.get((agent_id, alias))
            if binding is None or binding.closed:
                _raise_service_error(
                    "unavailable",
                    outcome_uncertain=False,
                    retry_safe=True,
                )
            self._active_leases += 1
            return binding

    def _release_binding_lease(self) -> None:
        with self._cond:
            self._active_leases -= 1
            if self._active_leases <= 0:
                self._cond.notify_all()

    def close(self, *, timeout: float = 5.0) -> bool:
        if (
            type(timeout) is bool
            or not isinstance(timeout, (int, float))
            or math.isnan(float(timeout))
            or float(timeout) < 0.0
        ):
            raise ValueError("timeout must be a non-negative number")

        deadline = time.monotonic() + float(timeout)
        with self._cond:
            self._draining = True
            if self._closed:
                return True

            while self._active_leases > 0 or self._closing_adapters:
                if self._closed:
                    return True
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    return False
                self._cond.wait(timeout=remaining)

            if self._closed:
                return True
            self._closing_adapters = True

        first_exc: BaseException | None = None
        try:
            for binding in self._binding_list:
                if not binding.closed:
                    binding.closed = True
                    try:
                        binding.adapter.close()
                    except BaseException as exc:
                        if first_exc is None:
                            first_exc = exc
        finally:
            with self._cond:
                self._closing_adapters = False
                if first_exc is None:
                    self._closed = True
                self._cond.notify_all()

        if first_exc is not None:
            raise first_exc
        return True

    def list(
        self,
        token: str,
        source_id: str,
        file_id: str = ROOT_ID,
        *,
        limit: int = 20,
        offset: int = 0,
        name_contains: str | None = None,
    ) -> dict[str, Any]:
        agent, grant = self._authenticate_and_authorize(token, source_id, "list")
        parts = _parse_canonical_parts(file_id, allow_root=True)
        canonical_id = ROOT_ID if not parts else "/".join(parts)

        checked_limit = _require_nonbool_int(limit)
        if checked_limit < 1 or checked_limit > SERVICE_MAX_LIMIT:
            _raise_service_error("invalid")

        checked_offset = _require_nonbool_int(offset)
        if checked_offset < 0 or checked_offset > MAX_INT64:
            _raise_service_error("invalid")

        if name_contains is not None:
            if not isinstance(name_contains, str):
                _raise_service_error("invalid")
            if len(name_contains) > SERVICE_MAX_NAME_CONTAINS or "\x00" in name_contains:
                _raise_service_error("invalid")

        parent_ref = FileRef(grant.alias, canonical_id)
        binding = self._acquire_binding_lease(agent.agent_id, grant.alias)
        try:
            page = ListingService(binding.adapter).list_page(
                parent_ref,
                limit=checked_limit,
                offset=checked_offset,
                name_contains=name_contains,
                max_entries=SERVICE_MAX_LIST_ENTRIES,
            )
            return {
                "items": [_serialize_metadata(item) for item in page.items],
                "next_offset": page.next_offset,
            }
        except (PolicyDeniedError, LocalStorageError, StorageError, OSError, ValueError) as exc:
            raise _translate_storage_exception(exc, is_write_in_flight=False) from None
        finally:
            self._release_binding_lease()

    def find(
        self,
        token: str,
        source_id: str,
        file_id: str = ROOT_ID,
        *,
        name_contains: str,
        limit: int = 20,
        max_entries: int = SERVICE_MAX_FIND_ENTRIES,
        max_depth: int = 4,
    ) -> dict[str, Any]:
        agent, grant = self._authenticate_and_authorize(token, source_id, "find")
        parts = _parse_canonical_parts(file_id, allow_root=True)
        canonical_id = ROOT_ID if not parts else "/".join(parts)

        if not isinstance(name_contains, str):
            _raise_service_error("invalid")
        if (
            len(name_contains) < 1
            or len(name_contains) > SERVICE_MAX_NAME_CONTAINS
            or "\x00" in name_contains
            or not name_contains.strip()
        ):
            _raise_service_error("invalid")

        checked_limit = _require_nonbool_int(limit)
        if checked_limit < 1 or checked_limit > SERVICE_MAX_LIMIT:
            _raise_service_error("invalid")

        checked_max_entries = _require_nonbool_int(max_entries)
        if checked_max_entries < 1 or checked_max_entries > SERVICE_MAX_FIND_ENTRIES:
            _raise_service_error("invalid")

        checked_max_depth = _require_nonbool_int(max_depth)
        if checked_max_depth < 0 or checked_max_depth > SERVICE_MAX_DEPTH:
            _raise_service_error("invalid")

        parent_ref = FileRef(grant.alias, canonical_id)
        binding = self._acquire_binding_lease(agent.agent_id, grant.alias)
        try:
            result = search.find(
                binding.adapter,
                parent_ref,
                name_contains,
                max_results=checked_limit,
                max_entries=checked_max_entries,
                max_depth=checked_max_depth,
                case_sensitive=False,
            )
            return {
                "items": [_serialize_metadata(item) for item in result.items],
                "truncated": bool(result.truncated),
                "reason": result.reason,
                "inspected": int(result.inspected),
                "skipped": list(result.skipped),
            }
        except (PolicyDeniedError, LocalStorageError, StorageError, OSError, ValueError) as exc:
            raise _translate_storage_exception(exc, is_write_in_flight=False) from None
        finally:
            self._release_binding_lease()

    def read(
        self,
        token: str,
        source_id: str,
        file_id: str,
        *,
        offset: int = 0,
        length: int = 262144,
    ) -> RangeReadResult:
        agent, grant = self._authenticate_and_authorize(token, source_id, "read")
        parts = _parse_canonical_parts(file_id, allow_root=False)
        canonical_id = "/".join(parts)

        checked_offset = _require_nonbool_int(offset)
        if checked_offset < 0 or checked_offset > MAX_INT64:
            _raise_service_error("invalid")

        checked_length = _require_nonbool_int(length)
        if checked_length < 1:
            _raise_service_error("invalid")
        if checked_offset + checked_length > MAX_INT64:
            _raise_service_error("invalid")

        read_cap = min(int(grant.max_read_bytes), SERVICE_MAX_READ_BYTES)
        if checked_length > read_cap:
            _raise_service_error("too_large")

        target_ref = FileRef(grant.alias, canonical_id)
        binding = self._acquire_binding_lease(agent.agent_id, grant.alias)
        try:
            return binding.adapter.read_range(
                target_ref,
                offset=checked_offset,
                length=checked_length,
            )
        except (PolicyDeniedError, LocalStorageError, StorageError, OSError, ValueError) as exc:
            raise _translate_storage_exception(exc, is_write_in_flight=False) from None
        finally:
            self._release_binding_lease()

    def save(
        self,
        token: str,
        source_id: str,
        file_id: str,
        data: bytes,
        *,
        overwrite: bool = False,
        create_parents: bool = True,
    ) -> dict[str, Any]:
        agent, grant = self._authenticate_and_authorize(token, source_id, "save")
        parts = _parse_canonical_parts(file_id, allow_root=False)
        parent_parts = parts[:-1]
        leaf_name = parts[-1]

        if len(parent_parts) > SERVICE_MAX_DEPTH:
            _raise_service_error("invalid")

        checked_overwrite = _require_exact_bool(overwrite)
        checked_create_parents = _require_exact_bool(create_parents)

        if type(data) is not bytes:
            _raise_service_error("invalid")
        if len(data) > int(grant.max_write_bytes):
            _raise_service_error("too_large")

        canonical_id = "/".join(parts)
        binding = self._acquire_binding_lease(agent.agent_id, grant.alias)
        try:
            if binding.writer is None:
                _raise_service_error(
                    "denied",
                    outcome_uncertain=False,
                    retry_safe=False,
                )

            current_parent = FileRef(grant.alias, ROOT_ID)
            if checked_create_parents:
                built_parts: list[str] = []
                for component in parent_parts:
                    binding.writer.mkdir(current_parent, component, exist_ok=True)
                    built_parts.append(component)
                    current_parent = FileRef(grant.alias, "/".join(built_parts))
            elif parent_parts:
                current_parent = FileRef(grant.alias, "/".join(parent_parts))

            written_meta = binding.writer.write_bytes(
                current_parent,
                leaf_name,
                data,
                overwrite=checked_overwrite,
            )
            ref_obj = (
                written_meta.ref
                if getattr(written_meta, "ref", None) is not None
                else FileRef(grant.alias, canonical_id)
            )
            return {
                "ref": {
                    "source_id": ref_obj.source_id,
                    "file_id": ref_obj.file_id,
                },
                "bytes_written": len(data),
                "parents_may_have_been_created": bool(checked_create_parents),
            }
        except ServiceError:
            raise
        except (PolicyDeniedError, LocalStorageError, StorageError, OSError, ValueError) as exc:
            raise _translate_storage_exception(exc, is_write_in_flight=True) from None
        finally:
            self._release_binding_lease()
```

FILE: tests/test_file_service.py

```python
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

def _sha256_hex(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

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
        token_sha256=_sha256_hex(token),
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
            policies.append(_make_agent(f"agent-{idx}", f"secret-token-{idx}-value", (grant,)))

        service = LocalFileService(tuple(policies))
        try:
            for idx in range(6):
                res = service.read(f"secret-token-{idx}-value", "work", "id.txt")
                self.assertEqual(res.data, f"agent-{idx}".encode("utf-8"))
        finally:
            self.assertTrue(service.close())

        # Reject >6 configured agents before opening any LocalAdapter.
        extra_root = self._mkdir("agent_6")
        seven_policies = tuple(policies) + (
            _make_agent("agent-6", "secret-token-6-value", (_make_grant("work", extra_root),)),
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
                _make_agent(f"agent-{idx}", f"many-token-{idx}-value", grants)
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

        token_a = "token-agent-alpha-001"
        token_b = "token-agent-bravo-002"
        service = LocalFileService(
            (
                _make_agent("alpha", token_a, (_make_grant("shared", root_a),)),
                _make_agent("bravo", token_b, (_make_grant("shared", root_b),)),
            )
        )
        try:
            res_a = service.read(token_a, "shared", "only_a.txt")
            self.assertEqual(res_a.data, b"alpha-content")

            res_b = service.read(token_b, "shared", "only_b.txt")
            self.assertEqual(res_b.data, b"bravo-content")

            with self.assertRaises(ServiceError) as ctx_a:
                service.read(token_a, "shared", "only_b.txt")
            self.assertEqual(ctx_a.exception.code, "not_found")

            service.save(token_a, "shared", "written.txt", b"from-alpha")
            self.assertTrue((root_a / "written.txt").is_file())
            self.assertFalse((root_b / "written.txt").exists())
        finally:
            self.assertTrue(service.close())

    def test_readonly_denial_and_no_leaked_metadata(self) -> None:
        root = self._mkdir("ro_root")
        (root / "existing.txt").write_bytes(b"top-secret-payload")
        token = "ro-agent-token-xyz"
        ro_grant = _make_grant(
            "docs",
            root,
            operations=frozenset({"list", "find", "read"}),
            max_write_bytes=1024,
        )
        service = LocalFileService((_make_agent("reader", token, (ro_grant,)),))
        try:
            with self.assertRaises(ServiceError) as existing_exc:
                service.save(token, "docs", "existing.txt", b"overwrite-attempt", overwrite=True)
            with self.assertRaises(ServiceError) as missing_exc:
                service.save(token, "docs", "nonexistent/file.txt", b"new-attempt")

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
        orig_close = LocalAdapter.close

        def counting_close(adapter_self: LocalAdapter) -> None:
            close_counts.append(adapter_self)
            orig_close(adapter_self)

        grants = (
            _make_grant("g1", valid_root_1),
            _make_grant("g2", valid_root_2),
            _make_grant("g3", missing_root_3),
        )
        policy = _make_agent("agent-rollback", "rollback-token-123", grants)

        with mock.patch.object(LocalAdapter, "close", autospec=True, side_effect=counting_close):
            with self.assertRaises(Exception):
                LocalFileService((policy,))

        self.assertEqual(len(close_counts), 2)
        self.assertNotEqual(close_counts[0], close_counts[1])
        self.assertFalse(missing_root_3.exists())

    def test_auth_before_any_per_request_adapter_call(self) -> None:
        root = self._mkdir("auth_order_root")
        token = "valid-agent-token-999"
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
        token = "validation-token-123"
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
                    lambda: service.read(token, "src", "sample.txt", offset=True),
                    lambda: service.read(token, "src", "sample.txt", length=0),
                    lambda: service.read(
                        token,
                        "src",
                        "sample.txt",
                        offset=(1 << 63) - 1,
                        length=1,
                    ),
                    lambda: service.save(token, "src", ROOT_ID, b"abc"),
                    lambda: service.save(token, "src", "sample.txt", "not-bytes"),  # type: ignore[arg-type]
                    lambda: service.save(token, "src", "sample.txt", b"abc", overwrite=1),  # type: ignore[arg-type]
                    lambda: service.save(token, "src", "sample.txt", b"abc", create_parents=0),  # type: ignore[arg-type]
                    lambda: service.save(
                        token,
                        "src",
                        "/".join(f"d{i}" for i in range(17)) + "/leaf.txt",
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
                    service.read(token, "src", "sample.txt", length=1025)
                self.assertEqual(read_cap_ctx.exception.code, "too_large")
                self.assertFalse(read_cap_ctx.exception.outcome_uncertain)
                self.assertFalse(read_cap_ctx.exception.retry_safe)

                with self.assertRaises(ServiceError) as write_cap_ctx:
                    service.save(token, "src", "sample.txt", b"x" * 513)
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
        # Symlink inside subdir that search.find should skip rather than follow.
        os.symlink(root / "alpha_note.txt", sub / "linked_note.txt")

        token = "list-find-token-777"
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
            self.assertIn("alpha_note.txt", found_ids)
            self.assertIn("beta_note.txt", found_ids)
            self.assertIn("subdir/deep_note.txt", found_ids)
            self.assertNotIn("subdir/linked_note.txt", found_ids)
            self.assertTrue(any("linked_note.txt" in s for s in found["skipped"]))
        finally:
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

        token = "sparse-token-456"
        service = LocalFileService(
            (_make_agent("agent", token, (_make_grant("store", root),)),)
        )
        try:
            mid = service.read(token, "store", "sparse.bin", offset=1024 * 1024, length=10)
            self.assertEqual(mid.data, b"MARKER\x00\x00\x00\x00")
            self.assertFalse(mid.eof)

            tail = service.read(
                token,
                "store",
                "sparse.bin",
                offset=2 * 1024 * 1024 - 4,
                length=4,
            )
            self.assertEqual(tail.data, b"TAIL")
            self.assertTrue(tail.eof)

            at_eof = service.read(
                token,
                "store",
                "sparse.bin",
                offset=2 * 1024 * 1024,
                length=64,
            )
            self.assertEqual(at_eof.data, b"")
            self.assertTrue(at_eof.eof)
        finally:
            self.assertTrue(service.close())

    def test_save_no_overwrite_collision_and_explicit_overwrite(self) -> None:
        root = self._mkdir("overwrite_root")
        (root / "report.txt").write_bytes(b"original-bytes")
        token = "overwrite-token-321"
        service = LocalFileService(
            (_make_agent("agent", token, (_make_grant("work", root),)),)
        )
        try:
            with self.assertRaises(ServiceError) as ctx:
                service.save(token, "work", "report.txt", b"new-bytes", overwrite=False)
            self.assertEqual(ctx.exception.code, "exists")
            self.assertTrue(ctx.exception.outcome_uncertain)
            self.assertFalse(ctx.exception.retry_safe)
            self.assertEqual((root / "report.txt").read_bytes(), b"original-bytes")

            res = service.save(
                token,
                "work",
                "report.txt",
                b"replaced-bytes",
                overwrite=True,
                create_parents=False,
            )
            self.assertEqual(
                res,
                {
                    "ref": {"source_id": "work", "file_id": "report.txt"},
                    "bytes_written": len(b"replaced-bytes"),
                    "parents_may_have_been_created": False,
                },
            )
            self.assertEqual((root / "report.txt").read_bytes(), b"replaced-bytes")
        finally:
            self.assertTrue(service.close())

    def test_save_creates_missing_parents_in_one_call(self) -> None:
        root = self._mkdir("parents_root")
        token = "parents-token-654"
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
            self.assertEqual((root / "p" / "a" / "b.txt").read_bytes(), b"payload")
        finally:
            self.assertTrue(service.close())

    def test_save_symlink_parent_refused_and_outside_untouched(self) -> None:
        root = self._mkdir("symlink_root")
        outside = self._mkdir("outside_target")
        os.symlink(outside, root / "escape_dir")

        token = "symlink-token-111"
        service = LocalFileService(
            (_make_agent("agent", token, (_make_grant("work", root),)),)
        )
        try:
            with self.assertRaises(ServiceError) as ctx:
                service.save(
                    token,
                    "work",
                    "escape_dir/sub/pwned.txt",
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
        token = "fsync-token-222"
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
                    service.save(token, "work", "committed.txt", b"secret-file-bytes")

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
        token = "super-sensitive-bearer-token"
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
                    service.read(token, "work", "doc.txt")

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
        token = "concurrent-token-888"
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
                res = service.read(token, "work", "data.txt")
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
        token = "concurrent-close-token"
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
                target=lambda: service.read(token, "work", "item.txt")
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
                service.read(token, "work", "item.txt")
            self.assertEqual(post_close_ctx.exception.code, "unavailable")

    def test_fd_stability_and_resource_accounting_after_close(self) -> None:
        baseline_fds = _count_open_fds()
        roots = [self._mkdir(f"fd_root_{i}") for i in range(4)]
        for r in roots:
            (r / "f.txt").write_bytes(b"ok")

        grants = tuple(_make_grant(f"g{i}", roots[i]) for i in range(4))
        token = "fd-stability-token"
        service = LocalFileService((_make_agent("agent", token, grants),))
        for i in range(4):
            self.assertEqual(service.read(token, f"g{i}", "f.txt").data, b"ok")
            self.assertEqual(len(service.list(token, f"g{i}")["items"]), 1)

        self.assertTrue(service.close(timeout=2.0))
        self.assertEqual(service._active_leases, 0)
        if baseline_fds is not None:
            self.assertEqual(_count_open_fds(), baseline_fds)

if __name__ == "__main__":
    unittest.main()
```

TESTS_NOT_RUN
STATUS: GENERATED
