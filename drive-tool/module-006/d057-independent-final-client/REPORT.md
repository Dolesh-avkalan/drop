# D057 — independent corrected client acceptance + final integration candidate

Author: independent Sarvam context (fresh; not the D047/D053 builders nor the D052/D055 reviewer).
Date: 2026-10-15 (UTC). Brief: `tasks/d057-independent-final-client.md` at `188f74f2`.

All results below were produced by me in this session on the sandbox. Every test uses a
**simulated loopback HTTP service** (`http.server` on 127.0.0.1) plus controlled transport seams.
These are **not** real Drive-service integration tests and no real service, root, token or
filesystem was touched.

---

## 1. Pins verified (no head substitution)

| Item | Expected | Measured | Verdict |
|------|----------|----------|---------|
| Candidate commit on `feature/module-006a-client-canonical-ids` | `bcf5d457fd951a63a61ebd5c939001790526819a` | branch head = `bcf5d457…` | MATCH |
| Candidate tree | `1f969300ac8257864c739e3ff1a5bdfae545e1d1` | `1f969300…` | MATCH |
| Candidate parent | `53450a4cb71f555addd94eb5a700c777e7f5b1e6` | `53450a4c…` (single parent) | MATCH |
| Production blob `drive_tool/service_client.py` | `d04c637de7b7ed2b9be78d5b18fde60519f71579` | `git hash-object` = `d04c637…` | MATCH |
| Test blob `tests/test_service_client.py` | `41d94d6ba0a184943ff6c80e1acc3d920ce18034` | `git hash-object` = `41d94d6…` | MATCH |
| sha256 production | `03c009ca…68a791` | `03c009ca…68a791` | MATCH |
| sha256 tests | `e10d6145…8ae4f4` | `e10d6145…8ae4f4` | MATCH |
| Accepted policy base | `e55c9f741a528ce9298b5041012373195e878eaf` | merge commit "Add immutable agent authentication and grant policy", tree `f71038e9…`, signature verified | MATCH |
| D053 candidate (delta base) | `53450a4cb71f555addd94eb5a700c777e7f5b1e6` | exists, blob `917df51f…` | MATCH |

The branch head equals the requested candidate exactly. The candidate commit changed exactly two
paths (`drive_tool/service_client.py`, `tests/test_service_client.py`); no other path.

---

## 2. Production delta review (`53450a4` → candidate)

`_validate_file_id` now, for every non-root id: requires the `p/` prefix, a non-empty suffix, a
relative (non-`/`-leading) suffix, and rejects empty/`.`/`..` segments. `root` stays list/find-only
(`allow_root` False for read/save). NUL and backslash are rejected. All checks run before any socket
because they execute at the top of each method, ahead of `_dispatch`.

Rejected before socket: `a.txt`, `docs/x`, `p`, `p/`, `p//x`, `p/../x`, `p/./x`, `/abs`,
`p/a\b`, `p/a\x00b`. Accepted and sent unchanged: `p/a.txt`, `p/docs/x`, `p/a b.txt`,
`p/a+b.txt`, `p/sub/dir/f.txt`. The id is transmitted verbatim — the prefix is never stripped
(list/find/read JSON body; save urlencoded query round-trips space and `+`).

Test delta: relaxed fixture ids updated to canonical ids (`f`→`p/f`, `dir`→`p/dir`,
`a b/c+d`→`p/a b/c+d`) with the original assertions preserved (the wire-body / `file_id=p%2Ff`
expectations are re-pinned, not weakened), plus a new `TestCanonicalFileIdPrefix` class. My own
diff of the two files confirms only id substitutions + the new test class — no assertion removed.

---

## 3. Executed results (measured, not trusted)

