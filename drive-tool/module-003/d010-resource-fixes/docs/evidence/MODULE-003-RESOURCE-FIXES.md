# MODULE-003 — Resource Ownership and Probe Fixes (d010, Sarvam)

Director: Codex. Implementer/test executor: browser Sarvam.
Brief: `tasks/d010-module003-resource-fixes.md` (dispatched after d009).
Review input: Gemini d008 static review (CHANGES REQUIRED); its proposed code was
treated as illustrative, not copied.

## 0. Status

- **TESTS_RUN** on Python 3.11.2 and 3.12.13.
- **PUSH_BLOCKED** — the executing worker had no GitHub write connector at run
  time, so no branch was pushed. Artifacts are delivered as files (see §8).
- Base: `c2b324dab4cf720178a36a58b5f1cf1339730151`.
- Intended branch: `feature/module-003-resource-fixes`. No merge; no changes to
  `main` or any existing feature branch.
- Allowed paths touched only: `drive_tool/local.py`, `tests/test_local.py`, and
  this new file. No MODULE-001/002 edits, interfaces, dependencies, caching
  frameworks, installs or deployment. Synthetic fixtures only.

## 1. Blob hashes

git blob hash = sha1 of `blob <len>\0<content>`.

```
file                     base c2b324da                     fixed (this work)
drive_tool/local.py      2f85eebf879c8c14b9945660dc65f978e3212133  5da22dd42d27746b9840ed00495568ea468754a3
tests/test_local.py      b84b41776209342319dddb8ecd10cfb8ee129233  b3319752edaf92a02993981fcc62d63f63ebb408
```

## 2. Fix 1 — child descriptor ownership across the parent-close handoff

**Problem.** In `read_bytes` and `list_children` the parent directory descriptor
was closed in a `finally` that runs *after* the child file/scan descriptor has
been acquired. If that close raised, the exception propagated before the child's
own cleanup scope began, orphaning the child descriptor.

**Fix.** A descriptor is treated as owned the moment it is acquired. Both
methods now build an explicit `owned` list and release it through one helper,
`_release_owned`, in a single `finally`:

- `read_bytes`: `owned = [parent?, file]`; the read and the child release share
  one scope, so a failing parent close can no longer skip the child.
- `list_children`: `owned = [parent?, scan]`; acquisition, the `fstat`/type
  check, `scandir`, iteration and release are inside one `try`/`finally`.

`_release_owned` closes each descriptor **exactly once**, in order, and:

- never retries a close (Linux releases the fd even when `close` reports an
  error; a truly ambiguous close cannot be verified and is not retried);
- attempts every descriptor even if an earlier close failed, so the child is
  still released when the parent close fails;
- on the success path raises the first close failure as `LocalStorageError` with
  its `OSError` cause preserved;
- while another exception is already propagating, suppresses close failures so
  the primary storage error is never masked.

Root descriptor ownership is unchanged (the root fd is never in `owned`), and no
unrelated traversal code was rewritten.

**Close-error semantics modelled.** Ownership-transfer tests inject an error
*after* the real `close` (the fd is released, then the error is reported) — the
common Linux case. Ambiguous-close behaviour is documented: the module does not
retry and does not claim to have released a descriptor whose close truly failed;
it treats the descriptor as released and moves on.

## 3. Fix 2 — the runtime probe uses the production flags

`_no_follow_semantics_available()` previously reconstructed the open flags
inline. It now calls the production helper `_dir_open_flags()` directly, so the
probe cannot drift from real adapter behaviour, and the result is never cached.
`_file_open_flags()` and `_dir_open_flags()` remain identical and both exclude
`O_DIRECTORY`, include `O_NOFOLLOW` and `O_NONBLOCK`; this shared-safety property
is asserted explicitly. No `O_DIRECTORY`-based weakening, `lstat`-then-open
fallback, or cached success was added.

## 4. Fix 3 — static prerequisites split from runtime probe in tests

Previously `_PosixTempRootTestCase.setUp` skipped every subclass when the
*runtime* probe returned False, so the probe/denial tests were skipped by the
result they test (a self-fulfilling gate).

Now:

- `_static_posix_prerequisites_met()` checks only static POSIX facilities;
- `_PosixStaticTestCase` gates on static prerequisites only — the probe and
  platform-denial tests derive from it and therefore always run;
