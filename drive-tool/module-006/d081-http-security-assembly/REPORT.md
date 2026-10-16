# D081 — HTTP security patch assembly and execution (report)

**Task:** D081. Apply the DeepSeek D080 patch to a NEW branch off exact `f304425a`,
translate the D080 example regressions from pytest into the existing unittest harness
(no installs), run actual oldfail/newpass and the full suite on 3.11/3.12, include the
independent D079 probes with confirmed/disconfirmed distinctions, and publish the
candidate plus raw evidence. No auth/schema changes, no source redesign, no merge.

## 1. Source identity

- base `f304425ab774158090edd69f1b605bcc3b03096d` (tree `87569b2b8a82c821497d9e784c568d5f75f3e5d7`)
- branch `feature/module-006b-http-security-fixes`, head `cc1cd326a1df85ad906796e535db466b4cf664ba`,
  tree `e60cd406f732fff2f25a1a2d5063523d974e432e`
- `drive_tool/http_adapter.py` blob `02576d59…` → `8cd137f7323eb5c9e1e4166471a04073204840e5`
  (39813 bytes, sha256 `1e18561512614e13250582d042593ab72c8f7bfcb104af13a2646865e94a9ac7`)
- `tests/test_http_adapter.py` blob `80798e32…` → `772239d2d9e593e13d6d19641529a3239836257e`
  (57468 bytes, sha256 `81bebfe2e7e4f1185942ad1eb6e03b4be91007e65605e58ab304acb31d553b47`)
- **strict two-file scope**: `M drive_tool/http_adapter.py`, `M tests/test_http_adapter.py`, nothing else.
- patch source: `drop` `406e5fb6`, `drive-tool/module-006/d080-http-security-fixes.md`.
- fetched the published branch back, `cmp`-confirmed byte identity with the local build, and
  re-ran everything from those fetched bytes.

## 2. Patch assembly

The D080 source diff is **malformed as a unified diff**: every hunk header is a bare `@@`
with no line numbers, so it cannot be fed to `git apply`/`patch`. Per the D081 instruction it
was reconstructed from the unambiguous anchor text, one hunk at a time, with an assertion
that each anchor matched exactly once (`scripts/apply_patch.py`). Eight sub-hunks:

1. `__init__`: add `_listener_closed` and `_close_lock`.
2. `__init__`: pre-populate `_idle_slots` from `_slots` under `_pool_cond`.
3. `__init__`: start the six workers **before** the accept thread.
4. `close()`: wrap the whole body in `_close_lock`; close/clear any pending `slot.conn`;
   wake and close the listener **once only** (`should_close_listener`).
5. `_read_request` Phase A: call the new `_check_partial_header_block(buf)` each iteration.
6. new `_check_partial_header_block`: incremental bare-LF/CR rejection, request-line byte
   and length bounds, header-block bound, and header-count bound before `CRLFCRLF`.
7. `_check_headers`: normalise leading zeros (`cl_raw.lstrip(b"0") or b"0"`); an oversized
   value becomes `MAX_SAVE_BODY_BYTES + 1` so the 413 comes from Step 8, after Step 6
   (Content-Type) and Step 7 (Authorization).
8. `_read_body`: remove the unreachable post-recv excess check (no behavioural change, no
   speculative over-read).

No production redesign and **no auth/schema change**; the invalid-payload delegation path is
untouched. The two changes are committed separately: the production patch first, then the
harness translation.

## 3. Harness translation

The D080 regressions were pytest tests against an imagined `adapter` fixture. They are
translated into `D080SecurityFixRegressionTests` in the existing module — same assertions,
no pytest, no installs. Two sites use a deterministic seam because the example form is not
deterministic or not reproducible here; both are documented in-line:

- **startup**: the example used a 6-way concurrent burst. That burst is kept, and the
  deterministic seam (`len(_idle_slots) == MAX_IN_FLIGHT_OPERATIONS` synchronously after
  construction) is asserted first. Honest caveat: this test **passes on the unpatched code
  too** (see §5), so it is a regression guard, not a discriminator, and the static startup
  window is *not* claimed to be dynamically proven.
- **repeat close**: the example re-bound the released port and asserted `accept()` timed out.
  That rebind is not reproducible here — the in-flight connection still holds the port — so
  the same property is asserted directly by counting `_wake_listener` calls.

## 4. Targeted oldfail / newpass (`logs/d080_oldfail_*`, `logs/d080_newpass_*`)

The translated tests run against the unpatched adapter (oldfail) and the patched one (newpass):

| Run | 3.11.2 | 3.12.13 |
| --- | --- | --- |
| new tests vs unpatched adapter | FAILED (failures=5), exit 1 | FAILED (failures=5), exit 1 |
| new tests vs patched adapter | Ran 4 tests, OK, exit 0 | Ran 4 tests, OK, exit 0 |

