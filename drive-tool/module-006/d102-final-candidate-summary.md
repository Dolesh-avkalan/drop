# D102 — final candidate integration (exact-byte overlay)

## Verdict

The final candidate is built, published and independently verified. It is the
accepted PR9-merge base `ebd05b77` with **exactly two unchanged HTTP files
overlaid** from `f37a30b` and **no source fixes**. On this candidate:

- the **full integrated suite** runs **581 tests, OK, skipped=3** with **exit 0**
  on both Python 3.11.2 and 3.12.13; and
- the **exact D101 final HTTP gate** (`--gate`) returns **raw exit 0** with
  **all four stages PASS** on both interpreters, at the frozen counts
  **580+20 / 9680+320 / 300+50**, zero unexpected/unavailable, resources clean.

Both results were produced from the **published bytes** (fetched back and
re-verified). No merge, deploy, target run, install or real-root access was
performed; the separate Gemini source review is untouched and remains
quota-blocked.

## 1. The candidate

- repo `Dolesh-avkalan/drive-tool`
- **branch** `feature/module-006b-final-service-candidate` (published)
- **head** `337e4c713829af76615472eb47b81244ff399528`
- **tree** `169855e4541531961cd25bbcba3da8d1109d85c8`
- **base (parent)** `ebd05b779cac191ab107d3368e6e1f280a8eac16` — the exact accepted
  PR9 merge (`Merge pull request #9 … feature/test-nested-scan-order`)

The overlay is **only** two files, both byte-identical to their source in
`f37a30b0073611c05d26f714f2e833d689673a09`:

| path | git blob | sha256 | bytes |
| --- | --- | --- | --- |
| `drive_tool/http_adapter.py` | `41279e6290617968c3b4f3f91fc3cf9a7dab505a` | `3ed13cfa7960854382577c9e0982d3ba116833793a6430d141732ccac89c020c` | 40881 |
| `tests/test_http_adapter.py` | `7a7be06d5ef0e25d0ac54e11bc5909cda27500d3` | `b678744759bd53c3dc992e215fc7e98cd5df869c381addbaaa2bfb15e2b87dbf` | 76436 |

Composite **sourcehash** (sha256 over the concatenated adapter‖test bytes, path
order): `b8b44c4c056e1925957445cc9b532c53194920124a469df54e49053a7dcbb71c`.

### Scope proof — exactly two additions, all base files unchanged

`git diff --name-status ebd05b77..HEAD` yields precisely:

```
A	drive_tool/http_adapter.py
A	tests/test_http_adapter.py
```

Every path that exists in the base is **byte-identical** to the base: each of
the base tree's files was re-hashed and matched its `ebd05b77` blob, and the only
files present in the candidate beyond the base are the two above. The whole
`drive_tool/` package (except the added adapter) and all 17 other test modules
are unchanged.

### Accepted regression fix preserved

`tests/test_partial_scan_review_fixes.py` is the accepted deterministic
test-order fix, blob `c01003e7015915db3dcac15a168ff7aae3d423db`, carried unchanged
in the base and therefore preserved in the candidate. No source or test file
other than the two overlays was touched.

### Fetch-back verification

The published branch was cloned fresh and re-checked: head `337e4c71…`, tree
`169855e4…`, the two blobs `41279e62…` / `7a7be06d…`, and both files' sha256 match
the values above byte-for-byte. The full suite re-run from the fetched-back bytes
also gives **581 / OK / skipped=3**.

## 2. Full integrated suite (Python 3.11.2 and 3.12.13)

Command: `python3.X -m unittest discover -s tests`.

| interpreter | result | tests | skips | exit |
| --- | --- | --- | --- | --- |
| CPython 3.11.2 | **OK** | **581** | **3** | 0 |
| CPython 3.12.13 | **OK** | **581** | **3** | 0 |

This matches the expected 581 with 3 documented control skips (the base carries
576; the accepted test blob adds the 5 further HTTP tests).

