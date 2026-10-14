# d012 — fresh independent execution of the d010 candidate (Sarvam)

Worker: browser Sarvam, fresh context, execution/review only.
Director: Codex. Brief: `tasks/d012-module003-final-independent-tests.md` (from `main`).
No implementation, branch, merge, deploy, install or storage/credential access was performed.

## 0. Status

- **TESTS_RUN** on Python **3.11.2** and **3.12.13** (both interpreters present and used).
- **PUSH_BLOCKED** — no GitHub write connector is bound to this worker (only the
  read-only public repo fetcher is exposed; `gh` is unauthenticated). Nothing was
  written to `Dolesh-avkalan/drop` or to any drive-tool branch. A GitHub connector
  was surfaced for the user to enable on a later turn. Complete artifacts are
  delivered as a downloadable zip + this report via the file-artifact UI.
- Independent verdict: the d010 candidate **reproduces and holds** — every d012
  fresh check passes on the candidate and the intended regressions fail on the
  base `c2b324d`. The prior implementer's "89 passing tests" is independently
  confirmed. Conformant cloud-kernel execution and integrated MODULE-002 tests
  remain later gates (not executed here).

## 1. Exact revisions, branch and hashes

| Item | Value |
| --- | --- |
| Candidate commit | `80bf54885877c475d2ac59ddb3e9f96384600b9e` |
| Candidate branch | `feature/module-003-resource-fixes` |
| Base commit | `c2b324dab4cf720178a36a58b5f1cf1339730151` |
| `main` commit (brief source) | `440d0f697c2c2ff176ad991279b1a3e399c42f93` |

git blob hashes (sha1 of `blob <len>\0<content>`), computed in this run:

| file | base c2b324da | candidate 80bf5488 |
| --- | --- | --- |
| `drive_tool/local.py` | `2f85eebf879c8c14b9945660dc65f978e3212133` | `5da22dd42d27746b9840ed00495568ea468754a3` |
| `tests/test_local.py` | `b84b41776209342319dddb8ecd10cfb8ee129233` | `b3319752edaf92a02993981fcc62d63f63ebb408` |
| `docs/evidence/MODULE-003-RESOURCE-FIXES.md` | (absent) | `2da73028ce87d06cb0cdb79509b98314124ac2f7` |

The two candidate source blob identities match the brief exactly
(`local.py 5da22dd4…`, `test_local.py b3319752…`).

**Delta verified independently.** A recursive tree diff of the candidate against
the base shows exactly three differences: `drive_tool/local.py`,
`tests/test_local.py`, and the new `docs/evidence/MODULE-003-RESOURCE-FIXES.md`.
`drive_tool/storage.py` (`28f7b8c0…`) and `drive_tool/__init__.py` (`9be841b5…`)
are byte-identical between base and candidate, so no MODULE-001 interface blob
changed.

Cross-check: the d010 delivery in `Dolesh-avkalan/drop` (`…/d010-resource-fixes/`)
carries `drive_tool/local.py` and `tests/test_local.py` whose blob hashes are
**identical** to the candidate blobs, and the same evidence file
(`2da73028…`). The drop delivery corresponds to this exact candidate.

## 2. Environment

- Kernel: `Linux 4.19.0-gvisor x86_64` (gVisor; emulated syscalls).
- Distro: Debian GNU/Linux 12 (bookworm); no `sudo`; `apt` unsupported.
- Filesystems: `/` overlay; `/tmp` and `/scratch` **9p (v9fs)**,
  `cache=remote_revalidating,disable_fifo_open,directfs`; `TMPDIR=/scratch/tmp`.
- Interpreters: `Python 3.11.2` and `Python 3.12.13` — both available, both used.
- Raw no-follow semantics on this kernel: `O_NOFOLLOW` alone rejects a symlink
  with `ELOOP`; `O_NOFOLLOW | O_DIRECTORY` **follows** it. This is the
  non-conformance the module's O_DIRECTORY-free strategy depends on, reproduced
  here independently.

## 3. Committed suite (full unittest discovery)

Command: `python3.X -m unittest discover -s tests -v` (in the checkout).

| Tree | Interpreter | Result | Exit | Skips |
| --- | --- | --- | --- | --- |
| candidate | 3.11.2 | `Ran 89 tests … OK` | 0 | 0 |
| candidate | 3.12.13 | `Ran 89 tests … OK` | 0 | 0 |
| base (its own tests) | 3.11.2 | `Ran 82 tests … OK` | 0 | 0 |
| base (its own tests) | 3.12.13 | `Ran 82 tests … OK` | 0 | 0 |

89 = 53 in `test_local` + 36 in `test_storage`; no tests skipped on this kernel
(the FIFO/socket tests executed). **The prior "89 passing" report is
independently confirmed, not merely repeated.**

