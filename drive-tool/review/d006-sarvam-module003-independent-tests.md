# MODULE-003 — Independent Re-test and Race Review (d006, Sarvam)

Independent, read-only re-test of the exact `drive-tool` commit
`110b27e81cfead478eb6e400a44043f6e14f14b7` in a fresh sandbox checkout at
detached HEAD. No branch was modified, no merge/deploy was performed, no
production files or services were touched, and only small temporary synthetic
fixtures under throwaway temp directories were used. Temporary regression
scripts live outside the checkout (sources included in the sibling folder).

This report is written by Sarvam and is independent of the implementer evidence
(`docs/evidence/MODULE-003-GEMINI.md`) and of the assembler evidence
(`docs/evidence/MODULE-003.md`) shipped in the same commit.

---

## 0. Verdict (short)

- **Test suite result reproduced:** `67` tests, `OK`, exit code `0`, **0 skipped**,
  on **both** Python 3.11.2 and Python 3.12.13. This matches the "after fixes"
  claim in `docs/evidence/MODULE-003.md` §4.2.
- **`O_NOFOLLOW | O_DIRECTORY` is not honoured on this environment:** a raw
  `os.open(..., O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_NONBLOCK, dir_fd=...)` on a
  symlink-to-directory **succeeds and follows the link** here, while
  `O_NOFOLLOW` *without* `O_DIRECTORY` correctly raises `ELOOP`. Reproduced on
  both interpreters and on all three mount types tested (`/tmp` 9p, `/scratch`
  9p, `/dev/shm` tmpfs).
- **The `lstat`-before-open guard added in the assembler fix is NOT race-safe on
  this platform.** A deterministic swap of an intermediate directory to a
  symlink *after* `_os_stat_nofollow` and *before* `_os_open` escapes the root at
  all three entry points exercised: `read_bytes` returned **outside sentinel
  bytes**, `stat` exposed **outside metadata**, and `list_children` exposed
  **outside directory entries**. The same interleaving is blocked when the open
  is made to honour `O_NOFOLLOW` (simulated, clearly labelled).
- **Descriptor cleanup and bounded reads look correct** under both the shipped
  tests and an independent `/proc/self/fd` probe and sparse-file probe.
- **The static symlink containment tests pass only because the symlink is present
  at `lstat` time.** They do not exercise the check→use window, so passing them
  is not evidence that the guard is race-safe — and the race probe shows it is
  not.

---

## 1. Source, environment and provenance

| Item | Value |
| --- | --- |
| Repository | `Dolesh-avkalan/drive-tool` |
| Reviewed commit (SHA) | `110b27e81cfead478eb6e400a44043f6e14f14b7` |
| Commit subject | `Add MODULE-003 evidence report` |
| Commit date | `2026-10-14 14:03:43 +0000` |
| Branch tip | yes — tip of `origin/feature/module-003-local-readonly` |
| Checkout | fresh `git clone`, `git checkout 110b27e8…` → detached HEAD confirmed |
| Tracked-tree state | clean (`git status --porcelain` shows only test-run `__pycache__/`, no tracked file modified) |
| Task brief read | `tasks/MODULE-003.md` @ `b5424513796834fc8c03a56bee7b0f0f7abc1f74` |

Files under test (sha256 of the checked-out blobs):

```
8e3b75cf2c0e1d60239aeb6cd38322a83ad66e4715b02882d4ec16e6f8927449  drive_tool/local.py
670a8862b1194483f12a3e38ad9678579794dcef522ec932f04aa7e982b24838  tests/test_local.py
fa49d9658e390e26df6a936db3b4542f4f4b9d5b2a6a4a6ee2f93f3e31f6a777  drive_tool/storage.py
```

Interpreter versions (exact):

```
Python 3.11.2      (/usr/bin/python3.11)
Python 3.12.13     (/usr/local/bin/python3.12; python3 -> 3.12.13)
```

Environment (recorded, not attributed):

```
uname -a:  Linux <host> 4.19.0-gvisor #1 SMP ... x86_64 GNU/Linux
/proc/mounts (selected):  /  overlay | /tmp 9p | /scratch 9p | /dev/shm tmpfs
```

The platform identifies itself as `4.19.0-gvisor`. This is stated as an observed
fact. The behavioural result in §3 is reported as observed across the mount types
tested; no specific kernel/filesystem is named as the *cause* because the probe
was not designed to isolate that.

Raw environment log: `logs/00_env.log`.

---

## 2. Test execution (task item 1)

Commands, run from the repository root:

```
python3.11 -m unittest discover -s tests -v
python3.12 -m unittest discover -s tests -v
```

Results:

