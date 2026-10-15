# d034 — independent execution and adversarial review of MODULE-005A (Sarvam)

Independent check of candidate **`593759a40645386427bad35d53e8b856aeaa68d5`**
(`Dolesh-avkalan/drive-tool`, branch `feature/module-005a-partial-scan`), base
`356a4d8a71d0e57a57e7c82dbfce50be145a0bdb`. Performed from the sandbox against a
fresh fetch of the pinned commit; **no implementation was modified, no branch
head was changed, no merge or deploy occurred.**

## 0. Pin confirmation and director overrides

- **Pinned candidate SHA:** `593759a40645386427bad35d53e8b856aeaa68d5` — confirmed
  as the **head of `feature/module-005a-partial-scan`** (GitHub "branches for head
  commit" returns exactly this branch) and `ahead_by: 1` over the base.
- **Base SHA:** `356a4d8a71d0e57a57e7c82dbfce50be145a0bdb`; its parent is
  `a84f6b3328d2caeb8d71f7c009e370dfea9cf452` (the approved MODULE-005 merge).
- **Three d031 director overrides** (adopted, and I checked the candidate honours
  them): **(1) no uncharged lookahead** — the scan stops at B raw entries and never
  calls `next()` for entry B+1; **(2) no metadata-only legacy fallback** — `find`
  hard-requires a callable `scan_children` and raises `ScanUnsupportedError` rather
  than falling back to `list_children`; **(3) charge failed-scan work** —
  `ScanFailure(inspected, error)` carries the raw entries yielded before a failure.

The pinned bundle `D033-REVIEW.txt` was verified to be the candidate source: every
embedded file's stated git blob hash matches the file at the pinned commit
(`storage.py 3f4f8dcf…`, `local.py d2d03ac0…`, `search.py 5a193441…`,
`test_partial_scan.py 0939ee77…`, `test_partial_scan_proofs.py 51c990bc…`,
`test_search.py 6c31aed4…`, `MODULE-005A.md 6feb5418…`).

## 1. Environment and full-suite execution

- Platform: Debian GNU/Linux 12 (bookworm), x86_64, uid 1000, **gVisor** sandbox
  kernel (raw `readdir` order emulated; the deterministic seam controls order).
- Interpreter A **Python 3.11.2**, Interpreter B **Python 3.12.13** (no newer
  interpreter installed; none installed).
- Command (repo root): `python3.11 -m unittest discover -s tests -p 'test_*.py' -v`
  (and `python3.12`).

| Interpreter | Count | Final | Exit | Skips |
| --- | --- | --- | --- | --- |
| 3.11.2 | `Ran 256 tests` | `OK` | 0 | 0 |
| 3.12.13 | `Ran 256 tests` | `OK` | 0 | 0 |

This independently reproduces the candidate's **256 tests on 3.11/3.12** claim.
Raw logs: `logs/suite_python3.11.log`, `logs/suite_python3.12.log`.

Scope audit (`diff -rq` candidate vs base) confirms **only the allowed files
changed**: `drive_tool/{storage,local,search}.py`, `tests/{test_search,test_partial_scan,test_partial_scan_proofs}.py`,
`docs/evidence/MODULE-005A.md`. `local_write.py`, `listing.py`, `__init__.py`,
read/stat containment and every `session/` document are untouched; all
`list_children` and write tests pass unchanged.

## 2. Independent probe battery (`scripts/probe_d034.py`)

40/40 contract checks pass, identically on 3.11 and 3.12, exercising the strict-B
seam, the accounting contract and adversarial edges (raw logs `logs/probe_python3.*.log`).
Highlights, all **PASS**:

- **strict B, no B+1**: a 10-entry dir with `max_entries=4` records exactly 4
  `next()` calls and ≤4 `stat` calls, `inspected=4`, `complete=False`.
- **local exact-budget unknown EOF**: 5-entry dir, `max_entries=5` → `inspected=5,
  complete=False`; `max_entries=6` → `complete=True`.
- **retained prefix matches**: an over-budget real dir keeps an early match,
  `truncated=True, reason="max_entries", inspected=B`.
- **mixed omitted/raw entries charged**: writer-temp + symlink + FIFO + regular
  file → `inspected=4`, items only the regular file; an ENOENT-disappearing entry
  is charged but omitted.
- **failed iteration / stat / iterator-close / fd-close accounting**: `ScanFailure`
  with the right `inspected`, `error` a `StorageError`, `__cause__` the `OSError`;
  `inspected` correct on both the partial-return and complete-path iterator-close
  failures.
- **root original-error identity**: a root `ScanFailure` re-raises the **same**
  error object (`assertIs`).
- **BFS sibling suppression after exhaustion**: after a failed scan consumes the
  budget, the sibling is never scanned (`calls == [root, p/s1]`).
- **result/depth priority**: `max_results` precedence; explicit `max_depth` reason.
- **malformed reports rejected loudly**: non-tuple `items`, bool/str `inspected`,
  out-of-range `inspected`, non-bool `complete`, `len(items)>inspected`, and an
  incomplete batch that does not exhaust the budget — all raise `StorageError`.
- **legacy scanner denial**: missing / non-callable `scan_children` →
  `ScanUnsupportedError`; argument validation still runs first.
- **fd hygiene**: 60 partial + 60 failing scans leave `/proc/self/fd` flat.

## 3. Findings

### F-B (blocking) — a skipped subdirectory does not surface as incomplete coverage, and the docs do not make it honest

**Where:** `drive_tool/search.py` — the `except StorageError` branch (lines 232–239),
the `except ScanFailure` depth>0 branch (lines 228–231), and the terminal return
(lines 313–319) which sets `truncated=False, reason=None` without consulting
`skipped`. Docs: `FindResult` docstring (lines 43–57), the `find` docstring
(lines 160–168), and `docs/evidence/MODULE-005A.md` §3/§9.

**Concrete scenarios (reproduced, both interpreters):**

1. Root has one subdirectory `p/bad` whose scan raises a pre-scan `NotFoundError`
   and no other work. `find(root, "x")` returns `items=(), skipped=("p/bad",),
   truncated=False, reason=None`.
2. Root has one subdirectory `p/sub` whose scan raises `ScanFailure(2, …)` that
   does **not** exhaust the budget. `find(root,"x",max_entries=100)` returns
   `skipped=("p/sub",), truncated=False, reason=None, inspected=3`.

**Impact:** the contract requires "**Do not report complete search coverage when
truncation or skipped directories indicate otherwise**." A consumer that reads the
primary completeness flag (`truncated`/`reason`) — e.g. `if not r.truncated and not
r.items: report "not found"` — concludes the subtree was searched and nothing
matched, when in fact a subdirectory was never examined. For a module whose stated
purpose is *honest search accounting*, this is the one place the result can still
mislead.

**Test coupling:** the current behaviour is baked into two tests, so a fix must
update them: `tests/test_partial_scan.py:656`
(`test_subdir_scanfailure_is_skipped_and_charged` asserts `assertFalse(result.truncated)`)
and `tests/test_search.py:399` (`test_subdirectory_storage_error_skipped` asserts
`assertFalse(r.truncated)` and `assertIsNone(r.reason)`). My reverse mutation X1
(forcing `truncated=bool(skipped)`) is caught **only** by these two tests — i.e. the
suite encodes the defect rather than proving the invariant.

**Narrow fix (one of):** (a) set `truncated=True` with a distinct `reason` (e.g.
`"skipped"`) whenever `skipped` is non-empty at return; or (b) if the design keeps
`truncated` bound-only, state the invariant explicitly on `FindResult`/`find`
("a non-empty `skipped` means the search is not exhaustive, regardless of
`truncated`") and in `docs/evidence/MODULE-005A.md`. Regression tests: assert that a
skipped subdirectory cannot coexist with an *unqualified* complete result, and that
the honesty statement is present.

### F-A (required) — malformed `ScanFailure.error` is rejected only at the root

**Where:** `drive_tool/search.py:220–227` (root) rejects a `ScanFailure` whose
`.error` is not a `StorageError`; the depth>0 branch (`228–231`) does **not**
validate it and silently records the directory in `skipped`.

**Concrete scenario (reproduced):** `bad = ScanFailure(1, "not-a-storage-error")`.
At the root, `find` raises `StorageError` (rejected). The **same** object returned
from a subdirectory's scan is accepted: `find` returns
`skipped=("p/sub",), truncated=False` with no error. My mutation X2 (adding the
identical check at depth>0) **survived the whole suite** — the case is untested.

**Impact:** the same malformed input is treated two ways depending on depth, and at
depth>0 an adapter bug is silently converted into a "skipped" directory — which also
feeds F-B. Severity low (a conforming adapter always passes a `StorageError`), but
it is a genuine validation asymmetry with zero test coverage.

**Narrow fix:** apply the `isinstance(failure.error, StorageError)` check at every
depth, not only `depth == 0`. Regression test: a depth>0 `ScanFailure` with a
non-`StorageError` `error` raises `StorageError`.

### F-C (robustness nit, outside the enumerated seam) — a `StorageError` raised after an entry is yielded, outside the four enumerated sources, escapes `ScanFailure` uncharged

**Where:** `drive_tool/local.py` `scan_children` — the metadata step
(`self._build_metadata(...)`, lines 1202/1208) and the stat seam
(`entry.stat(...)`, line 1184) only catch `FileNotFoundError`/`OSError`
(1186–1196); a `StorageError` raised there is not caught by the outer
`except OSError` (1227–1234), and the `finally` (1236–1246) suppresses cleanup
while another exception is propagating, so it escapes as a **bare** `StorageError`
with the already-yielded count discarded. Helper `_scan_work_error` (536–553)
wraps only `OSError`-derived failures.

**Concrete scenarios (reproduced):** injecting `LocalStorageError` from the stat
seam (a metadata operation) after one yielded entry, or from `_build_metadata`
after one yielded entry, escapes as a bare `LocalStorageError` — **not** a
`ScanFailure`, so the raw work is unaccounted. Fed through `find` at depth>0 the
subdirectory's work is charged as **zero** (probe `C3`: total `inspected=1` for a
subdir that yielded 2+ raw entries before failing).

**Labelling:** the contract enumerates exactly four chargeable sources — iteration,
non-ENOENT child stat, iterator close, descriptor cleanup. A `_build_metadata` /
`StorageError`-typed stat failure is **outside** that enumeration, so this is not a
letter-of-contract breach. It is also not reachable through the shipped
`LocalAdapter` (its `entry.stat` raises only `OSError`; `_build_metadata` never
raises), so practical severity is low. It is reported because the task asked to
look for "unaccounted work escaping `ScanFailure`", and because it shares the
same "raw work silently lost at depth>0" surface as F-B.

**Narrow fix (optional):** widen the scan's error wrapping to any `StorageError`
raised after `entry_count > 0` (route `_build_metadata`/stat through
`_scan_work_error`), or document that only the four enumerated sources are
guaranteed charged. Regression test: a `StorageError` from the metadata seam after
a nonzero prefix yields `ScanFailure(prefix, …)`.

## 4. Mutation checks (`scripts/mutations.py`)

Applied to isolated scratch copies (never committed), full suite run each time,
identical on 3.11 and 3.12 (raw logs `logs/mutations_py3*.log`).

The candidate's **seven** mutations are all **caught** — independently confirming
its §7 claim (7 caught, 0 survivors):

| Mutation | Result | Failing tests |
| --- | --- | --- |
| M1 discard partial matches | CAUGHT | 3 (`test_early_match_retained_from_over_budget_directory`, …) |
| M2 count only metadata | CAUGHT | 3 (`test_mixed_hidden_temp_symlink_fifo_all_charged`, …) |
| M3 read B+1 entries | CAUGHT | 11 (incl. `test_huge_directory_stops_after_exactly_b_no_b_plus_1`) |
| M4 `complete=True` at cap without EOF | CAUGHT | 8 |
| M5 ignore `ScanFailure.inspected` | CAUGHT | 2 (`test_subdir_scanfailure_is_skipped_and_charged`, …) |
| M6 scan sibling after exhausted budget | CAUGHT | 1 (`test_no_scans_after_failed_work_exhausts_budget`) |
| M7 leak fd on partial return | CAUGHT | 3 (`test_no_fd_growth_on_partial_and_failing_scans`, …) |

My own mutations:

| Mutation | Result | Meaning |
| --- | --- | --- |
| X1 force `truncated` when `skipped` non-empty | CAUGHT (2 tests) | the suite **encodes** F-B's behaviour |
| X2 add `ScanFailure.error` check at depth>0 | **SURVIVED** | F-A is **untested** |

## 5. Verdict

**CHANGES REQUIRED.**

The core scan/accounting contract is correct and thoroughly exercised: strict-B
with no B+1 lookahead, conservative local exact-budget incompleteness, retained
partial-prefix matches, mixed-entry charging, failure accounting for the four
enumerated sources, root error identity/cause, BFS sibling suppression after
exhaustion, result/depth priority, loud malformed-report rejection, legacy scanner
denial and fd hygiene all pass independently, and all seven claimed mutations are
caught. The required changes are narrow:

1. **F-B (blocking):** a skipped subdirectory must not yield an unqualified
   complete result — either set `truncated`/a reason when `skipped` is non-empty,
   or make the "non-empty `skipped` ⇒ not exhaustive" invariant explicit in the
   `FindResult`/`find` docs and the evidence report. Update the two tests that
   currently assert the opposite.
2. **F-A (required):** validate `ScanFailure.error` at **every** depth, not only
   the root, and add a regression test.
3. **F-C (optional nit, outside the enumerated seam):** widen the scan's error
   wrapping so a post-yield `StorageError` from the metadata/stat seam is charged,
   or document the four-source guarantee explicitly.

No candidate push, merge or deploy was performed.

## 6. Notes and limits

- This is **sandbox execution on a gVisor kernel**, not target-cloud execution;
  raw `readdir` order is emulated and controlled by the deterministic seam. Real
  kernel `readdir` order is not asserted.
- Fixtures are synthetic (<50 MiB), deterministic, local; no services, credentials
  or private paths were touched; all probes are bounded.
- The **second frontier static review has not happened**; nothing here depends on
  it, and no independent or target-cloud result is claimed.
- Reproduce: `python3.11 scripts/probe_d034.py` (and `python3.12`); mutate with
  `python3.11 scripts/mutations.py`.