New tests run against the **base implementation** (candidate `tests/` + base
`drive_tool/`): `Ran 89 tests … FAILED (failures=5)`, exit 1, on both
interpreters. The five failures are exactly the four
`TestChildDescriptorOwnershipHandoff` regressions plus
`test_probe_follows_production_dir_flags` — independently reproducing the d010
claim. Full output: `logs/newtests_on_base_python3.11.txt`,
`logs/newtests_on_base_python3.12.txt`.

## 4. Fresh ownership check (primary; fresh provenance)

Script: `scripts/d012_ownership_check.py` (written from scratch for d012; it
does **not** reuse the d010 or d009 test code).

**Design.** The check subclasses `LocalAdapter` and overrides its OS seams so
every descriptor returned by `_os_open` becomes a **virtual descriptor id** — a
unique, never-reused integer mapped to the real OS fd. This is deliberate:
kernel fd *numbers* are reused, so an integer is not a lifetime identity. With
virtual ids, "released exactly once" and "never retried" are exact.

Close-error injection models real Linux semantics:
- `after_real` — perform the real `close` (the fd **is** released), then report
  an error (the common Linux case);
- `ambiguous` — report an error **without** releasing the fd (the fd may or may
  not be released; the module must not retry and must not claim release).

**Scenarios exercised (11):** parent-close failure after child acquisition for
`read_bytes` on `p/a/file.txt` (shallow) and `p/a/b/file.txt` (deep), and for
`list_children` on `p/a/b` (shallow) and `p/a/b/c` (deep); **multiple** close
failures (parent + child); an **earlier traversal** close failure; a **primary
read failure** and a **primary scandir failure** combined with close errors; and
two **ambiguous** close cases (child, and parent handoff).

**Assertions (per scenario):** every descriptor acquired during the operation is
released exactly once; the child descriptor is released exactly once; no
double-close and no close-without-acquisition; the parent (when present) is
released exactly once and never retried; the root descriptor stays owned and the
adapter remains usable afterwards; a primary failure is preserved as
`LocalStorageError` with its `OSError` cause; on the success path with injected
close errors the first close failure is raised as `LocalStorageError` preserving
its `OSError` cause; an ambiguous close is attempted exactly once and never
claimed released.

**Results**

| Tree | Result | Exit |
| --- | --- | --- |
| candidate | `11 passed, 0 failed` | 0 |
| base `c2b324d` | `2 passed, 9 failed` (child orphaned on the handoff scenarios) | 1 |
| mutant M1 (drop the new child cleanup in `read_bytes`) | `5 passed, 6 failed` | 1 |

This satisfies the required demonstration: **the child-handoff check fails on
`c2b324d` and passes on the candidate**, and M1 shows the check has teeth beyond
"the base is old". Full logs: `logs/ownership_candidate.txt`,
`logs/ownership_base.txt`, `logs/mutation_m1_ownership.txt`.

**Ambiguous-close honesty.** In the ambiguous cases the module called `close`
exactly once (no retry) and did **not** claim release; the injected real fd
remained open, which the log records explicitly. A truly ambiguous close (fd not
actually released) cannot be verified from user space — the module documents this
rather than claiming a release it cannot prove.

## 5. Probe coupling and platform-denial gating

Script: `scripts/d012_probe_coupling.py`.

**Part A — the runtime probe uses the production flags.**
- `_dir_open_flags()` and `_file_open_flags()` are identical and both carry
  `O_NOFOLLOW` + `O_NONBLOCK` and **exclude** `O_DIRECTORY` (shared safety).
- Weakening `_dir_open_flags` (drop `O_NOFOLLOW`) makes the probe report
  "following" and the constructor fail closed with `UnsupportedPlatformError`.
- **Strong coupling assertion:** marking the helper's return with a
  behaviour-neutral bit (`O_NOCTTY`) and spying on `os.open`, the probe's own
  opens must carry that marker. On the candidate the probe opens are
  `0xa0900` (marker present → coupled); on the base they are `0xa0800` (marker
  absent → the base probe reconstructs its flags inline and is **decoupled**).
  A mutant M2 (probe reconstructs flags, ignoring the helper) yields probe opens
  `[]` and is caught. This closes a gap: an earlier, weaker version of the check
  passed M2 by coincidence (a decoupled probe that is always False); the strong
  marker assertion does not.
- The probe result is not cached (restoring the helper restores the true result).

**Part B — denial tests execute when static facilities exist but the runtime
probe is False.** With static POSIX prerequisites present and the probe forced
False:
- `TestPlatformCapabilityGate`: ran 6, skipped 0.
- `TestPlatformNoFollowSemantics`: ran 7, skipped 0 (not skipped by the result it
  tests — the self-fulfilling gate is gone).
- An operational class (`TestConfigurationAndRootValidation`): ran 5, **skipped
  5** with the precise reason "adapter unsupported on this kernel: O_NOFOLLOW is
  not enforced (runtime probe returned False)…".
- Whole suite with the probe forced False: 89 ran, **40 skipped**, 1 failure.

