# D043 — Independent execution & adversarial review of MODULE-005B (`read_range`)

Reviewer: Sarvam (independent context — not the implementation author).
Candidate: `Dolesh-avkalan/drive-tool`, branch `feature/module-005b-range-read`,
head `121faf848b2f33f80721239fc7716adba7a9ba62`, tree
`28ce7508c34181d63d62f03a330932a41a08ebe4`, base
`03a8250a5d02823812533290356cf375b7d2c33e`.
Task brief: `tasks/d043-range-read-independent.md` @ `8f5a1cf2…`.
Builder contract: `tasks/MODULE-005B.md` @ `18cc50f613e582e8bcaa9f282bd61b6ea48f1143`
(retrieved separately from the source base, as required).

## Verdict

**ACCEPT WITH NITS.**

Every builder claim that this task asked me to verify reproduced independently:
the candidate/tree/scope are exact; the committed suite is 351 tests / OK / exit 0
/ zero skips on both 3.11 and 3.12 (274 pre-existing + 77 new); the 7-mutant
runner catches 7/7 with each mutant failing its *intended* guard and no
syntax/import accident; and 34 fresh independent adversarial probes pass on both
interpreters. No reachable production defect was found. The nits (§7) are
maintainability observations, not correctness defects, and I explicitly did
**not** invent a blocker for the shared-helper/duplication question (§6).

## 1. Scope and provenance (independently confirmed)

- `GITHUB_GET_A_COMMIT` for `121faf8…` returns commit message
  "Add MODULE-005B evidence report (Sarvam)" and **tree
  `28ce7508c34181d63d62f03a330932a41a08ebe4`** — matches the brief.
- Recursive tree of head vs recursive tree of base `03a8250…`, and a full
  on-disk `diff -r` of the two snapshots, show **exactly the four allowed paths**
  differ:
  - `drive_tool/local.py` — modified (blob `74a45c61…`)
  - `tests/test_local_range.py` — new (blob `7fa3f80e…`)
  - `tests/test_local_range_proofs.py` — new (blob `d217e66b…`)
  - `docs/evidence/MODULE-005B.md` — new (blob `4292b690…`)
  No other tracked path changed. No `__pycache__`/`.pyc` is tracked.
- SHA-256 of the fetched candidate bytes matches the builder report §8 exactly:
  `local.py` `8d382347…ee2b7`, `test_local_range.py` `59651dfa…4555`,
  `test_local_range_proofs.py` `63a7deb6…81c7`. GitHub blob SHAs also match.
- The `local.py` diff is **purely additive**: a `dataclasses` import, the
  `RangeReadResult` dataclass, `_validate_range_options`, the `_os_pread` seam,
  `_require_pread_capability`, `read_range` and `_read_open_file_range`.
  `read_bytes`, `_read_open_file_bounded`, `_traverse_parent_dir`, `stat`,
  `list_children`, `scan_children` and every shared helper are byte-identical to
  base, so base `read_bytes` behaviour is preserved (not merely asserted).
- Builder d040 evidence integrity: every file under
  `drop/drive-tool/module-005b/d040-implementation/` re-hashes to its own
  `MANIFEST.txt` entry (15/15 OK). I did not modify or overwrite any of it.

## 2. Builder claims vs independent result

| Builder claim | Independent result |
| --- | --- |
| 351 tests, OK, exit 0, zero skips, 3.11 and 3.12 | Confirmed (351/OK/0, both) |
| 274 old + 77 new | Confirmed (base suite = 274; new modules = 62 + 15 = 77) |
| 7 mutants, 7 caught, 0 survivors | Confirmed (7/7, both interpreters) |
| No mutation is a syntax/import accident | Confirmed (all 351 collected; FAIL-dominant) |
| Only the 4 allowed paths changed | Confirmed by tree + byte diff |
| Base `read_bytes` unchanged | Confirmed by additive-only diff |

## 3. Independent full-suite execution

