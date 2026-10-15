# D058 — independent backend review, reproduction and source publication (final answer)

**Verdict: ACCEPT.** On fresh, independent inspection and execution, the D050/D054
synchronous file-service backend satisfies the D050 contract, and the two-file
candidate was published from the exact accepted base and verified byte-for-byte.
Three minor, non-blocking deviations and one latent (inert) annotation defect are
recorded below. No source or test changes were made; no merge/deploy was performed.

## 1. Provenance and pins (independently retrieved and verified)

| Item | Value |
|---|---|
| Contract | `tasks/d050-file-service-implementation.md` @ `8eac68b98481b86e7ae164a5835063584c15fdcb`, sha256 `7632d4868bba9025167f21aa0f3c1e579141a59638bf7f0e38b17126ff79f267` |
| Accepted base | `Dolesh-avkalan/drive-tool` @ `e55c9f741a528ce9298b5041012373195e878eaf`, tree `f71038e9da22044fcfe6ba6f35ce72239a878945` |
| Builder drop | `Dolesh-avkalan/drop` @ `8da43959e93d36649add7422a256b7688d70c84e`, `drive-tool/module-006/d054-file-service-assembly-summary/` |
| Generated answer | `drop` @ `2b980155e82e985a08d3a9eb7d517bf6a69603db`, `drive-tool/module-006/d050-gemini-file-service.md`, sha256 `ea0c018390ffe127299161b9006f2aef6b2a353659e18262f5b811d82c7b88b8` |
| Candidate `drive_tool/file_service.py` | sha256 `befe20bba64252d5595ac68e4af8459f4d8686dd31d14f5bfbf5159fa8b56f8c`, git blob `b7e18c606f45066cd54ec66016e70e797486ef50` |
| Candidate `tests/test_file_service.py` | sha256 `855df6ef02139f003cf7cfd26ccd1c43bce52b14e332c774f23a6de2917ad8dc`, git blob `8b5248f9365d8cac6e1331bb4677dea48a1778ff` |

The contract file is byte-identical at the accepted base and at the pinned contract
commit. The two drop source files match the brief's expected SHA256 exactly.

## 2. Method (fresh context, own probes and execution)

The audit did not reuse the builder's results as evidence. It:
1. rebuilt a candidate tree as *exact base + the two drop files verbatim* and
   confirmed it is byte-identical to the builder's committed blobs;
2. re-ran the full and focused suites on Python 3.11.2 and 3.12.13;
3. ran **cross-runs** (original generated tests vs original generated source;
   corrected tests vs original source; original tests vs corrected source);
4. executed its **own** 7 semantic mutants (`indep_mutations.py`) on both interpreters;
5. executed its **own** POSIX/concurrency/adversarial probes (`indep_probes.py`);
6. published the candidate branch and re-fetched and re-ran the **actual committed**
   bytes.

Raw logs and the harness scripts are in the sibling folder
`drive-tool/module-006/d058-independent-backend-summary/`.

## 3. Independent results

| Run | Result |
|---|---|
| Baseline (accepted base, existing tests only) | **413 tests, OK** (3.11, 3.12) |
| Candidate full suite | **429 tests, OK** (3.11, 3.12) |
| Candidate focused module | **16 tests, OK** (3.11, 3.12) |
| Original generated tests vs original generated source | 429, **16 errors**, every one `TypeError: token_sha256 must be bytes` (a test-harness defect, not a source defect) |
| Corrected tests vs original generated source | 429, **2 failures + 4 errors** — the corrected tests do catch the source defect (missing `p/` prefix) |
| Original tests vs corrected source | 429, **16 errors** — same harness defect, independent of source |
| Published-branch bytes re-fetched and re-run | **429 OK / 16 OK** (3.11, 3.12) |

**7 semantic mutants, independently written, each CAUGHT on both interpreters**
(M1 skip per-(agent,alias,op) grant lookup; M2 alias-only binding key; M3 bool
accepted as offset/limit; M4 dropped save uncertainty; M5 close ignores active
leases; M6 always create parents; M7 double close). Raw: `logs/mutations.txt`.

**Own probes: 54/54 checks PASS on both interpreters** (`logs/probes_*.txt`):
alias isolation across identical aliases; traversal/absolute/backslash/NUL/
dot-component file_ids rejected `denied`; `root` forbidden for read/save
(`invalid`); directory read and file listing `invalid`; symlink read `denied` and
symlinked-parent save `denied` with the outside tree untouched; cap boundaries
exact (`too_large` at cap+1); exact-EOF semantics (`eof_observed` False on an
exact-fill window, True only on an observed EOF); 8 concurrent no-overwrite
saves → exactly one winner, seven `exists`; fd count stable over 100 ops;
`close(timeout)` returns False with the active descriptor open and denies new
leases (`unavailable`, `retry_safe=True`), then a later close drains; 6 concurrent
closes close exactly once; error redaction holds (no root/token, `__cause__` None).

## 4. Contract inspection (independent)