**The single failure is expected and explained:** forcing the probe False on a
kernel that *actually* enforces O_NOFOLLOW makes
`test_runtime_probe_matches_raw_kernel_nofollow` detect the (physically false)
disagreement, because that test deliberately compares the probe against the real
kernel. On a genuinely unsupported kernel it would pass. It is the **only**
permitted failure and is a property of the simulation, not of the product.

Results: candidate **PASS** (exit 0); base **FAIL** (probe decoupled, exit 1);
M2 **FAIL** (exit 1). Logs: `logs/probe_candidate.txt`, `logs/probe_base.txt`,
`logs/mutation_m2_probe.txt`.

## 6. Operational containment checks (fresh fixtures)

Script: `scripts/d012_operational.py` — tiny synthetic fixtures, independent of
the committed tests.

| Check | Result |
| --- | --- |
| final symlink → outside file rejected by `stat` / `read_bytes` (`UnsafePathError`) | PASS |
| final dir-symlink rejected by `list_children` | PASS |
| intermediate symlink → outside dir rejected by `stat` | PASS |
| listing omits symlinks | PASS |
| root renamed, old path replaced by outside symlink: `read` stays in original dir | PASS |
| root anchoring: `list` stays in original dir | PASS |
| bounded read below / exact / above `max_read_bytes` | PASS / PASS / PASS |
| growth after `fstat` (fstat lies "5", real file 100, limit 10) rejected; read bounded to `max+1` (=11 bytes) | PASS |
| FIFO read rejected without blocking (timeout-bounded child process) | PASS |
| listing omits FIFO | PASS |
| no fd leak across 200 op cycles (success + failure) | PASS |

Result: **15 passed, 0 failed** on the candidate — and identically on the base
(these behaviours were already correct at `c2b324d`; the d010 fix targets the
ownership handoff, not containment). Logs:
`logs/operational_candidate.txt`, `logs/operational_base.txt`.

## 7. Secondary cross-check with the d009 scripts

The d009 scripts were retrieved from `Dolesh-avkalan/drop`
(`drive-tool/module-003/d009-independent-tests/scripts/`). Run against the
candidate with `PYTHONPATH=<candidate>`, both interpreters:

| script | candidate 3.11 | candidate 3.12 |
| --- | --- | --- |
| `raw_nofollow_probe.py` | exit 0 | exit 0 |
| `containment_assert.py` | exit 0 | exit 0 |
| `bounded_read_checks.py` | exit 0 | exit 0 |
| `root_rename_anchor.py` | exit 0 | exit 0 |
| `fifo_timeout.py` | exit 0 | exit 0 |
| `fd_cleanup.py` | exit 0 | exit 0 |

Against the **base**, d009 `fd_cleanup.py` exits 1, failing
`partB-read-child-released-exactly-once` and
`partB-list-child-released-exactly-once` — the child is orphaned when the parent
close errors, independently confirming the d010 bug with an external tool.
(`d009 diff_check.py` was not run: its expected-change set is for the d007
revisions, not the d010 delta.) The d009 scripts are a **secondary** cross-check;
the primary evidence is the fresh d012 check in §4.

## 8. Consolidated battery

`logs/battery.log` records environment, both committed suites, new-tests-on-base,
all three d012 checks against candidate/base/mutants, and the d009 cross-check,
with outputs and exit codes. Everything is internally consistent: the candidate
passes every fresh check; the base fails exactly the handoff and probe-coupling
checks; the mutants are caught.

## 9. Limits and honest notes

- Environment is gVisor/9p. Conformant-kernel (e.g. ext4) behaviour is
  **inferred, not executed**. The containment strategy depends only on
  `O_NOFOLLOW` being honoured, verified by the runtime probe (fail-closed
  otherwise).
- Ownership-transfer tests inject close errors **after** a real close (the common
  Linux case). A truly ambiguous close is documented, not claimed.
- Deterministic mechanism evidence, not a concurrency stress test. Documented
  boundaries (concurrent external writers, hard links, mounts, adversarial root
  provisioning) are unchanged. No production-security completeness is claimed.
- In `logs/battery.log` §D the printed `EXIT` for the piped `newtests-on-base`
  runs reflects the pipeline, not the runner; the authoritative exit is in
  `logs/newtests_on_base_python3.1X.txt` (EXIT=1, failures=5).
- No merge, deploy or push. Director acceptance and a fresh independent
  re-review remain. Conformant cloud-kernel tests and integrated MODULE-002
  tests are later gates.

## 10. Deliverables (manifest)

All paths are relative to `drive-tool/module-003/d012-independent-tests/` for the
intended `Dolesh-avkalan/drop` layout (not pushed — see §0).

| file | sha256 |
| --- | --- |
| `d012-sarvam-independent-tests.md` (this report) | see `MANIFEST.md` |
| `scripts/d012_ownership_check.py` | see `MANIFEST.md` |
| `scripts/d012_probe_coupling.py` | see `MANIFEST.md` |
| `scripts/d012_operational.py` | see `MANIFEST.md` |
| `logs/*` | see `MANIFEST.md` |

`MANIFEST.md` lists every file, its size and its sha256.
