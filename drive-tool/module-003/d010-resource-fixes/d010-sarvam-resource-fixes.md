# d010 — minimal MODULE-003 resource ownership and probe fixes (Sarvam)

Director: Codex. Implementer/test executor: browser Sarvam.
Brief: `tasks/d010-module003-resource-fixes.md`, dispatched after d009.

```
STATUS:      TESTS_RUN (PUSH_BLOCKED for delivery)
BRANCH:      feature/module-003-resource-fixes  (intended; not pushed)
COMMIT:      NOT_PUSHED  (base c2b324dab4cf720178a36a58b5f1cf1339730151)
TESTS:       python3.11/3.12 -m unittest discover -s tests -v  ->  Ran 89 tests ... OK  (exit 0)
DELIVERABLES: drive_tool/local.py, tests/test_local.py,
              docs/evidence/MODULE-003-RESOURCE-FIXES.md (+ raw logs, patch)
LIMITATIONS:  gVisor/9p kernel; no push; deterministic mechanism evidence only
```

## 1. Provenance and scope

- Base (exact): `c2b324dab4cf720178a36a58b5f1cf1339730151` in
  `Dolesh-avkalan/drive-tool` (branch `feature/module-003-review-fixes`).
- Intended new branch: `feature/module-003-resource-fixes` (branched from base).
- Only allowed paths changed (verified): `drive_tool/local.py`,
  `tests/test_local.py`, and the new `docs/evidence/MODULE-003-RESOURCE-FIXES.md`.
  No `main` or existing feature branch touched; no merge, deploy, interface,
  dependency or MODULE-001/002 change.
- Gemini d008's review was used as a defect list; its illustrative code was not
  copied.

## 2. Environment

- Kernel `Linux ... 4.19.0-gvisor`; `/` overlay, `/scratch` and `/tmp` 9p
  (`v9fs`); `TMPDIR=/scratch/tmp`.
- Interpreters: Python 3.11.2 (`/usr/bin/python3.11`), 3.12.13
  (`/usr/local/bin/python3.12`). Both available; neither missing.
- Synthetic fixtures only; all experiments in throwaway trees.

## 3. What changed

**Fix 1 — child descriptor ownership across the parent-close handoff.**
`read_bytes` and `list_children` now build an explicit `owned` descriptor list
and release it via one helper `_release_owned` in a single `finally`, so a
failing parent close after child acquisition can no longer skip the child's
cleanup scope. `_release_owned` closes each descriptor exactly once, never
retries an ambiguous close, attempts every descriptor even if an earlier close
failed, preserves the original `OSError` cause on the success path, and
suppresses close failures while another exception propagates. Root ownership is
unchanged; no unrelated traversal code was rewritten.

**Fix 2 — runtime probe uses production flags.**
`_no_follow_semantics_available()` now calls `_dir_open_flags()` (the production
helper) instead of a reconstructed bitmask, and the result is never cached.
File and directory flags remain identical and both exclude `O_DIRECTORY`.

**Fix 3 — static prerequisites split from the runtime probe in tests.**
`_PosixStaticTestCase` gates on static POSIX facilities only (probe/denial tests
derive from it and always run); `_PosixRuntimeTestCase` additionally skips
operational tests when the runtime probe reports no-follow not enforced, with a
precise reason. The self-fulfilling gate (probe tests skipped by the result they
test) is removed; probe tests assert kernel/probe agreement or fail-closed
behaviour instead of a hard-coded `True`.

## 4. Regressions (added before/with the fix)

`TestChildDescriptorOwnershipHandoff` reproduces the base leak for
`read_bytes p/a/file.txt`, `read_bytes p/a/b/file.txt`, `list_children p/a/b`,
`list_children p/a/b/c` (parent-handoff close failed after child acquisition),
plus an earlier-traversal-close case. Descriptors are identified by acquisition
(unique tokens; closes pop the most-recent token per fd number — LIFO), so the
checks are correct under fd-number reuse. Assertions: child released exactly
once; original failure/cause preserved; no double close; nothing left open;
parent released once; root still usable.

## 5. Raw results (see logs/)

Full committed suite:

| Tree | 3.11.2 | 3.12.13 |
| --- | --- | --- |
| fixed (this work) | `Ran 89` `OK` exit 0 | `Ran 89` `OK` exit 0 |
| base + new tests | `Ran 89` `FAILED (failures=5)` exit 1 | `Ran 89` `FAILED (failures=5)` exit 1 |

The 5 base failures: the 4 handoff regressions (e.g. `child descriptor lifetime
must be released exactly once (got 0)`) and
`test_probe_follows_production_dir_flags` (`True is not false`). No skips on this
kernel. 89 = 53 `test_local` + 36 `test_storage` (base was 82).

Targeted mutations (throwaway copies, `test_local.py` only):

| Mutation | Caught by |
| --- | --- |
| M1 remove new child cleanup | `FAILED (failures=8)`: 4 handoff regressions + 4 existing descriptor tests |
| M2 decouple probe from production flags | `FAILED (failures=1)`: `test_probe_follows_production_dir_flags` |

Cross-check: the independent d009 probes (`containment_assert`,
`bounded_read_checks`, `root_rename_anchor`, `fifo_timeout`, `fd_cleanup`) all
exit 0 against this fixed tree — including `fd_cleanup`'s parent-close path,
which failed against the base revision.

## 6. Blob hashes (git blob = sha1 of `blob <len>\0<content>`)

```
file                                      base c2b324da                      fixed
drive_tool/local.py                       2f85eebf879c8c14b9945660dc65f978e3212133  5da22dd42d27746b9840ed00495568ea468754a3
tests/test_local.py                       b84b41776209342319dddb8ecd10cfb8ee129233  b3319752edaf92a02993981fcc62d63f63ebb408
docs/evidence/MODULE-003-RESOURCE-FIXES.md  (absent)                          2da73028ce87d06cb0cdb79509b98314124ac2f7
```

## 7. Delivery (PUSH_BLOCKED)

The executing worker had no GitHub write connector, so nothing was pushed.
Artifacts are delivered as files: the three repo files at their branch paths, a
unified patch (`d010-fix.patch`), raw logs, and this report. Target relay
location once a connector is available:
`Dolesh-avkalan/drop` → `drive-tool/module-003/d010-resource-fixes/`.

## 8. Limits

- gVisor/9p: conformant-kernel (e.g. ext4) behaviour is inferred, not executed.
- Ownership-transfer tests inject close errors after a real close; truly
  ambiguous close is documented, not claimed.
- Deterministic mechanism evidence, not a concurrency stress test. Existing
  documented boundaries unchanged. No production security completeness claimed.
- No merge or deployment; director acceptance and a fresh independent re-review
  gate remain.
