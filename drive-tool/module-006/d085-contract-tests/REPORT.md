# D085 — adopt the capability/schema clarification; correct tests only

**Task:** D085. From exact `cc1cd326`, on a NEW branch, correct only
`tests/test_http_adapter.py` for the adopted capability boundary and the Content-Length
rule, run the full suite on 3.11/3.12, and run the gated 600-call smoke and 10,000-call
six-agent soak only if conformance passes. **Production is unchanged.**

## 1. Source identity

- base `cc1cd326a1df85ad906796e535db466b4cf664ba` (tree `e60cd406f732fff2f25a1a2d5063523d974e432e`)
- branch `feature/module-006b-http-contract-tests`, head `7dab4357ca9a79a6c857ab78bea55805dfa1de89`,
  tree `26eff85fa3b9945619157632e65d594c41653aac`
- `tests/test_http_adapter.py` blob `772239d2…` → `5419096c43190ea61270fd9091a8601d376bdd1e`
  (64700 bytes, sha256 `951e73d01b170a13789eb2306d66e695cc8ba5d3ae253a67be3d1bf4dc391469`)
- `drive_tool/http_adapter.py` **unchanged** at blob `8cd137f7323eb5c9e1e4166471a04073204840e5`
  (sha256 `1e185615…`). Scope vs base is exactly one modified path.
- fetched the published branch back, `cmp`-confirmed byte identity, and re-ran from those bytes.
- adjudication under review: `drop` `1676ffd`, `drive-tool/module-006/d083-auth-adjudication.md`.

## 2. What was adopted and what was rejected

**Adopted (director clarification over D083 §1).** The frozen backend authorizes
`(token, source_id, operation)` *before* schema, and exposes no token-only method, so a
missing / unextractable / non-string `source_id` is a uniform **403 denied** for known,
unknown and unauthorized tokens alike. An extractable **authorized** source with bad
remaining schema is **400 invalid**; an extractable but unauthorized source is 403. A
duplicate JSON key makes the source ambiguous and is 403. Delegation stays
operation-specific (`list`/`find`/`read`/`save`) — never routed all through `read`.

**Rejected (D083 §2).** The new leading-zero restriction (rejecting multi-digit
`0…` Content-Length as 400) and the conflation of the lexical Authorization framing check
with an authenticated known-token check before the body. Preserved from D061/D080: ASCII
decimal leading zeros are **accepted** within the header bounds and normalised with a
bounded conversion; the lexical auth gate runs before the oversize cap; and a huge but
syntactically valid Content-Length with valid lexical headers is **413 too_large**, not 400
invalid. A lexically valid but unknown token cannot be authenticated without a source_id
and body, so it passes the lexical gate and can still receive the 413 wire cap.

## 3. Test corrections (test-only, 10 expectations)

Nine expectations changed from `400 invalid` to the adopted `403 denied`, for a
missing/unextractable/non-string `source_id`:

- `PayloadParsingTests.test_payload_cases_rejected_400_invalid` → renamed
  `test_payload_cases_rejected_per_contract`, split into the six unextractable cases
  (`duplicate_keys`, `nan`, `infinity`, `bom`, `invalid_utf8`, `non_object` → 403) and the
  two extractable-bad-schema cases (`extra_key`, `missing_key` → 400).
- `PayloadParsingTests.test_deeply_nested_json_does_not_kill_worker` → 403, worker-alive
  follow-up kept.
- `AuthFirstZeroFsTests.test_valid_token_valid_source_bad_payload_invalid_before_lease` →
  renamed `test_unextractable_source_denied_uniformly_across_token_states`, 403, with the
  `calls == [("list", None)]` and `leases == 0` assertions preserved and paired
  unknown/unauthorized token checks added.
- `FramingRejectionTests` (case `save_duplicate_key`) → 403.

One expectation changed to `413 too_large`:

- `FramingRejectionTests` (case `huge_digit_content_length`) → 413. The framing test now
  carries a per-case contract status table instead of assuming 400 for every case.