Commands (from the candidate root, exactly the contract's):

```
python3.11 -m unittest discover -s tests -v
python3.12 -m unittest discover -s tests -v
```

| Interpreter | Count | Final line | Exit |
| --- | --- | --- | --- |
| Python 3.11.2 | `Ran 351 tests` | `OK` | 0 |
| Python 3.12.13 | `Ran 351 tests` | `OK` | 0 |

The final line is plain `OK`, **not** `OK (skipped=…)`, so zero tests are
skipped. (Twelve log lines contain the substring "skip", but each is a test
*method name* such as `test_disappearing_entry_during_listing_is_skipped`, all
reported `ok`.) Running the committed suite against the **base** snapshot yields
`Ran 274 tests … OK`, confirming the 77-test delta and that no pre-existing test
was deleted or skipped.

Raw logs: `raw/full_suite_python3.11.log`, `raw/full_suite_python3.12.log`,
`raw/base_suite_python3.11.log`. Environment: `env.txt`.

## 4. Independent re-execution of the builder mutation runner

I first read `scripts/mutation_runner.py` in full (published copy retained here,
unmodified). It copies an isolated tree, applies one string substitution, runs
the full suite, and reports a mutant "caught" when a test fails or errors. I
placed the candidate at its hardcoded `SRC_REPO=/scratch/repos/drive-tool` and
ran it **as published** on both interpreters. Baseline was green before every
run.

| Mutant | Caught by | Intended guard present & failing | Failure mode |
| --- | --- | --- | --- |
| M1 read_bytes-and-slice | 25 | yes | 19 FAIL + 6 ERROR; ERROR is the inherited whole-size `ReadLimitExceededError` (exactly the intended semantic) |
| M2 unbounded pread request | 18 | yes | 17 FAIL + 1 ERROR (near-bound offset overflows the 2**30 request) |
| M3 early stop on short read | 9 | yes | 9 FAIL |
| M4 incorrect exact-window EOF | 3 | yes | 3 FAIL |
| M5 missing `O_NOFOLLOW` | 7 | yes | 8 FAIL + 3 ERROR (symlink-listing tests) |
| M6a lost fd cleanup | 5 | yes | 5 FAIL |
| M6b masked error priority | 2 | yes | 2 FAIL |

Checks I ran to rule out a fake "caught": (a) each mutated run still **collected
all 351 tests** (no collection abort), and (b) no `SyntaxError`/`ImportError`/
`ModuleNotFoundError`/`IndentationError` token appears in any mutant log. Every
mutant's *named* intended guards fail for the right assertion (e.g. M4 fails
`test_exact_window_that_fills_request_is_not_eof` on
`assertFalse(res.eof_observed)`; M6b fails
`test_primary_pread_error_wins_over_close_failure` on
`assertIn("reading range", …)`). The M1 ERROR stack shows
`_read_open_file_bounded` raising `ReadLimitExceededError` — the whole-size
rejection the mutation was designed to reintroduce. **Mutation evidence is
meaningful, not accidental.**

Raw logs: `raw/mutation_runner_py3{11,12}.stdout.txt`,
`raw/mutation_py3{11,12}/*.log`.

## 5. Independent adversarial probes

