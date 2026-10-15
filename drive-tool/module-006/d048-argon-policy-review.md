# d048 (gemini)

- status: done
- chat: https://gemini.google.com/app/db6823a7a1085b71
- model: 4 argon (thinking: high)
- finished: 2026-10-15T16:53:27Z

## Question

Gemini, I need D048 independent security/code review of the complete policy production module and exact contract supplied from the pinned file. Necessary compact inline file fallback is used because your link/upload retrieval previously failed. Verify4Argon/high is actually available; if quota still blocks, fail honestly and do not send on Flash-Lite. Exact candidate dc3c2af7; report scope, quote actual code, verdict, concrete blockers and TESTS_NOT_RUN. No code/test/merge/deploy. End STATUS: REVIEWED.

(input files: Dolesh-avkalan/drive-tool:tasks/d048-policy-review.txt@4878271e1219d328b18e6bdd61afe84be9bb2483)

## Answer

Verdict: ACCEPT WITH NITS (0 Blockers)

Model Verification: Reviewed on high-reasoning frontier tier (not downgraded to Flash-Lite).

Scope: Static security and contract review of drive_tool/service_policy.py at candidate dc3c2af7a83055903708b2622ef05c735ebb1210 (feature/module-006a-policy, base 232fd03) against the D045 director contract. Pure in-memory module only; no code execution, test execution, filesystem work, merge, or deployment performed (TESTS_NOT_RUN).

### Proof of Code Receipt (Reviewed Branch Condition)

From PolicyTable.authenticate (lines 178–194) and _require_root (lines 53–65):

```python
        if length < _TOKEN_MIN_LEN or length > _TOKEN_MAX_LEN:
            raise PolicyDeniedError()
        for ch in token:
            cp = ord(ch)
            if cp < _TOKEN_MIN_CP or cp > _TOKEN_MAX_CP:
                raise PolicyDeniedError()
```

```python
    for component in value.split('/')[1:]:
        if component == '':
            raise ValueError('root must not contain empty components')
        if component == '.' or component == '..':
            raise ValueError('root must not contain dot components')
```

### Concrete Blockers

None. No reachable runtime errors, authentication/authorization bypasses, cross-agent alias leaks, or secret-redaction failures were found.

### Non-Blocking Nits (Maintainability / Static Analysis Only)

1. Unimported Mapping in method-body variable annotation (PolicyTable.__init__, line 164)

- Reachability analysis: Line 164 annotates self._by_id: Mapping[str, AgentPolicy] = MappingProxyType(dict(by_id)), while Mapping is never imported from collections.abc. This is not a reachable runtime error: Python does not evaluate attribute/variable annotations inside function bodies at runtime (and from __future__ import annotations is also active on line 9), nor does typing.get_type_hints(PolicyTable.__init__) inspect function-body statements. However, static type checkers and linters (mypy, pyright, ruff F821) will report Mapping as an undefined name.

- Minimal fix: Import Mapping on line 15 (from collections.abc import Mapping) or drop the redundant local annotation on line 164.

### Security & Contract Audit Matrix

- Hostile Plain Request Values (JSON Primitives) & Denied-Error Uniformity (PolicyDeniedError, lines 28–39; authenticate, lines 167–194; authorize, lines 196–225):

- PolicyDeniedError.__init__ (lines 38–39) ignores all positional and keyword arguments and initializes super().__init__(_DENIED) with fixed 'access denied'.

- authenticate(token) rejects non-str JSON primitives (None, bool, int, float, list, dict) at lines 175–176 with PolicyDeniedError() before length or ordinal checks.

- authorize(agent_id, source_alias, operation) explicitly verifies isinstance(..., str) for all three arguments (lines 204–209) before membership tests in OPERATIONS (line 210) or self._by_id.get(agent_id) (line 212), preventing TypeError: unhashable type on list/dict inputs. Lines 223–225 also wrap the method in a defensive catch-all except Exception: raise PolicyDeniedError() from None.

- Token Bounds, Digest Uniqueness & Bounded Full Scan (PolicyTable.__init__, lines 143–165; authenticate, lines 167–194):

