# d038 — bounded cloud validation runner (drive-tool candidate)

Self-contained, stdlib-only runner for the director to execute on the
directortemp VM. It validates the **pinned** candidate
`Dolesh-avkalan/drive-tool @ e88c9c79fdc27057622d44ba51e008f2e4ea4f4f`
(tree `abc0ffb2f561b375cd5166a6bf223d45e3b834c2`) by downloading its GitHub
archive, verifying identities, and running the committed suite plus real-kernel
checks.

It is adapted from the proven d014 runner design
(`drive-tool/readonly-core/d014-cloud-validation/runner/`) with its exact
archive pin and executable source/test identity list regenerated from GitHub.
It does **not** run on the target from the author's side. No target results are
fabricated here. Independent execution of this candidate (D037) is still
finishing on the local host; this bundle only *prepares* the runner.

## The command

```
python3 run_cloud_validation.py
```

That is the whole invocation. It creates a fresh unique workspace under
`/tmp` (`/tmp/d038-e88c9c79-<uniq>`), runs everything, prints `RESULT: PASS` or
`RESULT: FAIL (fail-closed)`, and exits `0` only on success. The workspace is
**kept** for retrieval; the exact cleanup command is printed at the end.

If the VM has no egress, pre-stage the pinned archive and pass it:

```
python3 run_cloud_validation.py --archive /path/to/drive-tool-e88c9c79.tar.gz
```

## Overall invocation timeout guidance

The runner bounds every sub-step itself (archive download, per-interpreter
suite, each kernel check in its own process), but it does **not** impose a
single outer deadline. Wrap the whole invocation in one director-side
wall-clock timeout. The runner prints a recommended value
(`RECOMMENDED_OVERALL_TIMEOUT_SECONDS`, default **5580 s**) which is the
worst-case sum of the default per-step budgets:

```
180 (download) + 3 interpreters x (300 suite + 10 checks x 120) = 5580 s
```

For example: `timeout 5580 python3 run_cloud_validation.py`. With fewer
interpreters the real runtime is far shorter (a two-interpreter sandbox run
finishes in well under a minute).

## Requirements / assumptions

- A POSIX host with Python 3 (the runner itself is stdlib-only; it then runs the
  suite on every interpreter it finds: `python3.14`, `3.13`, `3.12`, `3.11`,
  `3.10`, `3`).
- Outbound HTTPS to `codeload.github.com` for the pinned archive, **or** a
  pre-staged archive via `--archive <path>` (e.g. if the VM has no egress).
- Nothing is installed, cloned, mounted, or written outside the workspace. No
  credentials are used. The implementation is never edited and kernel support is
  never mocked. No browser service is touched; no reboot; no package install.

## What it checks, in order (each gate fails closed)

1. **Workspace + resources** — creates a new unique dir; requires the workspace
   filesystem to have free space (default ≥ 20 MiB).
2. **Environment (before)** — hostname, `uname`, OS release, interpreter, free
   space on the workspace/`/tmp`, memory, relevant mounts.
3. **Pinned archive** — downloads
   `https://codeload.github.com/Dolesh-avkalan/drive-tool/tar.gz/e88c9c79fdc27057622d44ba51e008f2e4ea4f4f`
   with a 50 MiB byte cap and a wall-clock timeout (default 180 s).
4. **Guarded extraction** — rejects absolute paths, `..` components, symlink/
   hardlink members, non-regular members; caps member count (2000), per-file
   size (5 MiB) and total uncompressed size (50 MiB).
5. **Identity** — recomputes the git blob sha1 of all **18** pinned Python
   files (the executable source `drive_tool/*.py` and every test module
   `tests/*.py`) and compares to the commit's known hashes **before** executing
   anything. Any mismatch or missing file aborts with the offending path.
   The d014 `EXPECTED_BLOBS` are **not** reused.
6. **Python coverage** — additionally fails closed if **any** `*.py` file
   present in the extracted tree is not in the pinned identity list, so every
   file `unittest` could execute (including newly added tests) is covered.
7. **Committed suite** — `python -m unittest discover -s tests -v` on each
   available interpreter, under a wall-clock timeout (default 300 s). Records
   full stdout/stderr, exit, count and skips.
