# D046 — cloud Sarvam: assembly and execution of the DeepSeek service policy

**Builder/assembler evidence — not independent acceptance.** Implementation assembly and actual test
execution of the D045 DeepSeek candidate. No changes to range/storage/HTTP code, no main merge, no
deployment, no package installs, no real tokens/roots.

## 1. Provenance and pins

| Item | Value |
| ---- | ----- |
| D046 brief | `drive-tool` @ `b0f5d8d7f851888553492144f52b9ae0c09b5f3f` `tasks/d046-policy-assembly.md` |
| Assembly base (main) | `drive-tool` @ `232fd03a3f50013adf62937e042d30c495aeb840` ("Record accepted range reads and verified integration"; parent = PR5 merge `1515182d…`) |
| Director contract | `drive-tool` @ `0a1c8bf20b197c3c06bd54820a0957772ff3d940` `tasks/d045-service-policy-implementation.md` |
| Generated answer | `drop` @ `1aa5ba7645526cf3d19238ccee84c8caa082c5ec` `drive-tool/module-006/d045-deepseek-service-policy.md` (two complete FILE blocks) |
| Generated answer bytes | SHA-256 `820c9b43d6f22222e937fd9bbc66a50567dcfffce136e6318281157545d00fac` (re-fetched via raw GitHub; byte-identical to the tool download) |
| Working branch | `feature/module-006a-policy`, created from `232fd03a…` |
| Branch head / tree | head `dc3c2af7a83055903708b2622ef05c735ebb1210`, tree `3f096eddbc5b509e2f0f8e67892f918b522eaa52` |

The two generated files were extracted **byte-for-byte** from the fenced ```python blocks of the pinned
answer file (no reconstruction from summaries). Extraction script: `scripts/extract.py`. Verbatim file
hashes: `service_policy.py` `537837dd…`, `test_service_policy.py` `d8d77768…`.

Allowed candidate paths only: `drive_tool/service_policy.py`, `tests/test_service_policy.py`.

## 2. Commits on `feature/module-006a-policy`

| # | Commit | Message |
| - | ------ | ------- |
| 0 | `232fd03a…` | base (main) |
| 1 | `dae2ca040550adea80bee3541e5cfd9db6080127` | Import D045 DeepSeek service policy **verbatim** (no edits) |
| 2 | `945016b2e0c1fcaaca53c8ff1747c138cc824bde` | Fix: `PolicyTable._by_id` immutable lookup (contract violation) |
| 3 | `dc3c2af7a83055903708b2622ef05c735ebb1210` | Fix: `test_visible_ascii_bounds_accepted` errored instead of asserting |

The final committed files were re-fetched from the branch and match the locally tested tree
**byte-for-byte** (SHA-256 below).

## 3. Initial execution (verbatim candidate, before any fix)

Full `unittest discover -s tests` and the focused policy module, on Python 3.11.2 and 3.12.13:

| Run | Result |
| --- | ------ |
| full suite 3.11.2 | **Ran 413 tests, FAILED (errors=1)** — exit 1 |
| full suite 3.12.13 | **Ran 413 tests, FAILED (errors=1)** — exit 1 |
| policy module 3.11.2 | **Ran 62 tests, FAILED (errors=1)** — exit 1 |
| policy module 3.12.13 | **Ran 62 tests, FAILED (errors=1)** — exit 1 |

413 = 351 baseline (verified: base has 351) + 62 new policy tests. The single error is in the generated
**test**, not the module:

```
ERROR: test_visible_ascii_bounds_accepted (test_service_policy.AuthenticationTests)
  File ".../tests/test_service_policy.py", line 300, in test_visible_ascii_bounds_accepted
    self.table.authenticate('!' * 32)  # unknown -> denied
  File ".../drive_tool/service_policy.py", line 192, in authenticate
    raise PolicyDeniedError()
drive_tool.service_policy.PolicyDeniedError: access denied
```

Raw logs: `logs/initial-full-3.11.log`, `logs/initial-full-3.12.log`, `logs/initial-policy-3.11.log`,
`logs/initial-policy-3.12.log`.

## 4. The two Codex-flagged items — checked against exact bytes

### 4a. NUL / single-backslash root checks — **NOT a violation (no fix)**

Codex static inspection suggested the root validator "appears to check a literal escaped backslash-x00
rather than actual NUL" and that "a doubled backslash literal may allow one backslash". Inspected at the
**byte level** (`repr` of the exact source lines):

```
54  "    if '\\x00' in value:"     -> source is  if '\x00' in value:   (Python NUL escape)
56  "    if '\\\\' in value:"     -> source is  if '\\' in value:     (one backslash char)
```

Both are correct Python. Probe against the final module using **actual characters**
(`probe/probe-output.txt`):

```
actual NUL  '/x'+NUL+'y'      : ValueError: root must not contain NUL
single backslash  '/x\y'      : ValueError: root must not contain backslash
two backslashes  '/x\\y'      : ValueError: root must not contain backslash
normal  '/srv/data'           : ACCEPTED
root '/'                      : ACCEPTED
trailing slash  '/foo/'       : ValueError: root must not contain empty components
```

An actual NUL is rejected and a single backslash is rejected. **No change made** — the flag is not a
confirmed violation. (A separate root check for empty components also rejects a trailing slash, as the
contract's grammar requires.)

### 4b. Registry lookup `PolicyTable._by_id` — **CONFIRMED violation (fixed, commit 2)**

Contract: *"Make internal state immutable or private immutable copies, no externally mutable
dictionaries."* The generated code assigned a **plain dict copy**:

```python
self._by_id: dict[str, AgentPolicy] = dict(by_id)
```

It is private but mutable and externally reachable. The probe demonstrates the exposure: before the fix,
`table._by_id['a'] = <forged AgentPolicy>` changed authorization (`authorize('a','m','read').root`
became `/evil`). Minimal fix, semantics preserved:

- **Before:** `self._by_id: dict[str, AgentPolicy] = dict(by_id)`
- **After:** `self._by_id: Mapping[str, AgentPolicy] = MappingProxyType(dict(by_id))` (`from types import MappingProxyType`)

`self._agents` and `self._digests` were already tuples (immutable); `_by_id` was the only mutable
member. After the fix the probe shows `type(_by_id) == <class 'mappingproxy'>`, item assignment raises
`TypeError`, and `authorize` still returns the exact configured grant. External mutation of caller
inputs cannot change permissions (already a copy; unchanged).

### 4c. Test-fixture escaping — **correct (no fix)**

The generated test fixtures use real characters, not textual stand-ins: `test_root_nul_rejected` passes
`root='/x\x00y'` (a real NUL) and `test_root_backslash_rejected` passes `root='/x\\y'` (a real single
backslash). They do **not** mirror any escaping mistake.

## 5. The generated-test defect — **CONFIRMED (fixed, commit 3)**

`test_visible_ascii_bounds_accepted` called `authenticate('!' * 32)` with **no** `assertRaises`; an
unknown-but-well-formed token is denied, so the test **always errored** (the cause of the initial
`errors=1`). The contract requires the visible-ASCII charset bound (codepoints 33..126) to be
demonstrably accepted; an erroring test provides no such evidence.

- **Before:** `self.table.authenticate('!' * 32)  # uncaught PolicyDeniedError`
- **After:** configure agents whose tokens are `'!'*32` (cp 33) and `'~'*32` (cp 126) and
  `assertIs(authenticate(tok), exact AgentPolicy)`.

