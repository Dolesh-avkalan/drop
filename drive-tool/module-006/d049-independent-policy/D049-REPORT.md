# D049 — independent policy execution and adversarial review

**Independent reviewer run — fresh context, not the D044/D046 builder chat.**
Verdict: **ACCEPT WITH NITS.** No blocker. The candidate is exactly the two allowed new
files; byte identities and provenance verify; the committed suite and the focused policy
module pass on Python 3.11.2 and 3.12.13 with zero skips; all six builder mutations are
caught semantically on both interpreters; and a fresh adversarial probe suite (103 checks)
passes. The only findings are one cosmetic annotation nit and one explicitly out-of-scope
process-boundary observation.

No source edits, no branch edits, no installs, no main merge, no deployment were performed.
All work is read-only verification plus new evidence files.

---

## 1. Exact pins

| Item | Value |
| ---- | ----- |
| Candidate repo/branch | `Dolesh-avkalan/drive-tool` `feature/module-006a-policy` |
| Candidate head | `dc3c2af7a83055903708b2622ef05c735ebb1210` |
| Candidate tree | `3f096eddbc5b509e2f0f8e67892f918b522eaa52` |
| Candidate parent | `945016b2e0c1fcaaca53c8ff1747c138cc824bde` |
| Base | `232fd03a3f50013adf62937e042d30c495aeb840` (tree `09a207fb1376c1db9c7242a4b9ddbb62acb2de1a`, parent = PR5 merge `1515182d0f273518d20a2ef80b5182cf6b36def2`) |
| Branch commits | `dae2ca04…` (verbatim import), `945016b2…` (`_by_id` fix), `dc3c2af7…` (test fix) |
| Director contract | `Dolesh-avkalan/drive-tool` `tasks/d045-service-policy-implementation.md` @ `0a1c8bf20b197c3c06bd54820a0957772ff3d940` |
| Generated answer | `Dolesh-avkalan/drop` @ `1aa5ba7645526cf3d19238ccee84c8caa082c5ec` `drive-tool/module-006/d045-deepseek-service-policy.md` |
| Builder drop | `Dolesh-avkalan/drop` @ `3e030403b9c9882a10cee38b0b1d551697a25971` `drive-tool/module-006/d046-policy-assembly/` |
| D049 brief | `Dolesh-avkalan/drive-tool` @ `4878271e1219d328b18e6bdd61afe84be9bb2483` `tasks/d049-policy-independent.md` |

Git blob SHAs of the two committed files (from the tree API):
`drive_tool/service_policy.py` = `3e58f99ab4ad0286838743b25cef138638131305`;
`tests/test_service_policy.py` = `97bbf75bd967c29a9558514332e12bd3c908e7b9`.

## 2. Byte identity and scope

Re-fetched from GitHub and hashed locally. Every identity matches the D046 manifest:

| Artifact | SHA-256 (computed by this review) | Expected | Match |
| -------- | --------------------------------- | -------- | ----- |
| candidate `drive_tool/service_policy.py` | `8feedd9499f52df32449acb4ce8d1d2e2a32e7cbf7d5ab2bed2f1a8547d9aa1c` | `8feedd94…` | yes |
| candidate `tests/test_service_policy.py` | `ada2c59e46cab5cc6b188b8d1ddefa9a25cfebe7d40e64df3ad65b3d5501959b` | `ada2c59e…` | yes |
| generated answer md | `820c9b43d6f22222e937fd9bbc66a50567dcfffce136e6318281157545d00fac` | `820c9b43…` | yes |
| verbatim `service_policy.py` (block 0) | `537837dd2f90505ed0ef37905e4f5e0cdfcc2e39dc2c808dfc32e7b97aeedd6e` | `537837dd…` | yes |
| verbatim `test_service_policy.py` (block 1) | `d8d777681dd310e6612ac4bfea4c9389d770bb4d95bacfacfd6460e8b4db7f4d` | `d8d77768…` | yes |