8. **Real-kernel checks** — each in its own process under a wall-clock timeout
   (default 120 s). The six retained d014 checks (`nofollow`, `bounded_read`,
   `root_anchor`, `dir_symlink_swap`, `fifo`, `fd_lifetime`) plus four new tiny
   real-filesystem checks (`strict_b_scanner`, `partial_search`,
   `write_collision`, `concurrent_writers`). These use real synthetic files and
   real `os.open`/`os.scandir` semantics. A conformant kernel is not expected to
   reproduce any historical insecure behaviour; the checks assert *containment*,
   not a specific failure mode. Each check's output labels **REAL** file
   operations observed through a seam separately from **SIMULATED** fault
   injection.
9. **Environment (after)** and a **SHA-256/length manifest** of the whole
   workspace (`logs/MANIFEST.md`), plus `logs/summary.json`.

`TMPDIR` is set inside the workspace and `PYTHONDONTWRITEBYTECODE=1`, so all
fixtures and any bytecode stay in the workspace.

### The four new d038 checks

- **`strict_b_scanner`** — wraps the **real** `os.scandir` iterator in an
  observational seam that counts raw yields and stat calls (no fault injection).
  Asserts the scanner pulls exactly `B` raw entries and never probes `B+1`, and
  that at most `B` entries are stat'ed.
- **`partial_search`** — **REAL**: a directory holding exactly `B` entries
  scanned with budget `B` never observes EOF, so `find` retains its matches and
  returns `truncated=True, reason="max_entries"` (an unknown end-of-directory is
  reported as truncation, never as "not found"). **SIMULATED**: the scandir seam
  fails after `k` real yields for a subdirectory; `find` charges the raw work,
  records the directory in `skipped`, keeps the matches it already had, and
  returns `truncated=True, reason="skipped"`.
- **`write_collision`** — **REAL**: a no-overwrite write of an existing name
  raises `AlreadyExistsError` and leaves the original bytes intact, with no
  stray temp file.
- **`concurrent_writers`** — **REAL**: a bounded set of threads each attempt a
  no-overwrite write of the same name with a distinct full payload; exactly one
  wins, every loser raises `AlreadyExistsError`, and the published file holds
  the winner's exact full payload with no truncation or mixing.

## Options

```
--base-dir DIR        where to create the unique workspace (default /tmp)
--workdir PATH        explicit workspace path (must not already exist)
--archive PATH        use a local .tar.gz instead of downloading
--python NAME         restrict to one interpreter (repeatable)
--download-timeout N  archive download timeout seconds (default 180)
--suite-timeout N     per-interpreter suite timeout seconds (default 300)
--check-timeout N     per-kernel-check timeout seconds (default 120)
--min-free-bytes N    required free space in the workspace fs (default 20 MiB)
```

## Outputs

Under `<workspace>/logs/`: `env_before.json`, `env_after.json`, `identity.txt`,
`suite_<py>.out`, `check_<py>_<name>.out`, `summary.json`, `MANIFEST.md`. The
downloaded archive (`archive.tar.gz`) and the extracted tree are kept too.

## Safety and limits

- Only the created workspace is touched; no broad cleanup or deletion is done.
  To remove everything when evidence is no longer needed, run the exact
  `rm -rf <workspace>` line the runner prints (and nothing wider).
- Fixtures are real synthetic files, ≤ 1 MiB each; total new files stay well
  under 50 MiB.
- Does not inspect private paths or enumerate browser profiles; does not read
  user data or any environment secret.
- Preserves the target's browser services; no service change, no reboot, no
  package installation.

## Provenance of this runner

Adapted for d038 from the d014 runner and exercised end-to-end in the author's
sandbox against the pinned archive (see the bundled `sandbox/` logs). In that
sandbox only Python 3.11.2 and 3.12.13 were present, so **Python 3.14 was
unavailable there and is not claimed**; the target's 3.14 will be picked up
automatically when the director runs it. Negative gates (tampered archive,
path-traversal archive, symlink member, missing archive, workspace reuse,
unpinned Python file) all failed closed.
