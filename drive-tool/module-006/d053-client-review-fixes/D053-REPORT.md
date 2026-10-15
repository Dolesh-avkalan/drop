# D053 — narrow client transport correction (response-body transport errors)

**Builder/assembler evidence only — not independent acceptance.** No broader source edits, no main
merge, no deployment, no installs, no real credentials/roots.

## 1. Provenance and pins

| Item | Value |
| ---- | ----- |
| D053 brief | `drive-tool` @ `40c320a666c37da3204c17921b52909310bf2e39` `tasks/d053-client-review-fixes.md` |
| Director contract | `drive-tool` @ `d14b1b7f599b48d4b7f3af9ddae9d6829e065769` `tasks/d047-agent-client.md` |
| D051 review | `drop` @ `ba4029f168d531be52a37155131003ab3b3e8b95` `drive-tool/module-006/d051-deepseek-client-review.md` (review verdict: CHANGES REQUIRED) |
| Base candidate | `drive-tool` @ `81a6485c300f0a9cecc9c902c90360379c17e946` (pinned intermediate snapshot; being independently tested by local D052 — left untouched) |
| New branch | `feature/module-006a-client-review-fixes` (created from `81a6485…`) |
| Head / tree | head `53450a4cb71f555addd94eb5a700c777e7f5b1e6`, tree `48ab4ef31a36ed2d36c8d6dfc5bd75bb90fd0b27` |
| Allowed paths | `drive_tool/service_client.py`, `tests/test_service_client.py` (only) |

Old candidate blob hashes (unmodified): `service_client.py` `3df94000…`, `test_service_client.py`
`fcda8541…`. The final committed branch files were re-fetched and match the locally tested tree
**byte-for-byte** (see manifest).

## 2. Reproduced old failure (before any change)

Confirmed against the pinned old candidate `81a6485` with tiny raw loopback servers
(`scripts/repro_oldfail.py`, `logs/oldfail-repro-3.11.txt`):

```
stall_body_read : LEAKED builtins.TimeoutError: timed out
truncated_body  : DriveClientError(code='unavailable', ...)   # see note
malformed_chunk : LEAKED http.client.IncompleteRead: IncompleteRead(0 bytes read)
```

The primary D051 finding is real: `_dispatch` wrapped only `conn.request()` / `conn.getresponse()`.
The response **body** is read by `_read_capped` → `resp.read(cap + 1)` **outside** that wrapper, so a
mid-body transport failure escapes as a raw stdlib exception. Note on `truncated_body`: with an explicit
`read(amt)` a short read does not itself raise — it returns short data, which the read-reply builder then
rejects (missing headers) as `unavailable`; the leaks that matter are the stall (`TimeoutError`) and the
malformed/truncated **chunked** body (`http.client.IncompleteRead` / `HTTPException`), plus
`ConnectionResetError` (covered by the seam tests).

## 3. The fix (narrow)

In `drive_tool/service_client.py`:

- Added `_TRANSPORT_ERRORS = (TimeoutError, http.client.HTTPException, OSError)`.
- In `_dispatch`, after `except _ProtocolError:` added:
  - `except DriveClientError: raise` (a parsed error envelope propagates unchanged), and
  - `except _TRANSPORT_ERRORS as exc: raise _wrap_transport(exc, write_op=write_op) from None`.

`_wrap_transport` maps `TimeoutError → "timeout"` and everything else `→ "unavailable"`, with
`write_op → outcome_uncertain=True, retry_safe=False` and read-only `→ outcome_uncertain=False,
retry_safe=True`. Cap+1 bounds, close ownership (response + connection closed in `finally`) and
no-retry behaviour are all preserved. `+18` lines, `0` deletions in the source file.

After the fix (`scripts/repro_oldfail.py` against the new tree, `logs/newpass-repro-3.11.txt`):

```
stall_body_read : DriveClientError(code='timeout', uncertain=False, retry_safe=True)
truncated_body  : DriveClientError(code='unavailable', uncertain=False, retry_safe=True)
malformed_chunk : DriveClientError(code='unavailable', uncertain=False, retry_safe=True)
```

## 4. Duplicate-header nits — DISCONFIRMED (no fix)

D051 raised two secondary nits: duplicate `Content-Length` and duplicate `Content-Type` not rejected.
The brief warned that `getheader` may combine duplicates, so static counterexamples can be wrong. Probed
against **actual http.client** (`scripts/probe_headers.py`, `logs/probe-headers-3.11.txt` /
`-3.12.txt`), identical on 3.11.2 and 3.12.13:

| Raw response | `getheader('Content-Length')` | `getheader('Content-Type')` | Client result |
| ------------ | ----------------------------- | --------------------------- | ------------- |
| dup CL `2`, `5` | `'2, 5'` | — | rejected |
| dup CL `100`, `2` | `'100, 2'` | — | rejected |
| dup Content-Type (octet, text/plain) | `'3'` | `'application/octet-stream, text/plain'` | rejected |
| single valid control | `'3'` | `'application/octet-stream'` | accepted |

