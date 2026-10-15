# D052 — independent client verification + integrated library candidate

Author: independent Sarvam context (fresh, NOT the D047 builder chat)
Date: 2026-10-15 (UTC)
Brief: `tasks/d052-client-independent.md` at `d65d30ae4888a0fa5822e1a985ee32e040d3939a`
Contract: `tasks/d047-agent-client.md` at `d14b1b7f599b48d4b7f3af9ddae9d6829e065769` (byte-identical on `main`)

All results below were executed in this session on the sandbox. No builder claim was reused as
independent evidence; every suite/mutation/probe was re-run from the actual GitHub artifacts.

---

## 1. Pins retrieved

| Item | Value | Status |
|------|-------|--------|
| Client candidate | `81a6485c300f0a9cecc9c902c90360379c17e946` on `feature/module-006a-client` | retrieved |
| Candidate base | `cedaa1342942a33f27a473e4c4ebbff6309c8932` | retrieved |
| Client base commit count | 2 commits (`cdaa6cf`, `81a6485`) | verified |
| Production blob (`drive_tool/service_client.py`) | `3b6d798b4df7558c1ecf7950057ce50b64a2a7dd` | matches candidate + D051 review snapshot |
| Test blob (`tests/test_service_client.py`) | `34c98433d9544a2ec076bf30c7ab3099e6f52724` | matches candidate |
| Builder evidence drop | `drive-tool/module-006/d047-client-implementation/` in repo `Dolesh-avkalan/drop` | retrieved from `drop` main (see blocker B1) |
| Integration base | `e55c9f741a528ce9298b5041012373195e878eaf` (PR#6 policy merged) | retrieved |
| Integration branch | `feature/module-006a-client-integration` | created |

## 2. Candidate scope / bytes

`git compare` `cedaa13...81a6485`: `status=ahead`, `total_commits=2`, exactly **2 files added, 0 modified, 0 deleted**:

- `drive_tool/service_client.py` +594/-0, blob `3b6d798b4df7558c1ecf7950057ce50b64a2a7dd`
- `tests/test_service_client.py` +912/-0, blob `34c98433d9544a2ec076bf30c7ab3099e6f52724`

Local tree diff (`base_cedaa13` vs `candidate_81a6485`) shows only the same two added paths. Scope is
exactly the two allowed paths — confirmed.

`drive_tool/service_client.py` SHA-256 `3df94000e249c9c564bd11a9142417a10494b426a24980e54849dd8730310785`
`tests/test_service_client.py` SHA-256 `fcda8541a51d83210cb479c0d0214e3c766895494ea4c1210fcd828ef28be2b1`
Both match the builder's `source_sha256.txt`. The D051 review snapshot embeds the module text byte-for-byte
equal to the committed file (only the trailing newline differs in the extracted block).

## 3. Suite reproduction (independent)

Command used: `python -m unittest discover -s tests -p "test_*.py"` (the brief's own tree requires the
pattern; `discover -s tests` without it is not importable). Raw logs in `candidate/`, `integration/`.

| Run | 3.11 | 3.12 |
|-----|------|------|
| Candidate base (351) | 351 OK, 0 skips | 351 OK, 0 skips |
| Candidate full | **412 OK, 0 skips** | **412 OK, 0 skips** |
| Candidate new file only | 61 OK | 61 OK |
| Integration base `e55c9f7` | 413 OK, 0 skips | 413 OK, 0 skips |
| Integration full (published) | **474 OK, 0 skips** | **474 OK, 0 skips** |

412 = 351 + 61 reproduced exactly. Integration 474 = 413 + 61 (measured, not inferred). Zero skips
everywhere; exit 0 everywhere.

## 4. Builder mutations — inspected and independently re-executed

Builder `run_mutations.py` inspected: it applies 6 mutations to a private tree copy and runs
`tests.test_service_client`, expecting failure. I re-applied the same 6 mutations to my own isolated
copies of the candidate **and** the integration tree, compile-checked each mutant
(`py_compile`) to prove the failure is semantic and not a syntax/import error, then ran the client suite.

| Mutation | compiles | 3.11 | 3.12 | same as builder |
|----------|----------|------|------|-----------------|
| M1 unbounded reply read | yes | CAUGHT (3) | CAUGHT (3) | yes |
| M2 lost connection close | yes | CAUGHT (5) | CAUGHT (5) | yes |
| M3 automatic save retry | yes | CAUGHT (4) | CAUGHT (4) | yes |
| M4 raw remote error leakage | yes | CAUGHT (5) | CAUGHT (5) | yes |
| M5 cross-request connection reuse | yes | CAUGHT (2) | CAUGHT (2) | yes |
| M6 wrong EOF handling | yes | CAUGHT (1) | CAUGHT (1) | yes |

All 6 caught, all compile (semantic), identical failure counts on both interpreters and both trees.
Logs in `candidate/mutations_*.log`, `integration/mutations_*.log`.

## 5. Independent adversarial probes (my own)

`scripts/probes.py` — 44 probes against real tiny loopback HTTP services plus controlled transport
seams. 43 pass; 1 fails (finding F1). Covered: exact POST path/method/headers/`Content-Length`/auth/
`Connection: close`; JSON body keys; `list` omitting `name_contains` when `None` and including it when
set; `save` urlencoded query with raw octet-stream body and no credentials in query; declared vs
missing vs chunked `Content-Length`; cap+1 excess detection (JSON and read); error-body cap; read
duplicate/malformed/invalid-EOF/wrong-MIME/missing/offset-mismatch/short-without-EOF/exact-fill-with-EOF
fail-closed; short-with-EOF and stale-observed-size-under-growth allowed; malformed JSON and `ok!=true`
-> `unavailable`; all 8 known codes; unknown code -> `unavailable`; save unknown reply and save transport
failure -> `outcome_uncertain=True, retry_safe=False`; read transport failure -> `False/True`; no automatic
retry (exactly one request) for save and read; redaction of token/root/remote message; invalid args and
invalid constructor open **zero** sockets; connection+response closed on success/transport-error/protocol-error;
new connection per call; cap+1 read argument via seam; redirect not followed; 12 concurrent independent
requests. Logs in `candidate/probes_*.log`, `integration/probes_*.log`.

## 6. Findings

### F1 — CHANGES REQUIRED: mid-body transport failure leaks a raw exception (read, list/find, save)

In `DriveClient._dispatch`, only `conn.request` / `conn.getresponse` are wrapped by `_wrap_transport`.
The bounded body reads `raw = _read_capped(resp, cap)` and `raw = _read_capped(resp, _MAX_JSON_BODY)`
sit outside that guard, and the enclosing handler catches only `_ProtocolError`. If the body read
raises a transport error (e.g. `http.client.IncompleteRead` on a truncated chunked stream, or a short
read against a declared `Content-Length`), the raw exception escapes to the caller instead of a
`DriveClientError`.

Repro (`scripts/finding_repro.py`), a server declaring a 100-byte chunk and delivering 3 bytes then
closing — identical result on 3.11 and 3.12:

```
read  truncated body: RAW http.client.IncompleteRead: IncompleteRead(0 bytes read)  [LEAKED]
list  truncated body: RAW http.client.IncompleteRead: IncompleteRead(0 bytes read)  [LEAKED]
save  truncated body: RAW http.client.IncompleteRead: IncompleteRead(0 bytes read)  [LEAKED]
```

Consequences against the contract:
- Caller never receives a `DriveClientError`, so there is no `code`, `outcome_uncertain` or `retry_safe`.
- For `save` this omits the mandated conservative `outcome_uncertain=True, retry_safe=False` — a caller
  cannot tell a failed write is uncertain and unsafe to retry.
- Server-derived exception text is exposed (contract: "Do not expose server exception text").

Connection and response **are** still closed (the `finally` block runs); only the error mapping is
missing. Not covered by the builder suite, which is why the suite is green. Suggested fix: wrap the body
reads (or broaden the inner handler to catch transport exceptions and map them with `_wrap_transport`).

### F2 — needs director adjudication: `p/` prefix for non-root `file_id` is not enforced

The d052 brief states the requirement: "every nonroot file_id MUST start p/ and be canonical relative
POSIX after prefix; root allowed only list/find ... do not relax." `_validate_file_id` enforces
non-empty, no leading `/`, no backslash, no NUL, and no empty/`.`/`..` segment, but it does **not**
require the `p/` prefix. Repro (`scripts/file_id_check.py`): `a.txt`, `docs/x`, `p` are accepted for
`read` and `save` (they reach the network), and `a.txt` is accepted for `list`. The builder tests
encode the relaxed reading (e.g. they send `file_id="dir"`, `file_id="f"`, and `file_id="a b/c+d"`).

This is a spec-vs-implementation divergence: the d047 contract text ("canonical p/relative POSIX") is
ambiguous, and the builder recorded decision #2 reading it as a plain relative POSIX path. The d052
director interpretation says the prefix is mandatory. The client does not implement the mandatory
prefix. If the prefix is a client-side validation rule, this is a change; if it is a server-side
canonicalization concern, F2 is a documentation nit. Director to adjudicate.

### Interpretation checks that pass

- `list` omits `name_contains` when `None` — compliant (brief says acceptable).
- `root` allowed only for `list`/`find`, rejected for `read`/`save` — compliant.
- Production blob `3b6d798` matches candidate and the D051 review snapshot — compliant.
- No automatic retries (save or read) — verified by request counting.
- Error/`repr` redaction even when the server echoes the token/root — compliant.
- Fresh connection per call, no cross-request reuse — verified (probe + mutation M5).
- Socket timeout documented as inactivity budget, not a hard deadline — documented in the module.

## 7. Integration candidate (assembly + independent validation only)

- Branch: `feature/module-006a-client-integration`
- Head: `05f4678c094d5b8d7410be45dc90040a97baec22`
- Tree: `3d2c4c1f0dc744cac9ea2a4fde6f7183a3677e16`
- Base/parent: `e55c9f741a528ce9298b5041012373195e878eaf` (exact, single parent)
- Diff `e55c9f7...05f4678c`: exactly 2 files added, both client blobs byte-identical to `81a6485`
  (`3b6d798…`, `34c9843…`). All existing accepted storage/range/policy files are byte-identical to base
  (local `diff -rq` shows only the two added paths).

The published branch was re-downloaded and re-tested: **474 OK, 0 skips on both 3.11 and 3.12**, and is
byte-identical to my local integration tree. The client probes and mutations behave identically on the
combined library (same 43/44 probes, all 6 mutations caught).

This is candidate assembly and validation. It is **not** merge authorization and no main merge or
deployment was performed.

## 8. Builder evidence

Retrieved from `Dolesh-avkalan/drop`, path `drive-tool/module-006/d047-client-implementation/`
(`report.md`, `run_mutations.py`, `source_sha256.txt`, `SHA256SUMS.txt`, `mutations_summary.txt`,
`env.txt`, suite/baseline/new-file logs, 6 mutation logs). The bundle's own `SHA256SUMS.txt` verifies
against the retrieved files, and `source_sha256.txt` matches the committed blobs. Builder evidence was
preserved (copies in `builder_*` files); it was **not** used as independent evidence.

## 9. Blockers

- **B1**: The pinned builder drop commit `c2c90a3` could not be resolved as a commit in either
  `Dolesh-avkalan/drive-tool` or `Dolesh-avkalan/drop` (404; no matching commit found; no tag). The
  drop **files** are present on `drop` main and were retrieved and hash-verified, so the builder evidence
  is available; only the exact commit pin is unresolvable. No `module-006/` path exists anywhere in the
  `drive-tool` repo (drops live in the separate `drop` repo).
- No other blockers. F1 is a code finding, not an environment blocker; per the brief I did **not** fix
  source or tests.

## 10. Verdict

**CHANGES REQUIRED.**

The candidate meets scope, byte-identity, redaction, retry, connection-ownership, and bounded-read
requirements, and the full 412/474 suites and all 6 mutations reproduce exactly. Two deviations from the
stated contract/interpretation remain: **F1** (raw transport exception leaks from the bounded body read,
and `save` loses its conservative uncertainty flags) is the substantive one; **F2** (mandatory `p/`
prefix for non-root `file_id` not enforced) needs director adjudication of the contract wording.

Honesty notes: all tests use simulated loopback HTTP services and transport seams — this is **not** real
Drive-service integration. No real roots, tokens or network endpoints were used; all malicious data is
synthetic. Only execution actually performed here is claimed; no 3.14/cloud run is claimed.
