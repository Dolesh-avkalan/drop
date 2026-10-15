# D055 — canonical client IDs + transport correction verification

Author: independent Sarvam context, continuing D052 (NOT the D047/D053 builder chats)
Date: 2026-10-15 (UTC)
Brief: `tasks/d055-canonical-client.md` at `2deba083d23d502fe77b64fe825ad87373926fda`
Predecessor: D052 report (drop `drive-tool/module-006/d052-independent-client/`)

All results were executed in this session on the sandbox. Nothing from a builder chat was reused as
independent evidence. Two roles are kept strictly separate below:

- **Part A — independent D052 reviewer:** verify D053's transport fix on its unmodified pin.
- **Part B — builder:** correct the confirmed F2 (`p/` prefix) deviation. This is *builder evidence*
  and needs another reviewer; it is not self-accepted.

---

## 1. Pins

| Item | Value |
|------|-------|
| D053 candidate (verified) | `53450a4cb71f555addd94eb5a700c777e7f5b1e6`, tree `48ab4ef31a36ed2d36c8d6dfc5bd75bb90fd0b27`, single parent `81a6485c…` |
| D053 scope vs `81a6485` | exactly 2 files modified: `drive_tool/service_client.py` (+18), `tests/test_service_client.py` (+216) — no other paths |
| D055 candidate (new) | branch `feature/module-006a-client-canonical-ids`, head `bcf5d457fd951a63a61ebd5c939001790526819a`, tree `1f969300ac8257864c739e3ff1a5bdfae545e1d1`, single parent `53450a4c…` |
| D055 scope vs `53450a4` | exactly 2 files modified: `drive_tool/service_client.py`, `tests/test_service_client.py` |
| Source blobs (D055) | `service_client.py` `d04c637de7b7ed2b9be78d5b18fde60519f71579`; `test_service_client.py` `41d94d6ba0a184943ff6c80e1acc3d920ce18034` |
| Source sha256 (D055) | `service_client.py` `03c009ca…68a791`; `test_service_client.py` `e10d6145…8ae4f4` |

---

## Part A — independent verification of D053 (pin `53450a4`)

D053's transport delta (diff in `d053_pin/transport_delta_service_client.diff`) adds
`_TRANSPORT_ERRORS = (TimeoutError, http.client.HTTPException, OSError)` and two `except` clauses in
`_dispatch` (after `_ProtocolError`): `except DriveClientError: raise`, and
`except _TRANSPORT_ERRORS as exc: raise _wrap_transport(exc, write_op=write_op) from None`. This maps a
failure while reading the response **body** to a safe `DriveClientError`.

