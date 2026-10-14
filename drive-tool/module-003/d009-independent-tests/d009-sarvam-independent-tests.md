# d009 — fresh independent tests of MODULE-003 correction (Sarvam)

Director: Codex. Worker: browser Sarvam, fresh independent test context.
Task brief: `tasks/d009-module003-independent-tests.md` @ main
`bb7c967b3e610d82eb0af7ff49e911f8a5eaf307`.

## 0. Status

- **TESTS_RUN** on both interpreters (3.11.2 and 3.12.13), all commands below.
- **PUSH_BLOCKED** — this worker has no GitHub write connector. `gh` is
  unauthenticated and the only GitHub capability exposed is a read-only repo
  fetcher; there is no way to write to `Dolesh-avkalan/drop`. All artifacts are
  delivered as files instead (see §9). No evidence is invented; nothing was
  written to any `drive-tool` branch or to `main`.
- The d007 correction is **independently confirmed** for the containment fix:
  on this sandbox's kernel the old revision escapes a directory→symlink swap at
  every entry point and the revised revision contains it (old-fail / new-pass,
  §4). The d007 test counts, blob-hash claims and "new tests fail on old"
  claim also reproduce (§3, §8).
- **One new, independent finding**: a descriptor-ownership gap on a path the
  d007 tests do not cover — when the parent-directory `close()` reports an error
  *after* the child file/scan descriptor has been acquired, the child descriptor
  is **orphaned** (not released). See §7. This is a minor correctness gap, not a
  containment escape.
- Scope respected: disposable synthetic fixtures in this sandbox only; no real
  PC/VPS/cloud-box access, services, production roots, OAuth, credentials,
  network downloads of user data, package installation, or implementation
  changes. Standard library only. Tests kept outside the checkout where
  practical.

## 1. Source, exact revisions and provenance

| Item | Value |
| --- | --- |
| Repository | `Dolesh-avkalan/drive-tool` |
| New revision (tested) | `c2b324dab4cf720178a36a58b5f1cf1339730151` (branch `feature/module-003-review-fixes`) |
| New commit URL | https://github.com/Dolesh-avkalan/drive-tool/commit/c2b324dab4cf720178a36a58b5f1cf1339730151 |
| Old revision (tested) | `110b27e81cfead478eb6e400a44043f6e14f14b7` |
| Brief read | `tasks/MODULE-003.md` @ main `bb7c967b3e610d82eb0af7ff49e911f8a5eaf307` |
| d007 evidence read | `docs/evidence/MODULE-003-REVIEW-FIXES.md` @ new revision |
| d007 artifacts fetched | `Dolesh-avkalan/drop` @ `7e847300b7dc33e4722bee450b1db29d1c7dc47e`, `drive-tool/module-003/d007-sarvam-review-fixes/` (present — reproducer and raw logs used only as a cross-check, §8) |

The task asked to read `tasks/MODULE-003.md` from main. The pinned revisions do
not contain it (they contain only `tasks/MODULE-001.md`); the brief was read from
main as instructed. The two pinned trees were fetched separately (no git
history) and their contents hashed locally.

## 2. Execution environment (recorded, raw in `logs/00_env.log`)

- Kernel: `Linux ... 4.19.0-gvisor #1 ... x86_64 GNU/Linux` (gVisor sandbox).
- Filesystem: `/` = overlay; `/tmp` and `/scratch` = `9p` (`v9fs`);
  `/dev/shm` = tmpfs. `stat -f /scratch/tmp` → `v9fs`.
- Interpreters: **Python 3.11.2** (`/usr/bin/python3.11`), **Python 3.12.13**
  (`/usr/local/bin/python3.12`).
- Flags: `O_NOFOLLOW=131072  O_DIRECTORY=65536  O_NONBLOCK=2048  O_CLOEXEC=524288`.
- `TMPDIR=/scratch/tmp`; all fixtures tiny synthetic directories there.
- Note: this is a *different* sandbox instance from the d007 run
  (`claw-sandbox-dc77…` here vs `claw-sandbox-9a81…` in the d007 env log), i.e.
  a genuinely fresh kernel/container.

## 3. Committed suite — actual results

Run from each checkout root: `python3.11 -m unittest discover -s tests -v` and
`python3.12 -m unittest discover -s tests -v`. Full stdout/stderr in
`logs/new_py311.log`, `logs/new_py312.log`, `logs/old_py311.log`,
`logs/old_py312.log`.