`http.client` **combines** duplicate headers into a comma-joined string. `_read_capped`'s
`_DECIMAL_RE = ^[0-9]+$` then fails on `'2, 5'` → `_ProtocolError` → `unavailable`; `_build_read_reply`
compares the MIME exactly, so `'application/octet-stream, text/plain'` ≠ `application/octet-stream` →
`unavailable`. Client-level probe (`scripts/probe_client_dupes.py`,
`logs/old-dup-client-3.11.txt` / `-3.12.txt`) confirms on the **old** client:

```
dup_CL_2_then_5   : DriveClientError(code='unavailable')
dup_CL_100_then_2 : DriveClientError(code='unavailable')
dup_CT_both_octet : DriveClientError(code='unavailable')
dup_CT_mixed      : DriveClientError(code='unavailable')
single_valid_control: ACCEPTED ReadReply(data=b'abc', eof=True)
```

**Both nits are disconfirmed**: duplicates are already rejected fail-closed. No fix and no regression
added for them (the existing `test_read_duplicate_header_fails_closed` already covers the observation
headers). Observation headers (`X-Drive-*`) already use `get_all` with an exactly-one requirement.

## 5. Regressions added (11, deterministic)

`tests/test_service_client.py` — pure append (216 added lines, **0 deletions**; the pre-existing 61 tests
are byte-identical, verified). New helper `_RaisingResponse` (a fake response whose `read` raises) and
`_RawSocketServer` (one-shot raw loopback server).

- Seam tests (`TestResponseBodyTransportErrors`): read body `socket.timeout` → `timeout`/False/True with
  response+connection closed and no retry; save body `socket.timeout` → `timeout`/True/False; read body
  `IncompleteRead` → `unavailable`/False/True; read body `HTTPException` (malformed chunk) →
  `unavailable`; save body `ConnectionResetError` → `unavailable`/True/False; error-path (500) body
  `socket.timeout` → `timeout`; redaction (a body error whose text echoes the token/root is not present
  in `str`/`repr`); no-retry (`read_calls == 1`).
- Fake-server tests (`TestResponseBodyTransportErrorsFakeServer`): stalled body → `timeout`; malformed
  chunk (`ZZZ`) → `unavailable`; truncated chunk (declares 5, sends 3) → `unavailable`.

## 6. Execution results

| Run | Result |
| --- | ------ |
| NEW full suite 3.11.2 | **Ran 423 tests, OK** — exit 0 |
| NEW full suite 3.12.13 | **Ran 423 tests, OK** — exit 0 |
| NEW client module 3.11.2 | **Ran 72 tests, OK** — exit 0 |
| NEW client module 3.12.13 | **Ran 72 tests, OK** — exit 0 |
| FINAL tests vs OLD client 3.11.2 | **Ran 72 tests, FAILED (errors=11)** — exit 1 |
| FINAL tests vs OLD client 3.12.13 | **Ran 72 tests, FAILED (errors=11)** — exit 1 |

423 = 412 baseline + 11 new. Baseline (`81a6485`): full suite 412 OK (351 core + 61 client) on both
interpreters. The 11 oldfail errors are the raw leaks (verified: `TimeoutError`, `IncompleteRead`,
`HTTPException`, `ConnectionResetError` appear in the tracebacks — not import errors). Raw logs under
`logs/`.

## 7. Mutation evidence (isolated copies, both interpreters)

`scripts/mutation_runner.py`. Each mutation is applied to an isolated copy of the final NEW tree; the
client module is run on 3.11 and 3.12; the copy is discarded. **7 mutants, 7 caught, 0 survived**, all
real assertion/error failures (no syntax/import fake positives; verified no `SyntaxError`/`ImportError`
in any mutant log).

| # | Mutation | Intended caught assertion | Caught by |
| - | -------- | ------------------------- | --------- |
| M1 | unbounded reply read (`resp.read()`) | never read unbounded | `test_connection_and_response_closed_on_success/_error`, `test_new_connection_per_call_no_reuse` |
| M2 | lost connection close | connection closed every call | 7 close/transport tests |
| M3 | automatic save retry | no automatic retry on save | `test_save_body_timeout_is_uncertain_not_retry_safe` |
| M4 | raw remote error leakage | remote text never leaks | `test_error_is_redacted_even_if_server_echoes_token` |
| M5 | cross-request connection reuse | fresh connection per call | `test_open_returns_a_new_connection_each_time`, `test_concurrent_calls_are_independent` |
| M6 | wrong EOF handling (exact-fill) | exact-fill window is not EOF | `test_read_exact_fill_with_eof_is_protocol_invalid` |
| M7 | **revert the D053 fix** | body transport errors map to safe error | all 11 new regressions (errors=11) |

## 8. Scope, blockers, honesty notes

- **Scope held.** Only the two allowed paths changed; the old candidate `81a6485` is untouched; no
  policy/storage/backend edits; no `main` merge; no deployment. D047/D051/D052 artifacts preserved.
- **Two confirmed fixes:** one narrow transport-error mapping (this is the D051 blocker) plus the
  regressions. The two duplicate-header nits were **disconfirmed** by probe; no speculative fix made.
- **No new blocker.** The client remains a lexical wire validator only; containment is the server
  adapter's job. This is builder evidence from one host — independent delta review/recheck and any
  integration are the director's to arrange.