oldfail detail (both interpreters): `test_partial_header_bounds_reject_early` fails on all
three sub-cases, `test_content_length_priority_and_leading_zeros` fails, and
`test_repeat_close_does_not_wake_released_port` fails with `AssertionError: 2 != 1` (the
unpatched `close()` wakes the listener a second time).
`test_startup_six_worker_readiness` passes on both — see §5.

## 5. Full suite (`logs/full_*`)

| Suite | Tests | Result | Exit |
| --- | --- | --- | --- |
| base `f304425a` | 563 | FAILED (failures=10, skipped=3) | 1 |
| patched branch | 567 | FAILED (failures=10, skipped=3) | 1 |

Identical on 3.11.2 and 3.12.13, and identical when re-run from the fetched published bytes.
The patch adds 4 passing tests and introduces **no new failure**; the 10 failures are the
pre-existing known ones and are unchanged in both directions:

- 9 auth/schema delegation divergences (403 denied vs the tests' expected 400 invalid):
  `test_valid_token_valid_source_bad_payload_invalid_before_lease`,
  `test_deeply_nested_json_does_not_kill_worker`, `test_payload_cases_rejected_400_invalid`
  (duplicate_keys, nan, infinity, bom, invalid_utf8, non_object) and
  `test_all_framing_cases_rejected_400_invalid (save_duplicate_key)`. **Not touched** —
  pending Gemini D075/D083 adjudication.
- 1 framing/size divergence: `test_all_framing_cases_rejected_400_invalid
  (huge_digit_content_length)` — the test expects `400 invalid`, the adapter returns
  `413 too_large`. Unchanged by the patch, because the D080 correction deliberately moves the
  size gate to Step 8 so that a huge Content-Length with valid Content-Type and lexical
  Authorization is a legitimate 413. This is a **test-vs-contract divergence, not a new
  production failure**; it is flagged for Gemini/DeepSeek rather than edited here.

The 3 skips are the smoke/soak gate tests (opt-in). Smoke/soak stay blocked: conformance does
not pass.

**Startup, honestly.** The startup test passes on the unpatched adapter as well. A direct
measurement (`scripts/probe_idle_slots.py`, 200 constructions) shows the unpatched
`len(_idle_slots)` is already 6 in **200/200** trials immediately after `__init__`, and the
6-way burst produced zero `503` on both builds. The startup race is therefore reported as a
**static window that the patch removes by construction, not dynamically proven here**.

## 6. Independent D079 probes re-run against the patched tree

My own D079 probes (`drop` `4e7da180`) were re-run unchanged against the patched branch
(`logs/d079_*_on_patched_*`):

| D079 finding | Unpatched (D079) | Patched (D081) |
| --- | --- | --- |
| Defect 1 framing / bare-LF | 504 after ~1.0 s, or 0 bytes on half-close | **400 invalid in 1–7 ms** — FIXED |
| Defect 2 huge CL priority | 413 for missing-auth and bad-Content-Type; 413 for leading zeros | **403 / 400 / not-413** — FIXED |
| Defect 2 control (11-digit, valid) | 413 | 413 (legitimate) — unchanged |
| Defect 3 already-buffered > CL | 400 invalid, 0 service calls | 400 invalid, 0 service calls — unchanged |
| Defect 3 pipelined req2 | 200 OK, 1 service call | 200 OK, 1 service call — unchanged |
| Defect 4.1 startup burst | 0 busy over 240 requests | 0 busy over 240 requests — unchanged |
| Defect 4.2 repeat close | `wake_calls=2`, second target `fd=-1` (listener closed) | **`wake_calls=1`** — FIXED |
| Defect 4.3 idle conn already being served | client gets a bounded 504 after the socket timeout | same — **unchanged** |

Confirmed vs disconfirmed, carried over from D079: defects 1, 2, 4.2 and 4.3 were confirmed;
defect 3 was **disconfirmed as a defect** (the contract's already-buffered rejection is
reachable and fires, and the pipelined second request is never executed — `service_calls == 1`),
which is why the patch removes only the unreachable line and adds no speculative peek/read.

On 4.3: the patch adds the pending-handoff closure in `close()` (mirroring `_rollback_startup`),
but a connection a worker has **already taken and is mid-request** is still served to
completion, bounded by the socket timeout. The D079 probe exercises that already-serving case,
so its observable result is unchanged. The pending-handoff closure is verified at code level
and by the once-only wake/close behaviour; it is not separately reproduced with a dynamic
handoff-gap counterexample here.

## 7. Scope and gates

Two files only; no merge, no deploy, no real roots, no installs. No fix beyond the patch and
the harness translation. **Gemini delta review is mandatory** before any further step; the
auth/schema divergence is Gemini D075/D083's to decide and the size-gate test expectation is
flagged for DeepSeek. Smoke/soak remain blocked until full conformance passes.