This **strengthens** the test (proves boundary-codepoint acceptance by identity) rather than weakening
it; no assertion was removed, and the test count is unchanged (still one method). No other generated
test was altered.

## 6. Final execution (after fixes)

| Run | Result |
| --- | ------ |
| full suite 3.11.2 | **Ran 413 tests, OK** — exit 0 |
| full suite 3.12.13 | **Ran 413 tests, OK** — exit 0 |
| policy module 3.11.2 | **Ran 62 tests, OK** — exit 0 |
| policy module 3.12.13 | **Ran 62 tests, OK** — exit 0 |

Raw logs: `logs/final-full-3.11.log`, `logs/final-full-3.12.log`, `logs/final-policy-3.11.log`,
`logs/final-policy-3.12.log`. Zero skips (final line is plain `OK`).

## 7. Mutation evidence (isolated copies)

Runner: `scripts/mutation_runner.py`. Each mutation is applied to an **isolated copy** of the final tree
(never the committed candidate), the focused policy module is run on 3.11 and 3.12, and the copy is
discarded. **6 mutations, 6 caught, 0 survived** on both interpreters; every catch is a real
`AssertionError`/`assertRaises` failure (no syntax/import fake positives). Raw per-mutant logs:
`logs/mutations/`; summary: `logs/mutation-summary.txt`.

| # | Mutation (in `drive_tool/service_policy.py`) | Intended caught assertion | Caught by (3.11 = 3.12) |
| - | ------------------------------------------- | ------------------------- | ----------------------- |
| M1 | early authentication return (`return agent` on first match) | full scan, no early return | `test_compares_all_digests_no_early_return` (3 != 5 comparisons) |
| M2 | duplicate digest acceptance (`if False and …`) | duplicate credential rejection | `test_duplicate_token_digest_rejected` |
| M3 | cross-agent alias fallback (scan all agents for the alias) | per-agent alias isolation | `test_allowed_returns_exact_object`, `test_same_alias_across_agents_isolated` |
| M4 | read-only save bypass (`return grant` regardless of op) | readonly denial / caps don't grant | `test_caps_do_not_grant_absent_operations`, `test_denied_message_identical_across_reasons`, `test_read_only_denies_save`, `test_save_only_denies_read` |
| M5 | malformed root acceptance (drop NUL/backslash checks) | root grammar enforcement | `test_root_backslash_rejected`, `test_root_nul_rejected` |
| M6 | cap upper-bound bypass (`value < 1` only) | cap range enforcement | `test_cap_too_large_rejected` |

## 8. Contract-coverage checklist (D045 §Tests)

Present and meaningful in the final tree: constructor type/boundary/duplicate failures; immutable
tuples/frozensets/frozen dataclasses; digest/root redaction in `repr` and in invalid-input exceptions;
valid-token identity; invalid tokens indistinguishable; **full digest scan via `hmac.compare_digest`
spy (no early return)**; no raw-token retention; same alias across two agents never crosses;
read-only vs save denial and caps do not grant rights; invalid/unhashable agent/alias/op consistently
denied; allowed grant returns the exact object; purity (no filesystem/network) guard.

## 9. Scope, blockers, and honesty notes

- **Scope held.** Only the two allowed paths changed; no storage/range/HTTP edits; no `main` merge; no
  deployment; no installs; synthetic tokens/roots only. The branch is isolated.
- **Two confirmed fixes**, each in its own attributed commit (2 and 3). The NUL/backslash flag was
  checked and is **not** a violation; no speculative refactor was made.
- **No new blocker.** One observed, non-blocking boundary: `PolicyTable` internal state is private and
  now immutable, but this is not a process-isolation boundary — arbitrary hostile in-process Python
  object mutation is out of scope, as the contract states.
- **Not independent acceptance.** These are builder/assembler results from one host; independent
  review/execution and any merge are the director's to arrange.