| Check | python3.11 | python3.12 |
|-------|-----------|-----------|
| Candidate full suite | **428 OK, 0 skips, exit 0** | **428 OK, 0 skips, exit 0** |
| Candidate client file only | 77 OK | 77 OK |
| My independent probes (candidate) | **35/35 pass** | **35/35 pass** |
| Builder D052 probes (cross-check) | 44/44 pass | 44/44 pass |
| 8 semantic mutation guards (candidate) | all CAUGHT, all compile | all CAUGHT, all compile |

Mutations (compile-clean = semantic, not syntax): M1 unbounded reply read (6 failing),
M2 lost close (7), M3 automatic save retry (6), M4 raw remote error leak (5),
M5 cross-request connection reuse (2), M6 wrong EOF handling (1), M7 revert body-transport fix (11),
M8 remove `p/` prefix enforcement (2).

Oldfail/newpass: the candidate's new tests run against the **old** client (`53450a4`) fail
(1 error, prefix regressions, old client accepts `a.txt` and reaches the socket); against the new
client they pass. So the new tests are genuinely sensitive to the fix.

My 35 probes independently cover: prefix rejection before any socket (all four ops); bare `p`/`p/`;
`root` list/find-only; NUL rejection; canonical ids sent unchanged incl. space/`+`; duplicate
observation headers fail closed (with a raw-stdlib `get_all` check confirming two values); malformed/
missing observation headers; duplicate `Content-Length` (measured: fails closed → `DriveClientError`);
truncated chunked read/save bodies; mid-body stall read/save (→ `timeout`, returns promptly);
conservative uncertainty (`save` True/False, `read` False/True) on refusal/oversize/malformed;
no retries (exactly one request); close on success/error; one fresh connection per call; redaction of
token/root/remote text; and body bounds.

---

## 4. Integration candidate

Because no blockers were found, I created a **new** branch from the exact accepted policy base.

| Item | Value |
|------|-------|
| Base (accepted policy) | `e55c9f741a528ce9298b5041012373195e878eaf`, tree `f71038e9da22044fcfe6ba6f35ce72239a878945` |
| New branch | `feature/module-006a-client-final-integration` |
| Integration head | `f837e8170eab89b7c12d1372626e3ebc20573a20` |
| Integration tree | `d0d4a30f20b95850b38d1cd807f01a1363af9e29` |
| Overlay | `drive_tool/service_client.py` (blob `d04c637…`), `tests/test_service_client.py` (blob `41d94d6…`) |

The integration commit was built with `base_tree = f71038e9…` and the two entries referencing the
**existing** candidate blob SHAs, so the two files are byte-identical to the candidate by construction
(verified by re-downloading the published branch: prod blob `d04c637…`, test blob `41d94d6…`). A
re-downloaded published tree compared against the e55 base shows **exactly two files added and zero
files changed/removed**; every other e55 file is preserved byte-for-byte.

### Combined suite on the published integration branch

| Check | python3.11 | python3.12 |
|-------|-----------|-----------|
| Combined full suite | **490 OK, 0 skips** | **490 OK, 0 skips** |
| Client file only | 77 OK | 77 OK |
| My independent probes | 35/35 pass | 35/35 pass |
| 8 semantic mutation guards | all CAUGHT | all CAUGHT |

490 = 413 (e55 base: core + policy) + 77 (client). This is a new measured count for the combined
tree; it is larger than the client-lineage 428 because the accepted policy base carries the policy
suite that the client lineage does not.

No source or test file was modified by me; I overlaid the two candidate files unchanged and changed
nothing else.

---

## 5. Blockers

**None.** The candidate was retrievable and verified; the branch head matched; the production and test
blobs matched; the suite, probes and mutations all passed; the overlay was clean. The integration
branch was created accordingly.

## 6. Honesty notes

- All client tests are simulated loopback HTTP services — **not** real service integration; no
  real-service acceptance is claimed.
- No merge, no deployment, no package install, no real roots/tokens, no old-branch modification.
  Only the new branch and the new drop evidence path were written.
- Only execution actually performed is claimed. python3.11 = 3.11.2, python3.12 = 3.12.13.
- The final integration acceptance decision remains the director's.