**Provenance chain verified end to end:** the generated answer md hashes to `820c9b43…`;
its two fenced ```python blocks extract byte-for-byte to `537837dd…` / `d8d77768…`, the
verbatim candidate; the committed branch files differ from the verbatim candidate by exactly
the two attributed fix deltas (section 4).

**Scope (via the compare API, `232fd03a…...dc3c2af7…`):** `ahead_by=3`, and exactly **two**
files changed, both `status: added` — `drive_tool/service_policy.py` (+225) and
`tests/test_service_policy.py` (+492). No existing file was touched. This matches the D045
"New paths ONLY" rule and the brief's scope claim.

## 3. Independent execution (fresh, this review)

Invocation: `python -m unittest discover -s tests` from the tree root (namespace-package
discovery), plus `python -m unittest -v tests.test_service_policy`. Interpreters available and
actually used: **CPython 3.11.2 and 3.12.13** (Debian 12, gvisor kernel). **No 3.13/3.14 is
present and none was run** — no such claim is made here.

| Run | 3.11.2 | 3.12.13 |
| --- | ------ | ------- |
| full suite (candidate) | Ran 413, **OK**, 0 skips | Ran 413, **OK**, 0 skips |
| policy module (candidate) | Ran 62, **OK** | Ran 62, **OK** |
| full suite (base `232fd03a…`) | Ran 351, **OK** | Ran 351, **OK** |

413 = 351 baseline + 62 new; the 351 original tests are preserved unchanged (base tree =
candidate minus the two new files; verified by the compare API showing only additions). Zero
skips confirmed (final line is plain `OK`; no `skipped=` / `OK (…)` markers).

**Initial-state corroboration.** Rebuilt the pre-fix tree from the verbatim blocks and ran it:
413 tests, **FAILED (errors=1)** on both interpreters, the single error being
`test_visible_ascii_bounds_accepted` (uncaught `PolicyDeniedError` at
`tests/test_service_policy.py:300`). This independently reproduces the D046 initial-state claim.

Raw logs: `logs/d049-full-*.log`, `logs/d049-policy-*.log`, `logs/d049-base-full-*.log`,
`logs/d049-initial-*.log`.

## 4. The two fixes — verified as strengthening, not weakening

`diff` of verbatim → committed candidate shows **only** these two changes:

1. `drive_tool/service_policy.py` (commit `945016b2`): `+from types import MappingProxyType`
   and `self._by_id: dict[...] = dict(by_id)` → `MappingProxyType(dict(by_id))`. This is the
   contract's "no externally mutable dictionaries" fix. Semantics unchanged.
2. `tests/test_service_policy.py` (commit `dc3c2af7`): only `test_visible_ascii_bounds_accepted`
   changed. Before it called `authenticate('!'*32)` with no `assertRaises` (always errored);
   after it configures boundary-codepoint tokens (`'!'*32`, `'~'*32`) and asserts
   `assertIs(authenticate(tok), exact AgentPolicy)`. **No assertion was removed or relaxed.**

Conclusion: the final tests fixed an invalid unknown-token assertion and **did not weaken
authentication** — confirmed independently by diff and by execution.

## 5. Independent mutation re-run (isolated copies)

Runner: `scripts/d049_mutation_rerun.py` (written by this review). Each mutation is applied to
an isolated copy; for each mutant it verifies (a) the mutant source still **compiles and
imports** (no syntax/import fake catch), (b) the policy suite fails, (c) the intended test is
among the failures, (d) the failure is a real `AssertionError` (semantic, not accidental).

**Result: 6/6 CAUGHT, semantically, on both 3.11.2 and 3.12.13.**

| # | Mutation | Caught by (3.11 = 3.12) | Type |
| - | -------- | ----------------------- | ---- |
| M1 | early auth return | `test_compares_all_digests_no_early_return` | AssertionError |
| M2 | duplicate digest acceptance | `test_duplicate_token_digest_rejected` | AssertionError |
| M3 | cross-agent alias fallback | `test_allowed_returns_exact_object`, `test_same_alias_across_agents_isolated` | AssertionError |
| M4 | read-only save bypass | `test_read_only_denies_save`, `test_save_only_denies_read`, `test_caps_do_not_grant_absent_operations`, `test_denied_message_identical_across_reasons` | AssertionError |
| M5 | malformed root acceptance | `test_root_nul_rejected`, `test_root_backslash_rejected` | AssertionError |
| M6 | cap upper-bound bypass | `test_cap_too_large_rejected` | AssertionError |

Logs: `logs/mutations/*.log`, summary `logs/d049-mutation-rerun.log`.

## 6. Fresh adversarial probes (this review's own script)

`scripts/d049_adversarial_probes.py` — 103 checks, **103/103 pass on both interpreters**
(`logs/d049-probes-python3.11.log`, `logs/d049-probes-python3.12.log`). Coverage vs the brief:

- **Real NUL / single backslash / dot / empty root components:** real `'\x00'`, one `'\\'`,
  two `'\\\\'`, `/x/./y`, `/x/../y`, `/./x`, `/../x`, `/.`, `/..`, `/x//y`, `/foo/`, `//`, `''`
  all rejected; `/` and `/srv/data` accepted; relative and non-str rejected. (Source bytes at
  `service_policy.py:55,57` are the correct Python NUL escape and a single backslash — the
  Codex "escaping" flag is **not** a violation, confirmed at byte level.)
- **Nonbool bounds / duplicate ids or digests:** caps reject `True/False` (TypeError) and
  `0/-1/MAX+1` (ValueError); accept `1`/`MAX`; reject `1.0/"1"/None`. Duplicate agent_id and
  duplicate token digest rejected. 32 agents/grants accepted, 33 rejected.
- **Immutable registry:** `_by_id` is a `mappingproxy`, item assignment raises `TypeError`;
  `_agents`/`_digests` are tuples; grants/agents frozen; `operations` a frozenset.
- **Different agents, same alias / different roots:** each agent returns its own exact grant;
  no cross-agent fallback in either direction.
- **Read-only cannot save; caps don't grant ops:** verified for both read-only and write-only
  grants.
- **Malformed/unhashable request fields deny uniformly:** 21 cases (`[]`, `{}`, `set()`,
  `bytearray`, `None`, ints, bytes) all raise `PolicyDeniedError('access denied')`.
- **Exact returned object identity:** `authenticate` → `is` AgentPolicy; `authorize` → `is`
  SourceGrant.
- **Visible-ASCII token boundaries/lengths:** cp 33 and cp 126 at len 32 accepted; len 256
  accepted; len 31/257/empty rejected; cp 32/127/tab/0x1f/non-ASCII rejected; non-str rejected.
- **All configured digest comparisons occur, no early match return:** `hmac.compare_digest`
  spy shows exactly N comparisons for a match at index 0, at index N−1, and for an unknown
  token.
- **No secrets in repr/errors; no fs/network:** token/digest/root absent from all reprs;
  denied message fixed and secret-free; `os.stat/lstat/listdir/open` and
  `socket.socket/create_connection` patched to raise are never hit during build+use.

## 7. Verdict and findings

**ACCEPT WITH NITS.**

**NIT-1 (cosmetic / type-checker only — not a runtime failure).** `service_policy.py:164`
annotates a **local** variable as `Mapping[str, AgentPolicy]`, but `Mapping` is not imported.
Verified inert: (i) `from __future__ import annotations` is present, and (ii) Python does not
evaluate **local** variable annotations regardless — a control test with an undefined name in
a local annotation runs fine even without the future import. The module imports cleanly and
`Mapping` is not bound in the module namespace. Impact: a static type checker (mypy/pyright)
would flag an undefined name; runtime is unaffected. Suggested (do not apply here): add
`from typing import Mapping` or drop the annotation. **Not a blocker.**

**OUT-OF-SCOPE-1 (process boundary, explicitly not an HTTP attack).** `PolicyTable` uses
`__slots__` with writable slots, so trusted in-process code can rebind `_agents`/`_by_id`/
`_digests`. This is not reachable from the JSON/HTTP request surface and the D045 contract
scopes this layer to authentication/authorization, not hostile-Python containment. The
mutable-dict exposure the contract named *was* fixed (MappingProxyType). No action required
for this contract; noted for the future process-isolation layer.

**Blockers: none.** No CHANGES REQUIRED.

## 8. Honesty notes and limits

- This review executed the candidate itself; it does **not** rely on D046's logs for
  acceptance. D046 logs were read only to compare claims, and every claim was independently
  reproduced (or, for the two fixes, confirmed by diff).
- Only Python 3.11.2 and 3.12.13 were run. No 3.13/3.14, no cloud/kernel-specific run is
  claimed.
- Root validation was exercised on synthetic strings only; no real paths were opened, as the
  contract requires.
- Synthetic tokens/roots only; no credentials, no filesystem/network calls from the layer.

## 9. File manifest

See `MANIFEST.sha256.txt` for byte SHA-256 of every file in this bundle.
