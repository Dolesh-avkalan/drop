# MODULE-003 — Review Fixes Evidence (d007, Sarvam)

This file records the scoped correction requested by the director after the
independent reviews `d005` (security review) and `d006` (independent re-test),
and supersedes the unsupported-platform race-safety claim in
`docs/evidence/MODULE-003.md` §5.1/§6/§7. It is written by Sarvam and is
separate from both the implementer's evidence (`docs/evidence/MODULE-003-GEMINI.md`)
and the assembly evidence (`docs/evidence/MODULE-003.md`).

## 0. Status

- **TESTS_RUN** on both interpreters. All commands, exit codes and raw logs are
  recorded below and shipped alongside this report.
- The revision **contains** the directory-swap race on the actual kernel at every
  entry point (read traversal, stat traversal, `list_children` final directory,
  and root setup/ancestor traversal), and the new committed tests **fail on the
  base commit**.
- No branch other than the new `feature/module-003-review-fixes` was modified;
  no merge, deploy, service, production file or credential was touched. Only
  tiny synthetic fixtures under throwaway temp directories were used.

## 1. Source, base and provenance

| Item | Value |
| --- | --- |
| Repository | `Dolesh-avkalan/drive-tool` |
| Base commit (exact) | `110b27e81cfead478eb6e400a44043f6e14f14b7` — "Add MODULE-003 evidence report" |
| New branch | `feature/module-003-review-fixes` (branched from the base commit) |
| Brief | `tasks/MODULE-003.md` @ `b5424513796834fc8c03a56bee7b0f0f7abc1f74` |
| Reviewer inputs | `d005-argon-module003-security-review.md` (CHANGES REQUIRED), `d006-sarvam-module003-independent-tests.md`, and `race_probe.py` |
| Fixes commit | `drive_tool/local.py`, `tests/test_local.py` |
| Evidence commit | `docs/evidence/MODULE-003.md` (append), `docs/evidence/MODULE-003-REVIEW-FIXES.md` (new) |

Implementer provenance for MODULE-003 is **Gemini 4 Argon, thinking: high**. The
"Gemini 3.1 Pro" label inside `docs/evidence/MODULE-003-GEMINI.md` is historical
and misleading and is **not** proof of the selected model; see
`docs/evidence/MODULE-003.md` §8.2.

Base-commit blob hashes (match d006 exactly):

```
8e3b75cf2c0e1d60239aeb6cd38322a83ad66e4715b02882d4ec16e6f8927449  drive_tool/local.py
670a8862b1194483f12a3e38ad9678579794dcef522ec932f04aa7e982b24838  tests/test_local.py
fa49d9658e390e26df6a936db3b4542f4f4b9d5b2a6a4a6ee2f93f3e31f6a777  drive_tool/storage.py
```

## 2. Execution environment

- Platform: `Linux ... 4.19.0-gvisor` (gVisor sandbox). `/` is `overlayfs`;
  `/tmp` and `/scratch` are `9p` (`v9fs`); `/dev/shm` is `tmpfs`.
- Interpreters: **Python 3.11.2** (`/usr/bin/python3.11`) and **Python 3.12.13**
  (`/usr/local/bin/python3.12`).
- `TMPDIR=/scratch/tmp`; all fixtures are tiny synthetic directories there.

## 3. The strategy and why it is used

The director's chosen strategy: directory components are opened **atomically**
with `O_RDONLY | O_NOFOLLOW | O_NONBLOCK` **without `O_DIRECTORY`**; the returned
descriptor is immediately `fstat`ed and required to be `S_ISDIR`, with
descriptor-relative traversal preserved.

Rationale, validated against the real kernel rather than assumed from constants
(`raw_probe.log`):

| Raw open (real kernel, this sandbox) | Result |
| --- | --- |
| `open(symlink_to_dir, O_RDONLY\|O_NOFOLLOW\|O_NONBLOCK)` | **ELOOP** (symlink rejected) |
| `open(broken_symlink, O_RDONLY\|O_NOFOLLOW\|O_NONBLOCK)` | **ELOOP** |
| `open(realdir, O_RDONLY\|O_NOFOLLOW\|O_NONBLOCK)` then `fstat` | opened, `S_ISDIR=True` |
| `open("/", O_RDONLY\|O_NOFOLLOW\|O_NONBLOCK)` then `fstat` | opened, `S_ISDIR=True` |
| `open(fifo, O_RDONLY\|O_NOFOLLOW\|O_NONBLOCK)` then `fstat` | opened, `S_ISFIFO=True` (no block) |
| `open(regular_file, O_RDONLY\|O_NOFOLLOW\|O_NONBLOCK)` then `fstat` | opened, `S_ISREG=True` |