### Skip audit — only the adapter-present control and the two opt-ins

The three skips are exactly:

1. `test_http_adapter.SmokeSoakGateContractTests.test_helper_raises_without_production_adapter`
   — *"production adapter present; gate test not applicable"* (adapter-present
   control, self-skips by design when the production adapter is present);
2. `test_http_adapter.SmokeSoakGateTests.test_stage_smoke_600`
   — *"smoke/soak opt-in (D067_RUN_HTTP_SMOKE_SOAK=1) + production adapter"*;
3. `test_http_adapter.SmokeSoakGateTests.test_stage_soak_10000` — same opt-in.

There are **no adapter-missing skips**; the conformance tests all execute.

## 3. D101 final HTTP gate replay

Harness: `scripts/http_gate_d101.py`, sha256
`3754ca19b4a72797ac16a1e32300ddf399e7117e2dec63def6693d2512db8d7b` (byte-identical
to the D101 published corrected harness), run as
`python3.X scripts/http_gate_d101.py --repo <candidate> --gate`. The frozen
operations, schedules, intents, budgets, the real 6-service-entry saturation
barrier and the gate helper are unchanged.

| stage | 3.11.2 | 3.12.13 |
| --- | --- | --- |
| `selfcheck` | PASS | PASS |
| `smoke600` | PASS **580 + 20**, 0 busy, 0 unavailable, 0 other | PASS same |
| `soak10000` | PASS **9680 + 320**, 0/0/0 | PASS same |
| `saturation_6plus1` | PASS **300 + 50**, 0/0 | PASS same |
| **`--gate` raw exit** | **0** | **0** |

Top-level aggregate `result = PASS` and `executed =
[selfcheck, smoke600, soak10000, saturation_6plus1]` on both. No security gate
was bypassed and no gate helper or source was changed to pass.

**Resources** clean in every stage on both interpreters: `closed=True`, fd
`11 → 4`, the seven `drive-http*` threads reaped, client leases never above 5,
RSS bounded, workspace ≈25.4 KiB and fixtures ≈25.1 KiB (inside the frozen
128 MiB / 32 MiB bounds), each stage inside its 900 s budget (smoke ≈7.5 s,
soak ≈121–123 s, saturation ≈2 s).

**Frozen schedule preserved.** `--dump-schedule` is bit-identical on 3.11.2 and
3.12.13, sha256
`14a6ac33e796dd62d2a1e60415868608c5013c6e2c5bfc39346ec3c3003c0c88` — the D097/D101
recorded full-schedule dump sha256 — and the smoke/soak fingerprints
`74e61249…` / `7f3911b4…` reproduce.

## 4. What was NOT done

- No merge, no deploy, no target run, no installs, no real-root access.
- No source fix and no test change: the two overlays are the unchanged accepted
  HTTP files; nothing was edited to make a gate or test pass.
- No security-gate bypass. The separate final Gemini source review was not
  attempted (it remains quota-blocked until reset) and was not worked around.
- No repeated original full audit: this is exact-byte integration with the
  accepted regression fix.

## 5. Blockers

None. Every required check executed and passed; there is nothing withheld or
deferred except the separate, quota-blocked Gemini review, which is outside this
task's scope.

## 6. Provenance

- Candidate branch: `Dolesh-avkalan/drive-tool @ feature/module-006b-final-service-candidate`
  (head `337e4c71…`).
- Overlay source: `Dolesh-avkalan/drive-tool @ f37a30b0…` (branch
  `feature/module-006b-http-busy-budget`).
- Base: `ebd05b77…` (accepted PR9 merge).
- Evidence bundle: `d102-final-candidate/` and `d102-final-candidate-summary/`
  (`MANIFEST.md`, `PINS.md`, `env.txt`, `logs/`, `scripts/`).

Verification was performed by the parent: the published bytes were fetched back
and hashed, and every raw log in the bundle is the parent's own run output.