**New paired coverage** — `CapabilityBoundaryTests`, which documents the
lexical-vs-service authentication distinction in its docstring and asserts: unextractable
source denied 403 for main/unknown/other/read-only tokens; extractable authorized source
with bad schema → 400; extractable unauthorized source → 403; duplicate JSON key → 403;
zero-padded Content-Length accepted and normalised (200 OK, not 413); and the huge
Content-Length matrix (known → 413, lexically-valid-unknown → 413, lexically-invalid → 403,
absent → 403).

No IO, redaction, lease or uncertainty assertion was weakened; the suite grew from 567 to
573 tests.

## 4. Conformance — PASSES

| Run | 3.11.2 | 3.12.13 |
| --- | --- | --- |
| full suite, local build | `Ran 573 tests … OK (skipped=3)`, exit 0 | same, exit 0 |
| full suite, fetched published bytes | `OK (skipped=3)`, exit 0 | same, exit 0 |

The three skips are exactly the documented opt-in/control ones — the adapter-present gate
contract test and the two `D067_RUN_HTTP_SMOKE_SOAK=1` opt-ins (`logs/skips_3.12.txt`).
There are **zero adapter-missing skips**. For contrast, the pre-D085 base with its original
expectations is `FAILED (failures=10, skipped=3)` (`logs/full_suite_preD085_3.12.txt`).

## 5. Gated smoke / soak — both FAIL, reported honestly

Conformance passes, so the gates were run with the fixed D064 bounds
(`max_stage_seconds = 900`, concurrency 6, 1 agent for smoke, 6 agents for soak).

| Stage | Calls | Wall | Result | Errors |
| --- | --- | --- | --- | --- |
| 600 smoke, 3.11 | 600/600 | 3.81 s | **FAIL** | `busy=32`, `unavailable=1` |
| 600 smoke, 3.12 | 600/600 | 3.72 s | **FAIL** | `busy=28` |
| 10,000 soak, 3.11 | 10000/10000 | 56.4 s | **FAIL** | `busy=300`, `denied=322`, `unavailable=7` |
| 10,000 soak, 3.12 | 10000/10000 | 59.1 s | **FAIL** | `busy=326`, `denied=320`, `unavailable=6` |

Resource counters are clean in every run: `closed=true`, fd `11 → 4` (no leak), RSS
**decreased** (e.g. soak 3.12 36972 → 32688 KiB), no temp accumulation, and a thread census
of `before=1, live=8, after_close=1` — the seven adapter threads (six workers plus the
accept thread) are created and fully reaped, matching `expected_adapter_threads = 7`.

**Minimal repro for the `busy` failures** (`scripts/probe_busy_repro.py`): the same 600-call
mixed workload at client concurrency 4 → `busy=0`, 5 → `busy=0`, **6 → `busy=32`**. The
smoke drives `concurrency = MAX_IN_FLIGHT_OPERATIONS = 6`, i.e. exactly the six worker
slots, so any transient moment where a slot is not registered in `_idle_slots` (a worker
finishing its post-response drain, or a client socket not yet released) makes the next
arrival a genuine seventh in-flight operation and the adapter correctly answers `503 busy`.
`err:denied` in the soak is also by design — one of the six soak agents is the read-only
token, which legitimately cannot `save` (~320 of 10,000 calls). `err:unavailable` is a
handful of calls at teardown.

**Attribution: pre-existing, not caused by D080 or D085.** The same probe against the
pre-D080 adapter (`f304425a`, sha256 `191ad2be…`) gives `busy=0 / 0 / 22`, and the 10,000
soak against it gives `busy=332, denied=309, unavailable=6` — the same profile. No fix is
proposed and no pass is claimed; the smoke/soak gates remain **BLOCKED** and the concurrency
/ read-only-agent mismatch is flagged for the gate owner.

## 6. Scope and gates

`tests/test_http_adapter.py` only; production byte-unchanged. No installs, no merge, no
deploy, no real roots. No acceptance claim — **Gemini D084 security review remains
mandatory**, and the smoke/soak gates stay blocked pending a decision on the gate's
concurrency and read-only-agent expectations.