| Revision | Interpreter | Result | Exit | Skips |
| --- | --- | --- | --- | --- |
| new `c2b324da` | 3.11.2 | `Ran 82 tests` … `OK` | 0 | none |
| new `c2b324da` | 3.12.13 | `Ran 82 tests` … `OK` | 0 | none |
| old `110b27e8` | 3.11.2 | `Ran 67 tests` … `OK` | 0 | none |
| old `110b27e8` | 3.12.13 | `Ran 67 tests` … `OK` | 0 | none |

82 = 46 (`test_local`) + 36 (`test_storage`); 67 = 31 + 36. These counts match
d007 §5.1. No test was skipped; there is no "skipped" runner line in any log.
The suite passes on the old revision too — passing the suite is therefore not
evidence of race safety, consistent with d007.

## 4. No-follow semantics and directory-swap containment (acceptance 2)

**Real kernel, no mocks.** `raw_nofollow_probe.py` calls the real `os.open` with
four flag sets (raw in `logs/raw_nofollow_probe_py311.log`):

| Target | `O_NOFOLLOW` only (adapter's flags) | `O_NOFOLLOW\|O_DIRECTORY` (old adapter) | `O_DIRECTORY` only | plain |
| --- | --- | --- | --- | --- |
| symlink→dir | **ELOOP** (rejected) | **opened as dir (followed!)** | opened as dir | opened as dir |
| broken symlink | **ELOOP** | ENOENT | ENOENT | ENOENT |
| real dir | opened, `S_ISDIR` | opened, `S_ISDIR` | opened | opened |
| `/` | opened, `S_ISDIR` | opened | opened | opened |
| FIFO | opened, `S_ISFIFO` | ENOTDIR | ENOTDIR | opened |
| regular file | opened, `S_ISREG` | ENOTDIR | ENOTDIR | opened |

This independently confirms d007 §3 on this kernel: `O_NOFOLLOW` **alone** is
honoured and rejects a symlink atomically at open; **combining it with
`O_DIRECTORY` makes the kernel ignore `O_NOFOLLOW`** and follow the symlink.
That is precisely why the old `lstat`-before-open emulation had a check-to-use
window and the revised strategy (no `O_DIRECTORY`, `O_NOFOLLOW` only, `fstat`
the result) is the correct one here.

**Asserting swap probe (old-fail / new-pass).** `containment_assert.py` renames a
directory component and replaces it with a symlink to an outside fixture
*immediately before* that component's open, then calls the real `os.open`. The
outside fixture contains synthetic sentinels only. Results (both interpreters,
`logs/containment_{new,old}_py3*.log`):

| Entry point | new `c2b324da` | old `110b27e8` |
| --- | --- | --- |
| `read_bytes('p/sub/target.txt')` traversal | PASS — `UnsafePathError` | **ESCAPE** — returned outside sentinel bytes |
| `stat('p/sub/target.txt')` traversal | PASS — `UnsafePathError` | **ESCAPE** — outside metadata (`size=33`) |
| `list_children('p/sub')` final dir open | PASS — `UnsafePathError` | **ESCAPE** — outside listing |
| root/ancestor swap at construction | PASS — `UnsafePathError` | **ESCAPE** — adapter anchored OUTSIDE, read sentinel |
| RESULT / exit | PASS / 0 | FAIL / 1 |

The root-ancestor case mirrors `inner/` under the outside directory, so the old
revision genuinely anchors the root descriptor outside and reads the sentinel
(d007's own reproducer hit a `ValueError` there instead because its outside
fixture lacked the matching subdir). The old revision is **not** contained on
this kernel — reported as measured, not fabricated. On a conformant kernel
(e.g. ext4, where `O_NOFOLLOW|O_DIRECTORY` is honoured) the old emulation would
be contained; that is **inferred, not executed here** (§10).

## 5. Bounded reads with deterministic growth (acceptance 3)

`bounded_read_checks.py`, `max_read_bytes=1000` (logs
`logs/bounded_read_checks_new_py3*.log`), PASS on both interpreters:

- below-limit (990 bytes) → exact bytes returned;
- exact-limit (1000 bytes) → exact bytes returned;
- above-limit (1001 bytes) → `ReadLimitExceededError` from `fstat`;
- **grow-during-read**: file starts at 1000, appended via the `_os_read` seam so
  it grows *after* `fstat` → `ReadLimitExceededError` (cap cannot be bypassed);
- **under-report-stat**: `_os_fstat` is made to lie that a really-1500-byte file
  is 10 bytes → `ReadLimitExceededError` at read time (the `max_read_bytes+1`
  read cap catches it).

## 6. Root-rename anchoring and FIFO timeout (acceptance 3)

`root_rename_anchor.py` (logs `logs/root_rename_anchor_new_py3*.log`), PASS both:
after construction the root pathname is renamed away and replaced first by an
outside symlink, then by a real outside directory; the adapter keeps reading the
original bytes, listing the original child and reporting the original size via
its retained descriptor. A control adapter built on the replaced path *does* see
the outside data, showing the replacements are effective.

`fifo_timeout.py` (logs `logs/fifo_timeout_new_py3*.log`), PASS both: the FIFO
read is run in a child process under a 10 s wall-clock timeout — it returns
`UnsupportedEntryError` well within the timeout (no hang), `stat('p/fifo')`
raises `UnsupportedEntryError`, and `list_children` omits the FIFO.

## 7. Descriptor lifetime — including the untested parent-close path

`fd_cleanup.py` (logs `logs/fd_cleanup_new_py3*.log`).

**Part A — repeated success/failure accounting: PASS.** 300 iterations × 11
operations (success and failure: missing entry, malformed ID, symlink, FIFO,
directory-as-file) leave the process open-fd count unchanged (before=5,
after=5). No leak across repeated success or failure.

**Part B — parent close error *after* the child descriptor is acquired: FAIL.**
This is the path the d007 committed tests do not cover (they cover close failure
during traversal/root setup only). For `read_bytes` and `list_children` the
adapter opens a parent directory fd, then the child file/scan fd, then closes
the parent in a `finally`. Injecting a failure on that parent close (emulating a
`close()` that reports an error while the kernel has released the fd), the child
descriptor is **not released**:

| Case | ordered descriptor events | child fd | after op |
| --- | --- | --- | --- |
| `read_bytes('p/a/b/file.txt')` | open 4, open 5, close 4, open 4, **close 5 raises** | 4 (file) | fd 4 still open (`fstat` ok) — **orphaned** |
| `list_children('p/a/b')` | open 4, open 5, **close 5 raises** | 5 (scan) | fd 5 still open — **orphaned** |

Identical on 3.11.2 and 3.12.13. Root cause: the parent fd is closed in a
`finally` that executes after the child fd has been assigned; when that close
raises (mapped to `LocalStorageError`), the later `try/finally` that would close
the child never runs, so the child descriptor leaks. This contradicts the
module's stated invariant (REVIEW-FIXES §4.1.4: "no orphaned descriptor is
leaked … every opened descriptor is released exactly once").

Severity, stated fairly: it requires `close()` to report an error, which is rare
for read-only directory descriptors (`EBADF`/`EINTR`/`EIO`); it leaks one
descriptor per occurrence; it is **not** a containment or data-exposure escape.
It is a correctness gap against the module's own ownership claim and it is
untested by d007. Detection note: an fd-number-based tracker is fooled here by
kernel fd reuse (the file fd reuses the just-freed intermediate fd number), so
this check uses an ordered open/close live-set plus a direct `fstat` on the child
fd.

## 8. Revision diff and d007 cross-check (acceptance 4)

`diff_check.py` (log `logs/diff_check.log`), PASS. Comparing old vs new trees by
git blob hash (sha1 of `blob <len>\0<content>`, comparable to
`git hash-object`; `__pycache__` build artifacts from running the suite are
excluded as untracked):

- changed (3): `drive_tool/local.py`, `tests/test_local.py`,
  `docs/evidence/MODULE-003.md`
- added (1): `docs/evidence/MODULE-003-REVIEW-FIXES.md`
- removed (0)

So exactly the four d007-reported files differ. All MODULE-001 and frozen blobs
are byte-identical old↔new:

```
SAME  drive_tool/__init__.py            9be841b5749acb36c5e362c84b986d98292bae8d
SAME  drive_tool/storage.py             28f7b8c0ce7ac56d602d0af3a709c3f31441904b
SAME  tests/test_storage.py             2126dde7f32b7c0cd4d1e737ff990ab10954caf5
SAME  docs/evidence/MODULE-001.md       3dabc64d75ff2fee3786de76179cdbf184332517
SAME  tasks/MODULE-001.md               9168f60a4499383c89a39033529fec6e2773921a
SAME  README.md                         3e23315ec72a68d7b9bb30d2c87b617147e0add6
SAME  docs/evidence/MODULE-003-GEMINI.md a9701ca7a033bf71c0a115fe4eadad096ed824b7
```

Changed/added blobs:

```
drive_tool/local.py                     5e2078f0… (old) -> 2f85eebf… (new)
tests/test_local.py                     ade91bc0… (old) -> b84b4177… (new)
docs/evidence/MODULE-003.md             d189cf12… (old) -> 565a915c… (new)
docs/evidence/MODULE-003-REVIEW-FIXES.md  (absent old) -> 67172542… (new)
```

**d007 artifacts cross-check (secondary).** The d007 reproducer and raw logs were
available in `Dolesh-avkalan/drop` and were run here:

- `race_probe_assert.py` → new PASS exit 0, old FAIL exit 1 (same four entry
  points), independently reproducing d007 §5.2.
- `run_new_tests_on_old.py` (old `drive_tool` + new `tests`) → `Ran 46 tests`,
  `FAILED (failures=6, errors=6)`, exit 1 on both interpreters, reproducing
  d007 §5.3.

These are labelled as a cross-check; the primary d009 evidence is the
independent scripts in §4–§7.

## 9. Files shipped with this report

Target location in the relay repo: `drive-tool/module-003/d009-independent-tests/`
(write blocked here — see §0). Delivered instead as files:

- `d009-sarvam-independent-tests.md` — this report.
- `containment_assert.py` — independent directory-swap containment probe (§4).
- `raw_nofollow_probe.py` — real-kernel `O_NOFOLLOW`/`O_DIRECTORY` probe (§4).
- `bounded_read_checks.py` — bounded reads + deterministic growth (§5).
- `root_rename_anchor.py` — retained-root-fd anchoring (§6).
- `fifo_timeout.py` — FIFO no-hang via timeout-bounded child (§6).
- `fd_cleanup.py` — fd accounting + parent-close-after-child leak check (§7).
- `diff_check.py` — revision diff / MODULE-001 blob check (§8).
- `run_all.sh` — consolidated runner.
- `logs/` — `00_env.log`, `battery.log`, and per-run raw logs (suite new/old ×
  py3.11/3.12, raw probe, containment new/old, bounded, anchor, fifo, fd,
  diff, d007 cross-checks).

## 10. Limits and residual risk

- Deterministic **mechanism** evidence, not a concurrency stress test. The swap
  is triggered at a seam immediately before the real open; the open itself is
  real kernel `os.open`, not a mock, but a true racing writer is not exercised.
- Environment is gVisor over 9p: `O_NOFOLLOW|O_DIRECTORY` is non-conformant here
  while `O_NOFOLLOW` alone is honoured. Conformant-kernel (e.g. ext4) behaviour
  for the same swap is **inferred from the documented kernel contract, not
  executed here**. On such a kernel the old revision's `lstat` emulation would
  be contained and no old failure would be observable.
- The §7 descriptor gap requires an injected `close()` error; its practical
  likelihood on read-only directory fds is low. Reported as measured.
- Unchanged documented boundaries still apply: concurrent external writers may
  change file contents mid-read (bounded bytes only, no snapshot/checksum); hard
  links, bind mounts/submounts, procfs/sysfs and adversarial root provisioning
  are operator responsibilities. No production security completeness is claimed.
- Nothing was pushed anywhere; no `drive-tool` branch or `main` was modified.
- No module beyond MODULE-003 was started.

## 11. Bottom line

The d007 correction is independently reproduced on a fresh sandbox: the revised
revision contains the directory-swap at all four entry points while the old
revision escapes at all four (old-fail/new-pass, real kernel), the bounded-read,
anchoring and FIFO properties hold, and only the four reported files differ with
MODULE-001 blobs unchanged. One new gap is reported honestly: the child
descriptor is orphaned when the parent close errors after the child is acquired
(§7) — untested by d007 and against the module's stated ownership invariant,
though not a containment escape.
