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


def _canonical_id(parts: tuple[str, ...]) -> str:
    """Rebuild the canonical ``p/...`` FileRef id from parsed path parts.

    ``local._parse_file_id`` strips the ``p/`` prefix; every FileRef handed to
    an adapter must carry the canonical ``p/...`` form again, so the service
    never constructs a bare relative id the adapter would reject.
    """
    if not parts:
        return ROOT_ID
    return "p/" + "/".join(parts)

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
        canonical_id = _canonical_id(parts)

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
        canonical_id = _canonical_id(parts)

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
        canonical_id = _canonical_id(parts)

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

        canonical_id = _canonical_id(parts)
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
                    current_parent = FileRef(
                        grant.alias, _canonical_id(tuple(built_parts))
                    )
            elif parent_parts:
                current_parent = FileRef(grant.alias, _canonical_id(parent_parts))

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
