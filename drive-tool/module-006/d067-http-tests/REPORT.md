# D067 — HTTP conformance test module (report)

**Task:** D067 (supersedes the D064 monolithic assignment). **Deliverable:**
`tests/test_http_adapter.py` only — a complete conformance/security test module
plus fixed bounded smoke/soak helpers against the frozen public API.
**Assigned to:** Sarvam. **Production adapter:** DeepSeek (D068, separate).
**Base commit:** `b7f8d17b9dcc4aec68d54b38f994290e05264e67` (506 tests, client/backend accepted).
**Branch:** `feature/module-006b-http-tests`.

## 1. Result summary (honest state)

| Item | State |
| --- | --- |
| Test module written, compiles on 3.11 + 3.12 | **DONE** |
| Committed baseline preserved (506 tests) | **DONE — 506 OK on both interpreters** |
| New module imports cleanly, adds no failure when adapter absent | **DONE — 563 total, 55 skipped, exit OK** |
| Adapter integration tests (end-to-end, framing, admission, …) | **BLOCKED — production `drive_tool/http_adapter.py` (D068) absent** |
| 600-call HTTP smoke | **NOT RUN — gated on the production adapter** |
| 10,000-call six-agent HTTP soak | **NOT RUN — gated on a passing smoke** |

No adapter-dependent result is claimed. The adapter is an *expected missing
dependency* for D067 (D068 is assigned separately); every such test is reported
as SKIPPED, not passed, and the smoke/soak helpers raise `RuntimeError` rather
than fabricate a stage.

## 2. Exact source identity & scope

- New path (the only change on the branch): `tests/test_http_adapter.py`
- branch: `feature/module-006b-http-tests` (created at base `b7f8d17`); head `e47587a506ed4dd25220eef92d54fb42a1f4fe63`, tree `2c184aea001a2361a9103340d4a26f4d27bd3587`
- git blob sha1: `b571032c3e938abfb2a17f1dde44bb370469e4c4`
- sha256: `de3c67d3405a176ee4ccfcab253083fb0fd7115b7174b569b352fdc747f90272`
- lines / bytes: 1078 / 50785
- test methods: 57 across 14 test classes (table-driven where the cases are uniform)
- Scope: exactly one new file; no client/backend/policy/storage edit; no
  production adapter written; no merge, deploy, install, real root or token.

## 3. Coverage (mapped to the adopted contract)

Public API only (`DriveHTTPAdapter` constructor, `host`, `port`,
`socket_timeout`, `service`, `close`, `repr`) plus the documented `__all__`
constants. Ordering is proven through a real-service instrumented seam
(`InstrumentedService(LocalFileService)`) that alters no accepted behaviour.

- **Constants & isolation** (`ContractConstantsTests`): every exported constant
  equals the D061 value; `__all__` complete; the adapter source does not
  reference `LocalAdapter`/`LocalWriter`/`ListingService`/`PolicyTable`.
- **Constructor validation & rollback** (`ConstructorValidationTests`): exactly
  one of `policies`/`service`; `service` type; `port` and `socket_timeout`
  validation (bool / non-number / NaN / Infinity / range); properties; bind
  failure rolls back with no thread leak; a supplied service is owned and
  closed by the adapter.
- **End-to-end DriveClient conformance** (`EndToEndTests`): list / find / read /
  save; empty-file read (`b""`, EOF true); short window (EOF true); exact-fill
  window (EOF false); read past EOF; explicit length within a small grant cap;
  default read on a small grant → `too_large`; whitespace-only find → `invalid`;
  out-of-range list offset → `invalid`.
- **Framing & header enforcement** (`FramingRejectionTests`, 30 table-driven
  raw-socket cases): non-POST, non-HTTP/1.1, request line > 8192, header block >
  16384, > 64 headers, bare `\n`, obs-fold, whitespace before `:`, missing /
  duplicate `Host`, `Connection: keep-alive`, duplicate `Connection`,
  `Transfer-Encoding`, `Expect`, missing / duplicate / non-digit
  `Content-Length`, 5000-digit `Content-Length` (bounded before `int()`),
  missing / duplicate / parameterized `Content-Type`, query on list / read,
  `/v1/save` missing / empty / extra / duplicate query keys, buffered trailing
  bytes → 400 `invalid`; two concatenated requests → one response and the
  second never executes.
- **Auth-first ordering & zero-FS-IO** (`AuthFirstZeroFsTests`): missing,
  duplicate, non-Bearer and lexically invalid `Authorization` → 403 `denied`
  before the body; unknown token with malformed / duplicate-key JSON → 403
  `denied` (never 400) with **zero binding leases**; valid token + unauthorized
  source + malformed body → 403 `denied`; valid token + invalid payload → 400
  `invalid` delegated with `file_id=None` and zero leases; no filesystem
  mutation.