- PolicyTable.__init__ enforces unique agent.token_sha256 across all agents via seen_digests: set[bytes] (lines 151, 158–159), preventing a single credential from matching multiple agents.

- authenticate enforces length bounds of 32 through 256 characters (lines 23–24, 177–179) and visible ASCII codepoints 33 through 126 (lines 25–26, 180–183), hashes the ASCII bytes once with hashlib.sha256 (line 185), and iterates over all configured (agent, stored) pairs using hmac.compare_digest(candidate, stored) without early return or break (lines 188–194). (Within the contract's scope, this provides a bounded full scan of up to 32 digests using compare_digest, without claiming full Python VM constant-time execution.)

- Constructor Input Bounds & Grammar Validation (_require_identifier, lines 41–46; _require_operations, lines 68–78; _require_cap, lines 80–85; AgentPolicy.__post_init__, lines 112–132):

- _IDENT_RE = re.compile(r'[A-Za-z0-9_-]{1,64}') with fullmatch (lines 21, 44) strictly bounds alias and agent_id to 1..64 ASCII identifier characters (and avoids $ trailing-newline edge cases).

- _require_cap (lines 80–85) explicitly rejects bool (isinstance(value, bool)) before checking int and enforces 1 to MAX_TRANSFER_BYTES (1048576).

- AgentPolicy.__post_init__ validates token_sha256 is exact bytes of length 32 (rejecting bytearray/memoryview, lines 114–119) and grants is a nonempty tuple of at most 32 exact SourceGrant instances (type(grant) is not SourceGrant, line 128) with unique alias values per agent (lines 126–132).

- PolicyTable.__init__ validates agents is a nonempty tuple of at most 32 exact AgentPolicy instances (type(agent) is not AgentPolicy, line 154) with unique agent_id and token_sha256.

- Actual NUL, Backslash & Path Component Checks (_require_root, lines 48–66):

- Rejects non-str with TypeError (lines 49–50), empty string with ValueError (lines 51–52), non-absolute paths (value[0] != '/', lines 53–54), NUL bytes ('\x00' in value, lines 55–56), and backslashes ('\\' in value, lines 57–58).

- Returns '/' directly (lines 59–60); for all other paths, splits on '/' and rejects empty components ('', catching both // and trailing /) as well as '.' and '..' (lines 61–65). Performs zero filesystem or os operations, leaving anchoring/containment to LocalAdapter.

- Immutable Container Ownership (SourceGrant, AgentPolicy, PolicyTable):

- OPERATIONS is a frozenset; _require_operations requires frozenset and rejects mutable sets (lines 69–70).

- SourceGrant and AgentPolicy are @dataclass(frozen=True) backed by frozenset and tuple.

- PolicyTable.__init__ stores private immutable copies (self._agents = tuple(agents), self._by_id = MappingProxyType(dict(by_id)), self._digests = tuple(digests)) with __slots__ = ('_agents', '_by_id', '_digests') (lines 141, 163–165), preventing external container mutation (subject to standard in-process Python boundaries).

- Root, Digest & Token Redaction:

- SourceGrant.root (line 92) and AgentPolicy.token_sha256 (line 109) specify field(repr=False).

- All TypeError, ValueError, and PolicyDeniedError exceptions use static string literals or internal field names and never interpolate caller-supplied values, roots, digests, or tokens.

- PolicyTable.authenticate never caches, logs, or stores the raw token or candidate digest on self.

- Per-Agent Alias Isolation & Passive Caps (authorize, lines 196–225):

- Two agents can configure the same alias with distinct roots because alias uniqueness is enforced per AgentPolicy (lines 126–132), not globally in PolicyTable.

- authorize resolves agent = self._by_id.get(agent_id) (line 212) and searches only agent.grants (line 215), never falling back to or leaking the existence of aliases on other agents.

- max_read_bytes and max_write_bytes are not consulted by authorize; an operation is permitted strictly when operation in grant.operations (line 217).

TESTS_NOT_RUN

STATUS: REVIEWED
