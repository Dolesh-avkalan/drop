"""D045: minimal service authentication / grant-policy boundary.

Pure in-memory policy objects. This module deliberately performs no
filesystem, network, or configuration-file work and does not import
``os`` or ``socket``. Filesystem containment and adapter anchoring are
the responsibility of the LocalAdapter constructed later by the caller.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass, field
from types import MappingProxyType

OPERATIONS: frozenset[str] = frozenset({'find', 'list', 'read', 'save'})
MAX_TRANSFER_BYTES: int = 1048576

_DENIED = 'access denied'
_IDENT_RE = re.compile(r'[A-Za-z0-9_-]{1,64}')

_TOKEN_MIN_LEN = 32
_TOKEN_MAX_LEN = 256
_TOKEN_MIN_CP = 33
_TOKEN_MAX_CP = 126

class PolicyDeniedError(Exception):
    """Raised for every authentication and authorization failure.

    The public message is always the fixed string ``'access denied'``.
    Callers cannot distinguish denial reasons and no user-supplied
    value is ever echoed back.
    """

    __slots__ = ()

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(_DENIED)

def _require_identifier(value, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f'{name} must be str')
    if _IDENT_RE.fullmatch(value) is None:
        raise ValueError(f'{name} is not a valid identifier')
    return value

def _require_root(value) -> str:
    if not isinstance(value, str):
        raise TypeError('root must be str')
    if not value:
        raise ValueError('root must be nonempty')
    if value[0] != '/':
        raise ValueError('root must be absolute')
    if '\x00' in value:
        raise ValueError('root must not contain NUL')
    if '\\' in value:
        raise ValueError('root must not contain backslash')
    if value == '/':
        return value
    for component in value.split('/')[1:]:
        if component == '':
            raise ValueError('root must not contain empty components')
        if component == '.' or component == '..':
            raise ValueError('root must not contain dot components')
    return value

def _require_operations(value) -> frozenset:
    if not isinstance(value, frozenset):
        raise TypeError('operations must be a frozenset')
    if not value:
        raise ValueError('operations must be nonempty')
    for op in value:
        if not isinstance(op, str):
            raise TypeError('operations members must be str')
        if op not in OPERATIONS:
            raise ValueError('unsupported operation')
    return value

def _require_cap(value, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f'{name} must be int')
    if value < 1 or value > MAX_TRANSFER_BYTES:
        raise ValueError(f'{name} out of range')
    return value

@dataclass(frozen=True)
class SourceGrant:
    """Per-agent authorization to use an alias against a trusted root."""

    alias: str
    root: str = field(repr=False)
    operations: frozenset[str]
    max_read_bytes: int = MAX_TRANSFER_BYTES
    max_write_bytes: int = MAX_TRANSFER_BYTES

    def __post_init__(self) -> None:
        _require_identifier(self.alias, 'alias')
        _require_root(self.root)
        _require_operations(self.operations)
        _require_cap(self.max_read_bytes, 'max_read_bytes')
        _require_cap(self.max_write_bytes, 'max_write_bytes')

@dataclass(frozen=True)
class AgentPolicy:
    """Authenticated agent and the set of source grants it may use."""

    agent_id: str
    token_sha256: bytes = field(repr=False)
    grants: tuple[SourceGrant, ...]

    def __post_init__(self) -> None:
        _require_identifier(self.agent_id, 'agent_id')
        if not isinstance(self.token_sha256, bytes) or isinstance(
            self.token_sha256, (bytearray, memoryview)
        ):
            raise TypeError('token_sha256 must be bytes')
        if len(self.token_sha256) != 32:
            raise ValueError('token_sha256 must be exactly 32 bytes')
        if not isinstance(self.grants, tuple):
            raise TypeError('grants must be a tuple')
        if not self.grants:
            raise ValueError('grants must be nonempty')
        if len(self.grants) > 32:
            raise ValueError('grants must contain at most 32 entries')
        seen: set[str] = set()
        for grant in self.grants:
            if type(grant) is not SourceGrant:
                raise TypeError('grants must contain SourceGrant instances')
            if grant.alias in seen:
                raise ValueError('duplicate alias in grants')
            seen.add(grant.alias)

class PolicyTable:
    """Immutable registry of agents and their grants.

    Authenticate a raw bearer token with :meth:`authenticate`, then
    authorize a request tuple with :meth:`authorize`.
    """

    __slots__ = ('_agents', '_by_id', '_digests')

    def __init__(self, agents: tuple[AgentPolicy, ...]) -> None:
        if not isinstance(agents, tuple):
            raise TypeError('agents must be a tuple')
        if not agents:
            raise ValueError('agents must be nonempty')
        if len(agents) > 32:
            raise ValueError('agents must contain at most 32 entries')
        by_id: dict[str, AgentPolicy] = {}
        seen_digests: set[bytes] = set()
        digests: list[bytes] = []
        for agent in agents:
            if type(agent) is not AgentPolicy:
                raise TypeError('agents must contain AgentPolicy instances')
            if agent.agent_id in by_id:
                raise ValueError('duplicate agent_id')
            if agent.token_sha256 in seen_digests:
                raise ValueError('duplicate token digest')
            by_id[agent.agent_id] = agent
            seen_digests.add(agent.token_sha256)
            digests.append(agent.token_sha256)
        self._agents: tuple[AgentPolicy, ...] = tuple(agents)
        self._by_id: Mapping[str, AgentPolicy] = MappingProxyType(dict(by_id))
        self._digests: tuple[bytes, ...] = tuple(digests)

    def authenticate(self, token) -> AgentPolicy:
        """Return the configured AgentPolicy matching a raw bearer token.

        Any failure (wrong type, wrong length, non-visible-ASCII char,
        unknown token) raises the identical PolicyDeniedError so that
        callers cannot distinguish reasons. The raw token is hashed
        once and never stored on the instance.
        """
        if not isinstance(token, str):
            raise PolicyDeniedError()
        length = len(token)
        if length < _TOKEN_MIN_LEN or length > _TOKEN_MAX_LEN:
            raise PolicyDeniedError()
        for ch in token:
            cp = ord(ch)
            if cp < _TOKEN_MIN_CP or cp > _TOKEN_MAX_CP:
                raise PolicyDeniedError()
        try:
            candidate = hashlib.sha256(token.encode('ascii')).digest()
        except UnicodeEncodeError:
            raise PolicyDeniedError() from None
        match: AgentPolicy | None = None
        for agent, stored in zip(self._agents, self._digests):
            if hmac.compare_digest(candidate, stored):
                match = agent
        if match is None:
            raise PolicyDeniedError()
        return match

    def authorize(self, agent_id, source_alias, operation) -> SourceGrant:
        """Return the exact configured grant for (agent, alias, operation).

        Trusted internal call after authentication. Never falls back to
        another agent's grants and never reveals whether a source alias
        exists elsewhere. Any denial raises the same PolicyDeniedError.
        """
        try:
            if not isinstance(agent_id, str):
                raise PolicyDeniedError()
            if not isinstance(source_alias, str):
                raise PolicyDeniedError()
            if not isinstance(operation, str):
                raise PolicyDeniedError()
            if operation not in OPERATIONS:
                raise PolicyDeniedError()
            agent = self._by_id.get(agent_id)
            if agent is None:
                raise PolicyDeniedError()
            for grant in agent.grants:
                if grant.alias == source_alias:
                    if operation in grant.operations:
                        return grant
                    raise PolicyDeniedError()
            raise PolicyDeniedError()
        except PolicyDeniedError:
            raise
        except Exception:
            # Defensive: never leak KeyError/TypeError for arbitrary inputs.
            raise PolicyDeniedError() from None
