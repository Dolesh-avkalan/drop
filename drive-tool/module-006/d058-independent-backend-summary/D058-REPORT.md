# D058 — independent backend review, reproduction and source publication (report)

Verdict: **ACCEPT** (no contract-breaking defect; candidate published and verified).
This report is the evidence backing the summary `../d058-independent-backend-summary.md`.

## Pins
- Contract `tasks/d050-file-service-implementation.md` @ `8eac68b98481b86e7ae164a5835063584c15fdcb`
  sha256 `7632d4868bba9025167f21aa0f3c1e579141a59638bf7f0e38b17126ff79f267`.
- Accepted base `Dolesh-avkalan/drive-tool` @ `e55c9f741a528ce9298b5041012373195e878eaf`
  tree `f71038e9da22044fcfe6ba6f35ce72239a878945`.
- Builder drop `Dolesh-avkalan/drop` @ `8da43959e93d36649add7422a256b7688d70c84e`.
- Generated answer `drop` @ `2b980155e82e985a08d3a9eb7d517bf6a69603db`
  `drive-tool/module-006/d050-gemini-file-service.md` sha256 `ea0c018390ffe127299161b9006f2aef6b2a353659e18262f5b811d82c7b88b8`.

## Source fix vs generated answer
A diff of the generated `file_service.py` against the delivered one shows exactly one
functional change: the addition of `_canonical_id()` and its use in place of
`"/".join(parts)` for the list/find/read parent refs and the save parent chain. This
restores the canonical `p/…` FileRef id that `local._parse_file_id` requires; without
it the adapter re-parsed bare ids and raised `UnsafePathError`, so reads/lists/saves
returned `denied`. No other production change was made.

## Execution matrix (raw logs in `logs/`)
| Run | 3.11.2 | 3.12.13 |
|---|---|---|
| Baseline (base, existing tests) | 413 OK | 413 OK |
| Candidate full | 429 OK | 429 OK |
| Candidate focused | 16 OK | 16 OK |
| Original tests vs original source | 16 errors | (same cause) |
| Corrected tests vs original source | 2 failures + 4 errors | — |
| Original tests vs corrected source | 16 errors | — |
| Published bytes re-fetched, re-run | 429 OK / 16 OK | 429 OK / 16 OK |
The 16 errors are all `TypeError: token_sha256 must be bytes` — a generated-harness
defect (hex string instead of a raw 32-byte digest), independent of the source.

## Mutations (`scripts/indep_mutations.py`, `scripts/reproduce_mutations.py`; `logs/mutations.txt`)
All seven independently-written semantic mutants are CAUGHT on both interpreters:
| Mutation | Failing tests |
|---|---|
| M1 skip per-(agent,alias,op) grant lookup | auth-before-parse; readonly-denial |
| M2 alias-only binding key | two-agents-same-alias + 6 others |
| M3 bool accepted as offset/limit | invalid-options-no-io |
| M4 dropped save uncertainty | 4 save tests |
| M5 close ignores active leases | concurrent-blocked-read-close-timeout |
| M6 always create parents | save-creates-missing-parents |
| M7 double close | concurrent-closes-close-once |
M7 requires removing the whole idempotency mechanism (the flags and the per-binding
`closed` guard are redundant defense-in-depth); representative raw failure
`AssertionError: 4 != 1` at `self.assertEqual(close_calls, 1)`.

## Probes (`scripts/indep_probes.py`, `scripts/reproduce_probes.py`; `logs/probes_*.txt`)
54/54 checks PASS on both interpreters: alias isolation; traversal/malformed id
rejection (`denied`); `root` forbidden (`invalid`); wrong-kind errors (`invalid`);
symlink read and symlinked-parent save refused (`denied`) with the outside tree
untouched; exact cap boundaries (`too_large` at cap+1); exact-EOF semantics; 8-way
concurrent no-overwrite publish (1 winner, 7 `exists`); fd stability; timeout close
keeps the active fd and denies new leases; 6-way concurrent close closes once;
redaction with `__cause__` None.

## D054 test-correction assessment
Mechanical corrections: raw digest; ≥32-char tokens; canonical `p/…` ids;
`eof_observed`; real on-disk path. Strengthenings: the redaction test is no longer
vacuous (it now reaches the storage-error path); the rollback test asserts each
opened adapter is closed exactly once; the list/find test replaced an incorrect
"symlink appears in skipped" expectation with a real `chmod 000` subtree and adds
`truncated`/`reason` assertions. No assertion was removed without replacement and
none was loosened to mask a defect.

## Publication
- Branch `feature/module-006a-file-service-independent` (drive-tool) from base `e55c9f7`.
- Commit `14729120c0f32ee5d64c1daf93b27fa1b3270d6b`, tree `3482dc4325afb5adf4b7ecfcbfe1e76a1ad0356c`,
  parent `e55c9f741a528ce9298b5041012373195e878eaf`.
- Blobs `b7e18c606f45066cd54ec66016e70e797486ef50`, `8b5248f9365d8cac6e1331bb4677dea48a1778ff`.
- Scope: exactly two new paths; base unchanged. No merge; default branch untouched.

## Deviations / limitations
Three non-blocking deviations (whitespace-only `find` → `invalid`; `list` offset
beyond length → `invalid`; default read length vs a smaller grant cap → `too_large`),
and one inert annotation defect (`Never` used without import). Only 3.11.2 and
3.12.13 available. Independent verdict only; integration remains with the director.