Because `O_NOFOLLOW` **alone** is honoured here, the symlink is rejected
*atomically at open time* with no separate `lstat`, so there is no check-to-use
window. `O_DIRECTORY` is deliberately not used: on this sandbox `O_NOFOLLOW` is
ignored when combined with `O_DIRECTORY` (reproduced by d006 and re-confirmed
here), which is exactly the non-conformance that made the previous
`lstat`-before-open emulation unsafe.

## 4. Exact edits

### 4.1 `drive_tool/local.py`

1. **Atomic no-follow directory opens without `O_DIRECTORY`.**
   `_dir_open_flags()` now returns `O_RDONLY | O_NOFOLLOW | O_NONBLOCK`
   (`| O_CLOEXEC`), with the rationale documented. Callers already `fstat` the
   returned descriptor and require `S_ISDIR`.
2. **Removed the three `lstat`-before-open guards** in `_open_anchored_root`,
   `_traverse_parent_dir` and `list_children`. Traversal now relies solely on the
   atomic `O_NOFOLLOW` open; there is no separate check and therefore no TOCTOU
   window. Symlink refusal, special-entry refusal and source-mismatch precedence
   are preserved.
3. **Runtime no-follow capability probe.** New module function
   `_no_follow_semantics_available()` creates a tiny throwaway directory with a
   symlink and confirms that opening the symlink with the adapter's exact
   component flags is refused (`ELOOP`/`EMLINK`) and that a real directory opens
   and `fstat`s as `S_ISDIR`. `_check_platform_capabilities()` calls it and
   raises `UnsupportedPlatformError` if it fails — **fail closed**, never claim
   safety from a constant alone. `O_DIRECTORY` was removed from the static
   required-flags list because the method no longer uses it.
4. **Close-failure ownership transfer** (`_open_anchored_root`,
   `_traverse_parent_dir`). The new descriptor is now taken into `current_fd`
   **before** the previous descriptor is released:
   `prev_fd = current_fd; current_fd = next_fd; close(prev_fd)`. If that close
   fails, the outer handler cleans up the newly opened `current_fd` and re-raises
   the wrapped failure — the failed descriptor is never retried or double-closed,
   and no orphaned descriptor is leaked. Helpers `_close_owned_fd` (wrap on the
   success path), `_close_traversal_fd` (wrap on success, suppress while
   unwinding) and `_close_quietly` (best-effort during unwinding) encode the rule
   that **Linux releases a descriptor even when `close` reports an error**.
5. **OS-error wrapping with preserved cause.** `scandir` iteration, traversal and
   root `fstat`, and the relevant cleanup paths now raise `LocalStorageError`
   with useful context and `__cause__` preserved. Cleanup never masks the primary
   error: a close that fails while another exception is propagating is
   suppressed.

### 4.2 `tests/test_local.py`

- `TestPlatformNoFollowSemantics` — real-kernel tests: `_dir_open_flags()`
  excludes `O_DIRECTORY`; a raw `O_NOFOLLOW` open rejects a symlink; a real
  directory opens and `fstat`s as `S_ISDIR`; the runtime probe reports enforced
  no-follow; a failing probe yields `UnsupportedPlatformError`.
- `TestContainmentSymlinksAndAnchoredRoot` — added
  `test_dir_swap_before_component_open_read_traversal_rejected`,
  `..._stat_traversal_rejected`, `test_dir_swap_before_list_children_final_open_rejected`
  and `test_dir_swap_before_ancestor_open_rejected_at_root_setup`. Each forces a
  directory component to be swapped for an outside symlink *immediately before*
  its atomic open and **asserts** `UnsafePathError` (failing if outside content is
  returned).
- `TestDescriptorLifetimeAndClose` — corrected `_TrackedScandirWrapper` so it
  tracks scandir's **internal duplicate** as a distinct token and retires only
  that token on `__exit__`; the caller's `scan_fd` stays accounted for until the
  adapter explicitly closes it. Added
  `test_list_children_closes_the_scan_descriptor` which spies the adapter seam.
- `TestCloseFailureOwnership` — injected `close()` failures during traversal and
  root setup: assert `LocalStorageError` with `OSError.__cause__`, **no
  double-close**, and that every opened descriptor is released exactly once.
- `TestOsErrorWrapping` — injected `EIO`/`EACCES` in scandir iteration, traversal
  `fstat` and root `fstat`: assert `LocalStorageError` with preserved cause and
  descriptor cleanup.

## 5. Raw results

### 5.1 Full suite — before and after

Commands (from the repository root):

```
python3.11 -m unittest discover -s tests -v
python3.12 -m unittest discover -s tests -v
```

