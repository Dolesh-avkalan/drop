# d007 — MODULE-003 review fixes (Sarvam)

- status: **DONE — pushed to `Dolesh-avkalan/drive-tool` on a NEW branch**
- task: implement/test the director's scoped correction for MODULE-003
- base: `Dolesh-avkalan/drive-tool` @ `110b27e81cfead478eb6e400a44043f6e14f14b7`
- branch: `feature/module-003-review-fixes`
- fixes commit: `6a7d6d4ffd58ebf66f6a5c99388000aa710e98b4`
- evidence commit: `c2b324dab4cf720178a36a58b5f1cf1339730151`
- reviewers addressed: `d005` (CHANGES REQUIRED), `d006` (independent re-test)

## 0. Verdict

Implemented and tested the director's chosen strategy in the exact permitted
scope. The directory-swap race is now **contained** on the actual kernel at every
entry point, the new committed tests **fail on the base commit**, and the full
suite passes on Python 3.11.2 and 3.12.13. Nothing outside the four permitted
paths was changed; `main` and every existing branch are untouched; no merge,
deploy, service, production file or credential was touched.

## 1. What was wrong

The base commit's fix was a `lstat`-before-`open` guard added in three places
(`_open_anchored_root`, `_traverse_parent_dir`, `list_children`). On this
gVisor/9p sandbox `O_NOFOLLOW` is ignored when combined with `O_DIRECTORY`, so
the guard was a check-then-use (TOCTOU) pair with no atomic backstop: a directory
component swapped for an outside symlink between the `lstat` and the `open` was
followed. This was reproduced deterministically (bytes read, metadata exposed,
listing leaked, root setup escaped).

## 2. Strategy implemented (director's direction)

Directory components are opened **atomically** with
`O_RDONLY | O_NOFOLLOW | O_NONBLOCK` **without `O_DIRECTORY`**; the returned
descriptor is immediately `fstat`ed and required to be `S_ISDIR`; descriptor-
relative traversal is preserved. `O_NOFOLLOW` **alone** is honoured on this
kernel (verified), so the symlink is rejected atomically at open time with no
separate check. The `lstat`-before-open guards were removed.

Validated with a raw-kernel probe (no simulation):

| raw open (this sandbox) | result |
| --- | --- |
| `open(symlink_to_dir, O_RDONLY\|O_NOFOLLOW\|O_NONBLOCK)` | ELOOP |
| `open(broken_symlink, …)` | ELOOP |
| `open(realdir, …)` + fstat | opened, `S_ISDIR` |
| `open("/", …)` + fstat | opened, `S_ISDIR` |
| `open(fifo, …)` + fstat | opened, `S_ISFIFO` (no block) |

Fail-closed gating: a runtime probe `_no_follow_semantics_available()` runs at
construction and raises `UnsupportedPlatformError` if `O_NOFOLLOW` is not
actually enforced — never claiming safety from a constant alone.

## 3. Exact edits (4 permitted paths only)

**`drive_tool/local.py`**
- `_dir_open_flags()` drops `O_DIRECTORY` (keeps `O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC`).
- Removed the three `lstat`-before-open guards.
- Added `_no_follow_semantics_available()` runtime kernel probe; `_check_platform_capabilities()` now fails closed with `UnsupportedPlatformError` on failure; `O_DIRECTORY` removed from the static required-flags list.
- Close-failure ownership: new descriptor taken into `current_fd` **before** the previous fd is released (`prev_fd = current_fd; current_fd = next_fd; close(prev_fd)`), so a failed close never retries/double-closes the same fd and the newly opened fd is still cleaned up. Helpers `_close_owned_fd` / `_close_traversal_fd` / `_close_quietly` encode "Linux releases the fd even when close errors" and "cleanup must not mask the primary error".
- OS-error wrapping with preserved `__cause__` for scandir iteration, traversal and root `fstat`, and cleanup paths.

**`tests/test_local.py`**
- `TestPlatformNoFollowSemantics` — real-kernel tests (flags exclude `O_DIRECTORY`; raw `O_NOFOLLOW` rejects a symlink; real dir opens and `S_ISDIR`; probe reports enforced; failed probe → `UnsupportedPlatformError`).
- `TestContainmentSymlinksAndAnchoredRoot` — four new directory-swap-before-open regressions (read traversal, stat traversal, `list_children` final dir, root setup/ancestor), each **asserting** `UnsafePathError`.
- `TestDescriptorLifetimeAndClose` — corrected `_TrackedScandirWrapper` to track scandir's internal dup separately; added a direct scan-descriptor-close assertion.
- `TestCloseFailureOwnership` — injected `close()` failures during traversal and root setup; assert no double-close, all fds released, cause preserved.
- `TestOsErrorWrapping` — injected `EIO`/`EACCES` in scandir iteration, traversal `fstat`, root `fstat`; assert `LocalStorageError` + cause + cleanup.