- **Alias isolation** (`AliasIsolationTests`): two agents sharing one alias
  string mapped to distinct roots stay isolated; cross-agent alias use denied.
- **Response caps & type validation** (`ResponseCapTests`): oversized JSON
  result → 413 `too_large` (uncertain false); wrong `read` result type → 503
  `unavailable` (uncertain false, retry safe); pre-body JSON / save
  `Content-Length` over cap → 413 before the body; save over grant write cap →
  413 with zero leases.
- **Save uncertainty & disconnect** (`SaveUncertaintyTests`): disconnect before
  full body → no file; committed save persists (no rollback / retry);
  fault-injected post-publish failure → `unavailable`, uncertain **true**,
  retry_safe **false**.
- **Read semantics** (`ReadSemanticsTests`): empty body with EOF header
  accepted; wire `length == 0` → 400 `invalid`.
- **Payload parsing** (`PayloadParsingTests`, 8 cases): duplicate keys,
  NaN/Infinity, UTF-8 BOM, invalid UTF-8, extra / missing keys, non-object JSON
  → 400 `invalid`; deeply nested JSON (5000 levels) caught safely and the worker
  still serves the next request.
- **Admission & absolute deadlines** (`AdmissionAndDeadlineTests`): six blocked
  workers → 7th call `busy` (uncertain false, retry safe) even under a
  concurrent raw-socket trickle; all six then succeed; thread count constant at
  +7; slow-header and slow-body 1-byte trickle terminated near the 0.5 s
  absolute deadline.
- **Shutdown, drain & redaction** (`ShutdownDrainRedactionTests`): invalid
  `close` timeouts rejected; blocked op → `close(0.1)` returns `False` within
  the deadline then `True`; new requests rejected after close; `repr` and error
  envelopes leak no token / root / path / exception text.
- **Smoke/soak gate** (`SmokeSoakGateContractTests`, `SmokeSoakGateTests`): the
  helpers carry the fixed D064 thresholds and raise when the adapter is absent;
  the opt-in stages run 600 then 10,000 calls (soak gated on smoke).

## 4. Fixed resource acceptance thresholds (pre-committed, D064)

Defined in `THRESHOLDS` before any run; the helpers enforce them and never move
them to fit a result.

| Threshold | Value |
| --- | --- |
| max workspace / fixtures | ≤ 128 MiB |
| max concurrent operations | ≤ 6 |
| expected adapter threads | constant 7 (1 accept + 6 workers) |
| FD after close | baseline + ≤ 2 (transient allowance) |
| RSS growth after warmup | ≤ 64 MiB |
| total stage timeout | ≤ 15 min |
| temp accumulation / cross-root bleed / unrecognized errors | none |

Smoke = 600 mixed calls (1 agent). Soak = 10,000 calls across 6 agents with
distinct aliases/roots. Both gated: `run_smoke`/`run_soak` raise `RuntimeError`
when the production adapter is absent.

## 5. Raw execution evidence (this sandbox)

Logs under `logs/`. Environment: Debian 12 (bookworm), 2 vCPU, ~2 GiB, CPython
3.11.2 and 3.12.13.

| Log | Command | Result |
| --- | --- | --- |
| `baseline_506_3.11.txt` / `_3.12.txt` | `python3.X -m unittest <17 committed modules>` | **Ran 506, OK** |
| `suite_full_3.11.txt` / `_3.12.txt` | `python3.X -m unittest discover -s tests` | **Ran 563, OK (skipped=55)** |
| `new_module_only_3.11.txt` / `_3.12.txt` | `python3.X -m unittest tests.test_http_adapter` | **Ran 57, OK (skipped=55)** |
| `gate_verbose.txt` | `... SmokeSoakGateContractTests -v` | **Ran 2, OK** |
| `compile.txt` | `python3.X -m py_compile tests/test_http_adapter.py` | **OK** |
| `source_identity.txt`, `environment.txt` | hashes / host | — |

The 55 skips are exactly the adapter-dependent tests. The 2 executed tests are
the gate-contract tests that must pass without the adapter (they assert the
helpers fail closed and the thresholds are fixed).

## 6. Honest pending gates (cannot be closed in D067)

1. **Adapter integration execution** — BLOCKED until the D068 production
   `drive_tool/http_adapter.py` is supplied. On assembly run
   `python3.X -m unittest tests.test_http_adapter` and expect 57 executed.
2. **600-call HTTP smoke** — NOT RUN (gated on the adapter).
3. **10,000-call six-agent HTTP soak** — NOT RUN (gated on a passing smoke).
4. **Independent security review / fresh execution** — arranged by the director
   (Gemini), not performed here.

Nothing here asserts that the adapter conforms; it asserts only that the test
module is complete, compiles, preserves the 506 baseline, and is gated so no
false success is possible without the production file.