Auth-then-authorize precedes ID parsing, option validation and any per-request
filesystem call in all four operations. Per-`(agent_id, source_alias)` adapters
and writers are anchored to the grant's own root with the grant's caps and
`max_list_entries=2000`; ≤6 agents / ≤32 grants are rejected before any adapter
opens; startup rollback closes each opened adapter once and preserves the
original exception. Option bounds match the contract (limit 1..100; non-bool
integer offsets ≥0; find entry budget 1..2000; depth 0..16; read window 1..grant
cap ≤1 MiB with int64 sum; `name_contains` limits; exact-bool flags; exact-bytes
data; cap exceed → `too_large`). `list`/`find` return the exact wire metadata and
partial/skip contract; `read` returns the accepted immutable `RangeReadResult`
unchanged; `save` builds the canonical parent chain top-down and reports
`parents_may_have_been_created` conservatively. Storage errors map to the fixed
codes with concrete classes before broad `ValueError`; post-lease save failures
are flagged `outcome_uncertain=True, retry_safe=False`; boundary errors carry no
raw OS error, root, token or bytes (`__cause__` None, context suppressed).
Lifecycle (`close`) is a lease-aware, single-close, drain-first method with no
`__del__` forced closure; the condition lock is never held during I/O.

## 5. D054 test-correction assessment (weakened assertions?)

A full diff of the generated test file against the delivered one was inspected.
Every correction is either mechanical (raw 32-byte digest instead of hex; ≥32-char
tokens; canonical `p/…` ids; `eof_observed` not `eof`; the real on-disk path
`root/a/b.txt`) or a strengthening:
- the redaction test was **vacuous** in the generated version (its token was <32
  chars, so auth denied before the mocked storage error); after the fix it genuinely
  exercises the translation path;
- the startup-rollback test now records successfully-opened adapters and asserts
  each is closed **exactly once**, replacing a count that could be polluted by
  `LocalAdapter.__del__`;
- the list/find test replaced an **incorrect** expectation (that an omitted symlink
  appears in `skipped`; `search.find` never reports omitted symlinks there) with a
  real `chmod 000` unreadable subtree, and additionally asserts `truncated` and
  `reason=="skipped"`.

No assertion was removed without replacement and none was loosened to hide a
defect. One nuance: the double-close guard is defense-in-depth (a redundant
`_closed`/`_closing_adapters` gating plus a per-binding `closed` flag), so removing
any single guard is compensated by the others; removing the whole idempotency
mechanism is what the concurrent-close test catches (my M7). This is robustness,
not a weakened test.

## 6. Publication (candidate source branch)

- New branch **`feature/module-006a-file-service-independent`** in
  `Dolesh-avkalan/drive-tool`, created from the exact accepted base `e55c9f7`.
- Commit **`14729120c0f32ee5d64c1daf93b27fa1b3270d6b`**,
  tree **`3482dc4325afb5adf4b7ecfcbfe1e76a1ad0356c`**, parent `e55c9f7…`.
- Overlaid **only** the two drop files, verbatim (blobs `b7e18c60…`, `8b5248f9…`).
- Scope vs base: **exactly two new paths**, every other base file unchanged.
- The tree hash was independently reproduced locally before publishing, and the
  committed bytes were re-fetched and re-run after publishing (429 OK / 16 OK).
- No merge; drive-tool default branch untouched.

## 7. Blockers and limitations (honest)

- **No contract-breaking blocker found.** Three minor, non-blocking deviations:
  1. `find(name_contains="   ")` (whitespace-only) is rejected `invalid`; the contract
     only requires a non-empty ≤256-char string, so this is stricter than required.
  2. `list(offset=<beyond filtered length>)` maps the helper's `ValueError` to
     `invalid`; the contract does not define that case (offset == length returns an
     empty page with `next_offset=None`, which is fine).
  3. `read()`'s default `length=262144` exceeds a grant whose read cap is smaller,
     yielding `too_large` — consistent with the contract's "length ≤ grant cap"
     rule, but worth noting for small-cap grants.
- Latent, inert annotation defect: `_raise_service_error(...) -> Never` uses `Never`
  without importing it. `from __future__ import annotations` keeps it inert at
  runtime; left unchanged (the brief forbids source fixes).
- Only Python 3.11.2 and 3.12.13 were available.
- The parent agent's own sandbox program context is restricted from the GitHub
  toolkit, so the branch publication and the independent reproduction were executed
  through sub-agent sandboxes using the same GitHub tools; the resulting bytes were
  verified by SHA256 and by re-running the committed candidate.
- This is an independent review/execution verdict, **not** an integration or merge.
  Final acceptance/integration remains with the director.

## 8. Review/execution vs builder claims

The D054 builder claimed: baseline 413; delivered 429 with 16 `token_sha256`
errors; a `_canonical_id` source fix; seven harness corrections; final 429 OK on
both interpreters; focused 16 OK; seven mutations caught. Independently confirmed:
baseline 413 OK; the delivered-verbatim failure is exactly the 16 `token_sha256`
errors; the source diff is exactly the `_canonical_id` addition; the corrected tests
fail against the un-fixed source (2 failures + 4 errors), proving the source fix was
necessary; final 429 OK / focused 16 OK on both interpreters; the builder's claimed
final tree `3482dc43…` and blob hashes reproduce exactly from base + the two files;
and seven independently-written mutants are all caught. The builder's honesty
caveats (no acceptance claim; only 3.11/3.12; the `Never` annotation left inert) are
accurate. All artifacts referenced above are in the sibling folder.