| Interpreter | Command | Tests | Skips | Final line | Exit code |
| --- | --- | --- | --- | --- | --- |
| 3.11.2 | `python3.11 -m unittest discover -s tests -v` | 67 | 0 | `OK` | `0` |
| 3.12.13 | `python3.12 -m unittest discover -s tests -v` | 67 | 0 | `OK` | `0` |

`Ran 67 tests in 0.437s` (3.11) and `Ran 67 tests in 0.483s` (3.12). The 67 tests
are 31 in `tests/test_local.py` + 36 in `tests/test_storage.py`. There are **no
skips**: the only occurrence of the string "skipped" in the logs is inside the
test *name* `test_disappearing_entry_during_listing_is_skipped`, which ran and
passed.

Raw logs: `logs/py311_unittest.log`, `logs/py312_unittest.log`,
`logs/py311_exit.log`, `logs/py312_exit.log`.

Targeted re-run of the descriptor-lifetime, bounded-read and special-entry
classes also passes on both interpreters (8 tests, `OK`, exit 0):
`logs/targeted_tests.log`.

This reproduces the assembler's "after fixes" result. It does **not** by itself
validate the containment *claim*, which §4 addresses.

---

## 3. Does `O_NOFOLLOW | O_DIRECTORY` follow a symlink here? (task item 2)

Reproducer: `nofollow_probe.py` (raw `os.open`, no adapter). It creates a real
directory, a symlink pointing at it, then opens the symlink with the exact flag
combination the adapter uses, and (for contrast) with `O_NOFOLLOW` alone.

Observed, identically on Python 3.11.2 and 3.12.13, for `/tmp` (9p), `/scratch`
(9p) and `/dev/shm` (tmpfs):

```
flags include O_NOFOLLOW: True, O_DIRECTORY: True
lstat('linkdir').islink = True
(A) open('linkdir', O_NOFOLLOW|O_DIRECTORY) -> SUCCEEDED fd=4 (symlink FOLLOWED)
    readdir(fd) = ['child']
(B) open('linkdir', O_NOFOLLOW only)        -> raised ELOOP (40)
```

So on this environment `O_NOFOLLOW` is effective on its own but is **not enforced
when combined with `O_DIRECTORY`**; the directory open follows the symlink. The
behaviour was identical across all three mount types, so it is not specific to a
single mount type in the set tested. Raw log: `logs/nofollow_probe.log`.

This is the platform non-conformance the assembler described in
`docs/evidence/MODULE-003.md` §5.1, and I reproduce it independently.

---

## 4. Pre-`stat`/open symlink-swap race (task item 3)

### 4.1 What the fix does

The assembler fix (commit `e899255`, included in the reviewed commit) added an
explicit no-follow guard in three places — `_open_anchored_root`,
`_traverse_parent_dir`, and `list_children` — of the form:

```python
pre_st = self._os_stat_nofollow(part, dir_fd=current_fd)   # check
if stat.S_ISLNK(pre_st.st_mode):
    raise UnsafePathError(...)
next_fd = self._os_open(part, dir_flags, dir_fd=current_fd) # use
```

The assembler's own evidence (`docs/evidence/MODULE-003.md` §6.2) claims:
*"`O_NOFOLLOW` is retained, so on a conformant kernel the check is redundant
defence-in-depth and the open remains the atomic guard against a symlink swapped
in between the `lstat` and the open."*

That claim is only true on a kernel that enforces `O_NOFOLLOW | O_DIRECTORY`. On
this platform the open does not enforce it (§3), so the guard reduces to a
classic check-then-use (TOCTOU) pair with no atomic backstop. The `lstat` also
cannot itself be atomic with the open.

### 4.2 Deterministic reproduction

Reproducer: `race_probe.py`. It wraps `LocalAdapter._os_open` so that the first
time it is called for the component `sub`, it (a) renames the real `sub`
directory to `sub__moved`, and (b) creates a symlink `sub -> <outside fixture>` —
and *then* delegates to the real open. Because the adapter always `lstat`s a
component immediately before opening it, the hook fires exactly inside the
`_os_stat_nofollow` → `_os_open` window. This is a deterministic mechanism proof
(no timing luck), in the same style as the suite's own adversarial test.

Fixture: an inside file `root/sub/target.txt` = `SAFE_INSIDE_BYTES`; an outside
fixture `outside/target.txt` = `OUTSIDE_SENTINEL_BYTES_0123456789` (33 bytes) and
`outside/secret.txt`.

**Part A — ACTUAL `os.open` on this environment** (real kernel behaviour):