Independently re-run on the unmodified pin (my own D052 scripts, not the builder's):

| Check | 3.11 | 3.12 |
|-------|------|------|
| D052 adversarial probes (`probes.py`) | 44/44 pass | 44/44 pass |
| D052 hostile-body reproducer (`finding_repro.py`) | read/list → `unavailable False/True`; save → `unavailable True/False` | same |
| D053 transport verification (`d053_transport_verify.py`) | 7/7 pass | 7/7 pass |
| Original 6 D052 mutations (`mutate.py` M1–M6) | all CAUGHT, compile-clean | all CAUGHT, compile-clean |
| Full suite | 423 OK, 0 skips | 423 OK, 0 skips |

Transport-mapping checks (my `d053_transport_verify.py`), actual pass/fail, both interpreters:

- read truncated chunked body → `unavailable`, `outcome_uncertain=False`, `retry_safe=True` — PASS
- save truncated chunked body → `unavailable`, `True`, `False` — PASS
- read mid-body stall (server sleeps past the 0.5s inactivity budget) → code `timeout`, `False/True` — PASS (returned at ~0.50s)
- save mid-body stall → code `timeout`, `True/False` — PASS
- connection + response still closed on a mid-body failure — PASS
- mid-body error redacted (no token / no `IncompleteRead` text) — PASS
- no automatic retry on a body transport error (server hit once) — PASS

**D053 verdict (independent): ACCEPT.** The fix is correct, bounded to the two allowed paths, and does
not regress the original 6 mutation guards. D053's own evidence was retrieved from
`drop/drive-tool/module-006/d053-client-review-fixes/` (report, mutation summary M1–M7, logs) and is
preserved; my results above are independent.

D052 F1 is therefore resolved on `53450a4`. Note F2 was **not** addressed by D053 — the pin still
accepts `a.txt`, `docs/x`, `p` (see `d053_pin/file_id_check_before_fix_3.12.log`).

---

## Part B — F2 correction: mandatory `p/` canonical prefix (builder work)

### Pre-fix reproduction (on `53450a4`)

`file_id_check.py` on the unmodified pin shows the deviation the director confirmed:
`read`/`save` accept `a.txt`, `docs/x`, `p`; `list` accepts `a.txt`. (Log:
`d053_pin/file_id_check_before_fix_3.12.log`.)

### Change

`_validate_file_id` now, for every non-root id, requires the `p/` prefix and a non-empty canonical
relative POSIX suffix. Rejected before any socket: `a.txt`, `docs/x`, `p`, `p/`, `p//x`, `p/../x`,
`p/./x`, absolute (`/abs`), backslash (`p/a\b`), NUL (`p/a\x00b`). `root` stays list/find-only. Accepted:
`p/a.txt`, `p/docs/x`, `p/a b.txt`, `p/a+b.txt`, `p/sub/dir/f.txt`. The id is sent on the wire
**unchanged** — the prefix is never stripped.

### Tests

Relaxed fixture ids were updated to canonical ids without weakening any assertion
(`"f"`→`"p/f"`, `"dir"`→`"p/dir"`, `"a b/c+d"`→`"p/a b/c+d"`, and the expected wire bodies/query
`file_id=p%2Ff`). A new class `TestCanonicalFileIdPrefix` adds narrow regressions: prefix-less ids
rejected before any socket (via the exploding-open seam), `root` still rejected for read/save, canonical
ids accepted and sent verbatim, and `root` accepted for list/find.

### Results

| Check | 3.11 | 3.12 |
|-------|------|------|
| Full suite (published artifact) | **428 OK, 0 skips, exit 0** | **428 OK, 0 skips, exit 0** |
| Client file only | 77 OK | 77 OK |
| D052 probes | 44/44 | 44/44 |
| D053 transport verify | 7/7 | 7/7 |
| Mutations M1–M6 (regressions) | all CAUGHT | all CAUGHT |
| M7 revert body transport fix | CAUGHT (11) | CAUGHT (11) |
| **M8 remove prefix enforcement** | **CAUGHT (2)** | **CAUGHT (2)** |

428 = 423 (D053) + 5 new prefix tests. All 8 mutants compile (semantic, not syntax errors).

Targeted oldfail/newpass: the new `test_service_client.py` run against the **old** client (`53450a4`)
fails (`oldfail_newtests_vs_oldclient_3.12.log`, errors in the prefix regressions, because the old client
accepts the ids), and against the new client passes (`newpass_newtests_vs_newclient_3.12.log`).

The published branch was re-downloaded and re-tested (428 OK both interpreters) and is byte-identical to
the local candidate.

**This Part B change is builder evidence and requires another reviewer.** I did not self-accept it. No
merge, no deployment, no real roots, no storage/policy/backend edits.

---

## 2. Publication

Evidence published under `drop` repo, path `drive-tool/module-006/d055-canonical-client/` (report, D053
pin logs, canonical logs, oldfail/newpass, mutation summaries, probes, transport checks, scope, pins,
scripts, env, SHA-256 manifest). D052 and D053 evidence were left untouched. The old
`feature/module-006a-client-integration` branch was not altered.

## 3. Blockers

None. `53450a4` was retrievable and verified; the moving D053 branch was not used or modified.

## 4. Honesty notes

- All tests use simulated loopback HTTP services and transport seams — not real Drive-service integration.
- No real roots/tokens/endpoints; all malicious data synthetic.
- Only execution actually performed here is claimed; no 3.14/cloud run.
- Part A is an independent review; Part B is builder work pending independent review.