- `_PosixRuntimeTestCase` (and the operational alias `_PosixTempRootTestCase`)
  additionally skip when the runtime probe reports O_NOFOLLOW not enforced, with
  a precise reason. An unsupported kernel is a legitimate fail-closed outcome,
  not a product defect.

The probe tests were corrected:

- `test_real_kernel_rejects_symlink_with_component_flags` — runs always; asserts
  the kernel rejects with ELOOP/EMLINK *if* the probe reports enforced, else
  asserts the adapter fails closed with `UnsupportedPlatformError` (never an
  unconditional failure on a correctly rejected platform).
- `test_runtime_probe_matches_raw_kernel_nofollow` — asserts the probe agrees
  with the raw kernel, rather than asserting a hard-coded `True`.
- `test_probe_follows_production_dir_flags` — weakening `_dir_open_flags` (drop
  `O_NOFOLLOW`) must make the probe report following and the constructor fail
  closed.
- `test_file_and_dir_open_flags_share_safe_flags` — file/dir flags equal and
  safe.

## 5. New regressions — child ownership handoff

`TestChildDescriptorOwnershipHandoff` reproduces the base leak and asserts the
fix, for `read_bytes` on `p/a/file.txt` and `p/a/b/file.txt`, and
`list_children` on `p/a/b` and `p/a/b/c`. The parent-handoff close is failed
after the child is acquired; a separate test fails an earlier traversal close.

Descriptors are identified by **acquisition**, not by fd number: each open gets
a unique token and each close pops the most-recent token for that fd number
(LIFO, matching the kernel), so the checks are correct even when the kernel
reuses a freed fd number. Assertions: every acquired child released exactly
once; original failure/cause preserved (`LocalStorageError` with `OSError`
cause); no descriptor closed without a matching acquisition (no double close);
nothing left open; parent released exactly once; root still usable afterwards.

## 6. Raw results

Environment: `Linux ... 4.19.0-gvisor`; `/` overlay, `/scratch` and `/tmp` 9p
(`v9fs`); Python 3.11.2 and 3.12.13; `TMPDIR=/scratch/tmp`.

Full committed suite (`python3.11/3.12 -m unittest discover -s tests -v`):

| Tree | Interpreter | Result | Exit |
| --- | --- | --- | --- |
| fixed (this work) | 3.11.2 | `Ran 89 tests` … `OK` | 0 |
| fixed (this work) | 3.12.13 | `Ran 89 tests` … `OK` | 0 |
| base `c2b324da` + new tests | 3.11.2 | `Ran 89 tests` … `FAILED (failures=5)` | 1 |
| base `c2b324da` + new tests | 3.12.13 | `Ran 89 tests` … `FAILED (failures=5)` | 1 |

The 5 base failures are exactly the 4 handoff regressions plus
`test_probe_follows_production_dir_flags`. No tests were skipped on this kernel;
89 = 53 in `test_local` + 36 in `test_storage` (base was 82).

Targeted mutations (throwaway copies; `test_local.py` only):

| Mutation | Result |
| --- | --- |
| M1 remove new child cleanup | `FAILED (failures=8)` — the 4 handoff regressions plus 4 existing descriptor tests |
| M2 decouple probe from production flags | `FAILED (failures=1)` — `test_probe_follows_production_dir_flags` |

Cross-check with the independent d009 probes run against this fixed tree:
`containment_assert.py`, `bounded_read_checks.py`, `root_rename_anchor.py`,
`fifo_timeout.py` and `fd_cleanup.py` all exit 0 — including the d009
`fd_cleanup` parent-close path, which failed against the base revision. (d009
evidence is separate from this module's.)

## 7. Limits

- gVisor/9p environment; conformant-kernel (e.g. ext4) behaviour is inferred,
  not executed. The containment strategy still depends only on `O_NOFOLLOW`
  being honoured (verified by the runtime probe, fail-closed otherwise).
- Ownership-transfer tests inject close errors after a real close; a truly
  ambiguous close (fd not actually released) is documented, not claimed.
- Deterministic mechanism evidence, not a concurrency stress test. Documented
  boundaries (concurrent external writers, hard links, mounts, adversarial root
  provisioning) are unchanged. No production security completeness is claimed.
- No merge or deployment. Director acceptance and an independent re-review gate
  remain.

## 8. Files

`drive_tool/local.py`, `tests/test_local.py`, and this evidence file. Raw logs
and the check scripts are shipped separately (see the d010 delivery).