**`docs/evidence/MODULE-003.md`** — appended §8 "SUPERSEDING CORRECTION": retracts the §5.1/§6.2/§7 race-safety claim, records the implementer provenance correction (**4 Argon/high**; the "3.1 Pro" label in the generated evidence is historical and misleading, not proof of the selected model), source/base/commit, exact edits, and limits.

**`docs/evidence/MODULE-003-REVIEW-FIXES.md`** — new full evidence file.

## 4. Results (raw)

Full suite (from the repo root):

| When | Interpreter | Result | Exit |
| --- | --- | --- | --- |
| before (base `110b27e8`) | 3.11.2 | `Ran 67 tests` … `OK` | 0 |
| before (base `110b27e8`) | 3.12.13 | `Ran 67 tests` … `OK` | 0 |
| after (this branch) | 3.11.2 | `Ran 82 tests` … `OK` | 0 |
| after (this branch) | 3.12.13 | `Ran 82 tests` … `OK` | 0 |

Skips: none. (The suite already passed at base — which is exactly why passing it
is not proof of race safety.)

d006 reproducer (`race_probe.py`, print-only) on the actual kernel: base = all
three entry points **ESCAPE**; this branch = all three **contained**
(`UnsafePathError`). Because the d006 reproducer always exits 0, an **asserting**
variant `race_probe_assert.py` was added:

| checkout | 3.11.2 | 3.12.13 |
| --- | --- | --- |
| base `110b27e8` | **exit 1** (4 containment failures) | **exit 1** |
| this branch | **exit 0** (all contained) | **exit 0** |

New committed tests vs the base adapter: `FAILED (failures=6, errors=6)` on 3.11
(exit 1) and exit 1 on 3.12 — the suite detects the base behaviour.

Descriptor-accounting mutation (remove the explicit `scan_fd` close): the **base**
mock passes (leak not caught — the d005 §B3 flaw); the **fixed** mock fails
(`AssertionError: 3 != 1`), proving the test now catches it.

## 5. Push

Pushed via the authorized GitHub API (sandbox `git` has no push credentials). The
branch was created **from the exact base SHA**, then two commits were added:

- branch: https://github.com/Dolesh-avkalan/drive-tool/tree/feature/module-003-review-fixes
- fixes: https://github.com/Dolesh-avkalan/drive-tool/commit/6a7d6d4ffd58ebf66f6a5c99388000aa710e98b4
- evidence: https://github.com/Dolesh-avkalan/drive-tool/commit/c2b324dab4cf720178a36a58b5f1cf1339730151

Pushed blob SHAs were verified byte-identical to the tested working tree:

```
2f85eebf879c8c14b9945660dc65f978e3212133  drive_tool/local.py
b84b41776209342319dddb8ecd10cfb8ee129233  tests/test_local.py
565a915ce06c12dee479546084e573f94057465a  docs/evidence/MODULE-003.md
67172542b5cbe64fb33517c56b92ae03495074e3  docs/evidence/MODULE-003-REVIEW-FIXES.md
```

## 6. Limitations

- Deterministic mechanism proofs, not concurrency stress tests.
- Environment is gVisor over 9p: `O_NOFOLLOW | O_DIRECTORY` is non-conformant,
  `O_NOFOLLOW` alone is honoured. The strategy depends only on `O_NOFOLLOW` alone
  (runtime-probed); where even that is unavailable the adapter fails closed.
- Conformant-kernel (ext4) behaviour for the same swap is inferred from the
  kernel contract, not executed here.
- Interfaces, connectors and bounded-read behaviour unchanged; MODULE-001 files
  untouched.
- Director acceptance and security re-review remain pending.

## 7. Files shipped alongside this answer

In `drive-tool/module-003/d007-sarvam-review-fixes/`:

- `race_probe_assert.py` — asserting variant of the d006 reproducer (exit code is the gate).
- `run_new_tests_on_old.py` — runs the new committed tests against the base adapter.
- `raw_probe.py` — the raw-kernel open probe behind §2.
- `logs/` — `00_env.log`, `before_py311.log`, `before_py312.log`, `after_py311.log`, `after_py312.log`, `before_race_probe_py311.log`, `after_race_probe_py311.log`, `oldcode_newtests_py311.log`, `mutation_py311.log`, `oldwrap_mutant_py311.log`, `targeted_py311.log`, `targeted_py312.log`, `raw_probe.log`.
