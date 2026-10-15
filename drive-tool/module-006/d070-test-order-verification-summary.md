# D070 — D066 test-order patch verification (summary)

Status: **done**. Verdict: the DeepSeek D066 patch is semantically valid and correct.

Scope is a single path: `tests/test_partial_scan_review_fixes.py`, method
`PostYieldStorageErrorTests.test_metadata_failure_below_root_is_skipped_and_charged`.
No production edits in the candidate, no merge, no deploy, no real roots. The
candidate branch was created and committed **locally only**; nothing was pushed
to `drive-tool`.

## Exact source pins

- Source ref: `Dolesh-avkalan/drive-tool` @ `4140a528383ad5794cafd1c99aea9a41d9acef11`
  (tree `60aa6b03e2cc50234e14175eb9de9974386633ce`)
- Accepted base: `b7f8d17b9dcc4aec68d54b38f994290e05264e67`
  (tree `4a4e27b9d3f75ffd7c841aa547eacef82734596e`)
- Base test blob: `f110f83c95b846bc853069194ff7759b690ebfca` (identical at base and source ref)
- Candidate branch: `feature/test-nested-scan-order`
- Candidate commit: `8b543f3bf986055c492bc6982341ed5c90beff6d` (local-only)
- Candidate tree: `be4f1f3136a8092b20e1c011fb9d641945a7fe76`
- Candidate test blob: `c01003e7015915db3dcac15a168ff7aae3d423db`
- DeepSeek drop pin resolved: `Dolesh-avkalan/drop`
  `drive-tool/module-006/d066-test-order-correction.md` @
  `fba54dfcb0f660dd12bbbd2faa82cde73459b05a`

`b7f8d17` is an ancestor of `4140a52` (ahead 17, behind 0); the intervening
commits touch only `docs/`, `session/`, `tasks/`, so the test blob and
`drive_tool/local.py` are byte-identical at both refs. The local base
reconstruction is byte-faithful (its git tree and blob SHAs equal GitHub's).

## What was verified

**Seam enforces both nested orders (independent probe, not the test's own
assertion).** Instrumenting `OrderedScanAdapter` and recording yielded names
per directory: with raw filesystem sub-order `['a.txt','b.txt']` unchanged, the
seam yields `['a.txt','b.txt']` for the forward pin and `['b.txt','a.txt']` for
the reversed pin. The seam — not the filesystem — decides the nested order.
`SEAM ENFORCES BOTH NESTED ORDERS: True` on 3.11.2 and 3.12.13.

**Original failure reproduces deterministically.** Running the original body
with `order=["sub"]` gives inspected `2` (passes — the bug is masked on this
filesystem because readdir happens to return `a.txt` first). Running it with
the reversed nested order `["sub","b.txt","a.txt"]` gives inspected `3` →
`AssertionError: 3 != 2`. That is the deterministic reproduction of the
order-dependent failure.

**Patched test passes both orders.** Both subTests pass —
`(order=['sub','a.txt','b.txt'], expected=2)` and
`(order=['sub','b.txt','a.txt'], expected=3)` — with `subtests=2 failures=0
errors=0`, on both interpreters. Strict equality on `inspected`, `skipped`,
`truncated`, `reason` is preserved; no membership relaxation, no skip.

**No filesystem-order masking.** Crossing both seam orders with both file
creation orders (a-then-b, b-then-a) — all four combinations pass on both
interpreters.

**Isolated production charging mutation.** `_post_yield_storage_error` changed
to under-charge by one (`ScanFailure(entry_count)` → `ScanFailure(entry_count
- 1)`) in an isolated copy. It compiles on both interpreters, and against the
patched test **both** subcases fail on both interpreters: a-first
`1 != 2`, b-first `2 != 3`. The mutation was never committed to the candidate.

## Raw execution results

| run | interpreter | result | exit |
|---|---|---|---|
| target test (patched) | 3.11.2 | Ran 1, OK | 0 |
| target test (patched) | 3.12.13 | Ran 1, OK | 0 |
| full suite | 3.11.2 | Ran 506, skipped 0, failures 0, errors 0 | 0 |
| full suite | 3.12.13 | Ran 506, skipped 0, failures 0, errors 0 | 0 |

Full suite run from the candidate tree via
`python -m unittest discover -s tests`.

## One non-blocking note

The DeepSeek hand diff, as pasted, is **not directly `git apply`-able** here:
its hunk has a single leading context line and no trailing context, and this
`git apply` rejects thin hunks (3-lead + 1-trail applies; 3-lead + 0-trail and
1-lead + 1-trail do not). This is a diff-format artefact, not a semantic
defect — the removed block is byte-identical to the file. A canonical patch
regenerated with `git diff` (full context) applies cleanly and is the same
change: 16 lines removed, 22 added, one method.

## Evidence bundle

Raw scripts, logs, the candidate, both patches, the mutation diff and a sha256
hash manifest are under
`drive-tool/module-006/d070-test-order-verification-summary/`.