```
[ACTUAL os.open (this env)] read_bytes('p/sub/target.txt') traversal
    -> ESCAPED: read_bytes returned OUTSIDE sentinel bytes b'OUTSIDE_SENTINEL_BYTES_0123456789'
[ACTUAL os.open (this env)] stat('p/sub/target.txt') traversal
    -> ESCAPED: stat exposed OUTSIDE metadata (size=33, name='target.txt')
[ACTUAL os.open (this env)] list_children('p/sub') final directory
    -> ESCAPED: list_children('p/sub') exposed OUTSIDE entries ['secret.txt', 'target.txt']
```

All three required entry points escape: the outside sentinel **bytes** are read,
outside **metadata** is exposed, and the outside **directory listing** leaks.
The intermediate-swap also defeats `read_bytes` and `stat` traversal because the
swapped directory fd is then used as the anchor for the final component.

**Part B — SIMULATED conformant open** (clearly labelled simulated evidence): the
wrapper performs the same swap but the open is made to honour
`O_NOFOLLOW | O_DIRECTORY` (raise `ELOOP` if the named entry is a symlink, as a
conformant kernel does):

```
[SIMULATED conformant open] read_bytes('p/sub/target.txt') traversal
    -> raised UnsafePathError: symlink encountered at 'sub' for 'p/sub/target.txt'
[SIMULATED conformant open] stat('p/sub/target.txt') traversal
    -> raised UnsafePathError: symlink encountered at 'sub' for 'p/sub/target.txt'
[SIMULATED conformant open] list_children('p/sub') final directory
    -> raised UnsafePathError: symlink encountered at 'sub' for 'p/sub'
```

On a conformant kernel the atomic open closes the window and containment holds.
Identical output on both interpreters. Raw log: `logs/race_probe.log`.

> Note on the task's conditional: the task said "if the kernel honours NOFOLLOW,
> separately simulate a nonconformant open that ignores the flag." Here the
> kernel does **not** honour it, so the roles are inverted: Part A is the actual
> nonconformant behaviour and Part B is the simulated conformant behaviour. Both
> are labelled.

### 4.3 Interpretation and scope (kept factual)