| When | Interpreter | Result | Exit |
| --- | --- | --- | --- |
| Before (base `110b27e8`) | 3.11.2 | `Ran 67 tests` … `OK` | 0 |
| Before (base `110b27e8`) | 3.12.13 | `Ran 67 tests` … `OK` | 0 |
| After (this branch) | 3.11.2 | `Ran 82 tests` … `OK` | 0 |
| After (this branch) | 3.12.13 | `Ran 82 tests` … `OK` | 0 |

The suite passes at the base commit (as d006 already showed) — which is precisely
why passing the suite is **not** evidence of race safety. Skips: none.

### 5.2 d006 reproducer on the actual kernel — before vs after

`race_probe.py` (the d006 reproducer, print-only) against the base commit shows
all three entry points **ESCAPE** (outside sentinel bytes read, outside metadata
exposed, outside listing exposed). Against this branch it shows all three
**contained** with `UnsafePathError`.

Because the d006 reproducer is print-only and always exits `0`, it is not a
pass/fail gate. The asserting variant `race_probe_assert.py` is:

```
PYTHONPATH=<checkout> python3.11 race_probe_assert.py   # also python3.12
```

| Checkout | Interpreter | Result | Exit |
| --- | --- | --- | --- |
| Base `110b27e8` | 3.11.2 | `RESULT: FAIL - 4 containment failure(s)` (bytes/metadata/listing/root escaped) | **1** |
| Base `110b27e8` | 3.12.13 | `RESULT: FAIL` | **1** |
| This branch | 3.11.2 | `RESULT: PASS - all entry points contained the directory swap` | **0** |
| This branch | 3.12.13 | `RESULT: PASS` | **0** |

### 5.3 New committed tests fail on the base commit

Running the new `tests/test_local.py` against the base `drive_tool/local.py`
(with a minimal shim supplying the two helper names the old module predates):

```
python3.11 run_new_tests_on_old.py   # -> FAILED (failures=6, errors=6), exit 1
python3.12 run_new_tests_on_old.py   # -> exit 1
```

The 3 directory-swap-before-open tests and the platform-semantics tests **FAIL**;
the close-failure and OS-error-wrapping tests **ERROR** — i.e. the suite detects
the base behaviour. This is the "tests assert outcomes and fail on the old
commit" requirement.

### 5.4 Descriptor-accounting mock catches the leak (mutation)

The base mock discarded the passed fd on `__exit__`, hiding the leak d005 §B3
described. Mutating the adapter to remove the explicit `scan_fd` close and
running the two descriptor tests:

| Mock used | Mutant adapter | Result |
| --- | --- | --- |
| Base (discards passed fd) | no explicit `scan_fd` close | **OK** (leak NOT caught) |
| Fixed (tracks scandir dup) | no explicit `scan_fd` close | `FAILED` — `AssertionError: 3 != 1` and `AssertionError: <fd> not found` |

## 6. Limits and residual risk

- This is a deterministic **mechanism** proof, not a concurrency stress test.
- The environment is gVisor over 9p: `O_NOFOLLOW | O_DIRECTORY` is
  non-conformant here while `O_NOFOLLOW` alone is honoured. The revised strategy
  depends only on `O_NOFOLLOW` alone, verified by a runtime probe; on a platform
  where even that is unavailable the adapter fails closed with
  `UnsupportedPlatformError`.
- Conformant-kernel (e.g. ext4) behaviour for the same swap is inferred from the
  documented kernel contract, not executed in this sandbox.
- Unchanged documented boundaries still hold: concurrent external writers may
  change file contents mid-read (bounded bytes only, no snapshot/checksum); hard
  links, bind mounts/submounts, procfs/sysfs and adversarial root provisioning
  are operator responsibilities. No production security completeness is claimed.
- Interfaces, connectors and bounded-read behaviour are unchanged; MODULE-001
  files are untouched.
- Director acceptance and security re-review remain pending.

## 7. Files shipped with this report

In `drive-tool/module-003/d007-sarvam-review-fixes/` (relay repository):

- `race_probe_assert.py` — asserting variant of the d006 reproducer (exit code
  is the gate).
- `run_new_tests_on_old.py` — runs the new committed tests against the base
  adapter (with the minimal helper shim).
- `raw_probe.py` — the raw-kernel open probe behind §3.
- `logs/` — `00_env.log`, `before_py311.log`, `before_py312.log`,
  `after_py311.log`, `after_py312.log`, `before_race_probe_py311.log`,
  `after_race_probe_py311.log`, `oldcode_newtests_py311.log`,
  `mutation_py311.log`, `oldwrap_mutant_py311.log`, `targeted_py311.log`,
  `targeted_py312.log`, `raw_probe.log`.