`scripts/d043_independent_probe.py` is written from scratch (it does not import
or reuse the builder's tests). It uses observational spies that wrap the
adapter's own OS seams and delegate to the **real** `os.open/fstat/pread/read`,
so "observed" calls are genuine kernel calls; controlled fault injection is
labelled as simulated. **34 checks, 34 pass, 0 fail on both 3.11 and 3.12.**
Coverage and results:

- **Option type/bounds before I/O** — 12 invalid cases (bool/float/str offset;
  negative/over-2**63-1 offset; bool/float/zero/negative/over-cap length;
  `offset+length > 2**63-1`) all raise the correct `TypeError`/`ValueError` with
  **zero syscalls** (spy `io_total` unchanged). Boundary `offset+length ==
  2**63-1` is accepted and yields empty/`eof=True` beyond EOF.
- **Default window** — `min(262144, cap)`: cap 100000 → 100000 returned; large
  cap → 262144 returned; first pread chunk correctly capped at 65536.
- **Sparse larger-than-cap / high offset, no prefix** — 1 MiB sparse file, tiny
  `length=4` at offset 1 000 000 returns `WXYZ`; **first pread starts exactly at
  the requested offset** (no prefix read); no zero-length pread; `read_bytes`
  still denies the whole file.
- **Exact window** — single pread, no lookahead probe, `eof_observed=False`.
- **Short reads / EINTR** — injected 1-byte short read then `EINTR` then normal:
  window filled (`ABCDEFGHIJ`), EINTR retried.
- **Initial-only metadata** — `observed_size` stays the pre-growth value while
  the appended bytes are visible via pread; truncation after fstat yields stale
  `observed_size` with honest data.
- **Offset beyond EOF + growth** — empty/`eof=True` before growth; the same
  offset returns real bytes after growth.
- **Unavailable/non-callable `os.pread`** — `UnsupportedPlatformError` before any
  filesystem call, while construction and `read_bytes` keep working; a
  non-callable `os.pread` also fails closed.
- **Precedence** — source mismatch → malformed id → root(IsDirectoryError) →
  closed, each ahead of option validation, matching `read_bytes` order.
- **FIFO** — rejected (`UnsupportedEntryError`) without blocking (bounded by a
  watchdog thread).
- **No-follow** — final-component symlink rejected (`UnsafePathError`).
- **Root anchoring** — root renamed and replaced by an outside symlink still
  reads the original bytes.
- **Concurrency** — parallel calls at independent offsets each return the correct
  window; **no fd growth** over 60 success+failure ops (`/proc/self/fd` stable).
- **Error priority** — a primary pread `OSError` is preserved (as
  `LocalStorageError` with the `OSError` cause) even when the close seam also
  fails.

Raw logs: `raw/probe_python3.11.log`, `raw/probe_python3.12.log`.

**Honesty note.** My first probe draft reported 3 failures; on inspection all
three were wrong expectations in *my* probe (the first pread chunk is capped at
65536, one fixture was smaller than the default window, and my growth-byte
arithmetic ignored the 4-byte prefix). The implementation was correct in all
three. I corrected the probe and re-ran to a clean 34/34; the corrected script is
what is published.

## 6. Duplicated target-open control flow / resolver reuse (specific scrutiny)

The brief asks whether `read_range` reuses the existing resolver/ownership
machinery or drifts into a second path resolver. Findings:

- `read_range` (candidate `drive_tool/local.py` L1498–L1536) calls the **same**
  `_check_source_and_state`, `_parse_file_id`, `_traverse_parent_dir`,
  `_file_open_flags`, `_classify_component_open_error` and `_release_owned` used
  by `read_bytes` (L1370–L1402). My probe monkeypatched
  `_parse_file_id`, `_traverse_parent_dir` and `_file_open_flags` and confirmed
  **all three are invoked** by `read_range`, so it is not a parallel resolver.
- The open-target block (~20 lines: open with `dir_fd`, register in `owned`,
  `finally: _release_owned`) is **textually duplicated** between `read_bytes` and
  `read_range`, and the regular-file validation is duplicated between
  `_read_open_file_bounded` and `_read_open_file_range`. The brief explicitly
  permits — but does not require — a shared private helper, and explicitly warns
  against inventing a blocker merely for sharing established helpers. The
  duplicated code calls the *same* helpers with the *same* arguments, so there is
  **no behavioural drift and no independent resolver today**. This is a
  maintainability nit (§7, N1), not a reachable defect and not a blocker.
- Ownership: a descriptor is registered the moment it is acquired; the single
  `finally` releases parent+child exactly once, covering the parent-close
  handoff. Verified by fd-stability and error-priority probes.

## 7. Findings (source-referenced)

No **CHANGES REQUIRED** items. Nits:

- **N1 (nit, maintainability).** The target-open + `owned` + `finally` block and
  the regular-file validation are duplicated between the `read_bytes` and
  `read_range` paths (`local.py` L1384–L1402 vs L1516–L1536; L1413–L1420 vs
  L1555–L1562). A shared private helper would remove future drift risk. Not
  required by the contract; behaviour is currently identical.
- **N2 (nit, unspecified ordering).** `_validate_range_options` runs before
  `_require_pread_capability` (L1504–L1507), so on a platform with no `os.pread`
  and invalid options the option error wins. The contract fixes neither
  precedence; harmless and fail-closed either way.
- **N3 (observation, not a defect).** `eof_observed` and the initial `fstat`
  observations are per-call only; a caller must not treat them as a snapshot.
  This is exactly what the contract requires and the code documents.

## 8. Limitations / NOT RUN

- **Real syscall tracing: NOT RUN.** No `strace`/`ltrace` is present on this
  kernel (`4.19.0-gvisor`). Syscall observation is seam-mediated (the spies
  delegate to the real `os.*` calls). No kernel-level trace is claimed.
- **Python 3.13/3.14: NOT RUN.** Only 3.11.2 and 3.12.13 are installed; none was
  installed or claimed. No portability claim is made for other versions/kernels.
- **Target cloud / integration / merge: out of scope.** Nothing was merged,
  deployed, or pushed to `main`; the implementation and all d040 evidence were
  left untouched.
- This review is not acceptance; it is evidence for the owner to assess.

## 9. Artifacts

All files listed in `MANIFEST.txt` (bytes + SHA-256), published under
`drop/drive-tool/module-005b/d043-independent-verification/`. No file under
`d040-implementation/` was modified.