- The `lstat` guard is a check-then-use guard. On this platform it is **not
  race-safe**: an actor able to rename/replace a directory component (i.e. with
  write permission on that component's parent, which for the configured root is
  the operator's own directory) can redirect access outside the root.
- This is exactly the case the module contract forbids: *"Do not let symlink
  replacement between checks/opens redirect access outside the root"*
  (`tasks/MODULE-003.md`, "Containment and bounded reads — mandatory"), and the
  fix's stated justification claims the open backstops the swap. On this platform
  it does not.
- **The static symlink tests are not evidence of race safety.** They place the
  symlink *before* the operation, so the `lstat` sees it and the guard fires.
  They never interleave a swap between check and use. I therefore do **not** treat
  their passing as proof that the guard is race-safe.
- This is a mechanism/interleaving proof, not a stress test: it forces the
  interleaving deterministically. A separate real-concurrency stress run was not
  attempted and is not claimed.
- The escape requires a writer with rename/replace rights on a path component.
  If the configured root (and its ancestors) are strictly non-writable to any
  untrusted party for the whole lifetime of the adapter, this specific window is
  not reachable — but that is a deployment precondition, not something the code
  enforces, and the code/evidence claim otherwise.

---

## 5. Failure-path descriptor cleanup and bounded reads (task item 4)

### 5.1 Descriptor cleanup

Shipped tests (all pass, both interpreters):

- `test_close_idempotency_and_operations_after_close`
- `test_deterministic_descriptor_accounting_across_success_and_failures`
  (mock-based: asserts exactly 1 live fd while open, 0 after close, across
  success + `NotFoundError` + `UnsafePathError` + `ReadLimitExceededError`)
- `test_linux_proc_self_fd_bounded_count` (`/proc/self/fd` bounded count)

Independent probe `fd_probe.py` (no adapter-internal mocks; counts
`/proc/self/fd` directly, 50 iterations of mixed success/failure ops including a
symlink-traversal `UnsafePathError`, a missing-entry `NotFoundError`, and a
`ReadLimitExceededError`):

```
baseline=4 after_init=5 during_50_loops=5 after_close=4
RESULT: PASS (no leak)      # both Python 3.11.2 and 3.12.13
```

So the `scan_fd` leak described in `docs/evidence/MODULE-003.md` §5.2 is indeed
fixed at this commit, and the explicit `finally: self._os_close(scan_fd)` does
release the caller-side descriptor (CPython's `os.scandir(fd)` dups internally and
closes the duplicate). Raw log: `logs/fd_probe.log`.

Review of the cleanup structure (read-only; no fixes implemented): the
intermediate-traversal loop closes `next_fd` on a post-open `fstat` failure and
closes `current_fd` on any other failure; `stat`/`list_children`/`read_bytes`
close the traversed parent fd in a `finally`; `read_bytes` closes the file fd in a
`finally` after the bounded read. I found no leak in these paths under the probes
above.

**Descriptor gaps noted (not fixed):**

1. No shipped test drives a failure *inside* `_os_scandir` (e.g. `scandir`
   raising after `scan_fd` is opened); the `except` path there closes `scan_fd`
   and re-raises, but that branch is untested.
2. No shipped test drives `_os_fstat(file_fd)` raising inside
   `_read_open_file_bounded`; the outer `finally` closes `file_fd`, but that
   branch is untested.
3. `__del__` does a best-effort `close()`; a failure during interpreter shutdown
   is swallowed by design and is not tested.

### 5.2 Bounded reads

Shipped tests (all pass, both interpreters):

- `test_read_limit_below_exact_and_above_threshold` (15 / 16 / 17 bytes at limit
  16; the 17-byte file is rejected by the upfront `fstat` gate with **zero**
  `os.read` calls)
- `test_simulated_file_growth_after_fstat_reads_at_most_limit_plus_one`
  (exactly `max_read_bytes + 1` = 17 bytes read from the descriptor)
- `test_multi_chunk_streaming_growth_seam` (requests `[17, 11, 5]`, 17 bytes)

Independent probe `bounded_probe.py` adds two angles the suite does not cover:

```
(1) apparent_size=2147483648 st_blocks=4194304          # 2 GiB sparse file, limit 1 MiB
    outcome=ReadLimitExceededError: file 'p/huge.bin' size (2147483648 bytes) exceeds max_read_bytes (1048576 bytes)
    os.read calls before rejection=0
(2) outcome=ReadLimitExceededError: file 'p/grow.bin' exceeded max_read_bytes (16 bytes) while reading
    bytes read from descriptor=17 (expected max_read_bytes+1 = 17)
RESULT: PASS      # both Python 3.11.2 and 3.12.13
```

This supports the module's claim that a large apparent size is rejected by the
upfront gate **without calling `os.read` and without allocating proportional to
the untrusted size**, and that a file growing after `fstat` cannot exceed
`max_read_bytes + 1` bytes read from the descriptor. Raw log:
`logs/bounded_probe.log`.

**Bounded-read gaps noted (not fixed):**

1. No test asserts the *buffered* size stays ≤ `max_read_bytes` for an
   adversarial multi-chunk stream (the streaming seam proves bytes *read* ≤
   limit+1, which implies it, but memory-bound is not asserted directly).
2. The `EINTR` retry branch in the read loop is untested (hard to trigger
   deterministically).
3. Behaviour under `max_read_bytes` larger than the chunk size across many chunks
   is covered only indirectly.

---

## 6. Minimal reproducer

The core containment finding reduces to the two facts in §3–§4. Minimal
illustration (full sources in the sibling folder):

```python
import os, stat
# 1. This environment does not enforce O_NOFOLLOW together with O_DIRECTORY:
#    open(symlink_to_dir, O_RDONLY|O_DIRECTORY|O_NOFOLLOW, dir_fd=parent) succeeds.
# 2. The adapter's guard lstat()s then open()s, so a swap in between is not caught
#    here.  race_probe.py forces that swap via a wrapper on _os_open and shows
#    read_bytes returning the OUTSIDE fixture bytes.
```

Run:

```
PYTHONPATH=<checkout> python3.11 nofollow_probe.py
PYTHONPATH=<checkout> python3.11 race_probe.py     # also: python3.12 …
```

---

## 7. Files delivered with this report

In `drive-tool/review/d006-sarvam-module003-independent-tests/`:

- `nofollow_probe.py` — raw `os.open` no-follow probe (task item 2).
- `race_probe.py` — deterministic pre-stat/open swap race probe, actual +
  simulated (task item 3).
- `fd_probe.py` — independent `/proc/self/fd` failure-path leak probe (task item 4).
- `bounded_probe.py` — sparse-file and grow-after-fstat bounded-read probe
  (task item 4).
- `logs/00_env.log`, `logs/py311_unittest.log`, `logs/py312_unittest.log`,
  `logs/py311_exit.log`, `logs/py312_exit.log`, `logs/targeted_tests.log`,
  `logs/nofollow_probe.log`, `logs/race_probe.log`, `logs/fd_probe.log`,
  `logs/bounded_probe.log` — raw outputs.

---

## 8. Status

- **TESTS_RUN.** Both interpreters executed the full suite; exact counts, exit
  codes and raw logs are recorded above. Nothing here is fabricated; no
  execution result is claimed that was not produced.
- The suite passes; the containment *claim* does not hold on this platform
  against a check→use swap, as demonstrated deterministically.
- No branch, merge, deploy, service, production file, or credential was touched;
  no fix was implemented. Environment secrets were not inspected. Fixtures were
  temporary synthetic directories only.
