# d014 — bounded cloud validation runner (read-only core candidate)

Self-contained, stdlib-only runner for the director to execute on the
directortemp VM. It validates the **pinned** integrated candidate
`Dolesh-avkalan/drive-tool @ 99e102522da4f0eeee465fe231ad62f0cc4ecad8`
(`feature/readonly-core-candidate`) by downloading its GitHub archive,
verifying identities, and running the committed suite plus real-kernel checks.

It does **not** run on the target from the author's side. No target results are
fabricated here.

## The command

```
python3 run_cloud_validation.py
```

That is the whole invocation. It creates a fresh unique workspace under
`/tmp` (`/tmp/d014-99e10252-<uniq>`), runs everything, prints `RESULT: PASS` or
`RESULT: FAIL (fail-closed)`, and exits `0` only on success. The workspace is
**kept** for retrieval; the exact cleanup command is printed at the end.

## Requirements / assumptions

- A POSIX host with Python 3 (the runner itself is stdlib-only; it then runs the
  suite on every interpreter it finds: `python3.14`, `3.13`, `3.12`, `3.11`,
  `3.10`, `3`).
- Outbound HTTPS to `codeload.github.com` for the pinned archive, **or** a
  pre-staged archive via `--archive <path>` (e.g. if the VM has no egress).
- Nothing is installed, cloned, mounted, or written outside the workspace. No
  credentials are used. The implementation is never edited and kernel support is
  never mocked.

## What it checks, in order (each gate fails closed)

1. **Workspace + resources** — creates a new unique dir; requires the workspace
   filesystem to have free space (default ≥ 20 MiB).
2. **Environment (before)** — hostname, `uname`, OS release, interpreter, free
   space on the workspace/`/tmp`, memory, relevant mounts.
3. **Pinned archive** — downloads `https://codeload.github.com/Dolesh-avkalan/drive-tool/tar.gz/99e102522da4f0eeee465fe231ad62f0cc4ecad8`
   with a 50 MiB byte cap and a wall-clock timeout (default 180 s).
4. **Guarded extraction** — rejects absolute paths, `..` components, symlink/
   hardlink members, non-regular members; caps member count (2000), per-file
   size (5 MiB) and total uncompressed size (50 MiB).
5. **Identity** — recomputes the git blob sha1 of all **17** pinned files and
   compares to the commit's known hashes **before** executing anything. Any
   mismatch or missing file aborts with the offending path.
6. **Committed suite** — `python -m unittest discover -s tests -v` on each
   available interpreter, under a wall-clock timeout (default 300 s). Records
   full stdout/stderr, exit, count and skips.
7. **Real-kernel checks** — each in its own process under a wall-clock timeout
   (default 120 s): `nofollow`, `bounded_read`, `root_anchor`,
   `dir_symlink_swap`, `fifo`, `fd_lifetime`. These use real synthetic files and
   real `os.open` semantics. A conformant kernel is not expected to reproduce any
   historical insecure behaviour; the checks assert *containment*, not a
   specific failure mode.
8. **Environment (after)** and a **SHA-256/length manifest** of the whole
   workspace (`logs/MANIFEST.md`), plus `logs/summary.json`.

`TMPDIR` is set inside the workspace and `PYTHONDONTWRITEBYTECODE=1`, so all
fixtures and any bytecode stay in the workspace.

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
- Fixtures are real synthetic files, ≤ 1 MiB each (the bounded-read growth check
  stays far below that). Total new files stay well under 50 MiB.
- Does not inspect private paths or enumerate browser profiles; does not read
  user data.

## Provenance of this runner

Authored for d014 and exercised end-to-end in the author's sandbox against the
same pinned archive (see the bundled `sandbox/` logs). In that sandbox only
Python 3.11.2 and 3.12.13 were present, so **Python 3.14 was unavailable there
and is not claimed**; the target's 3.14 will be picked up automatically when the
director runs it. Negative tests (tampered archive, path-traversal archive,
symlink member, missing archive, workspace reuse) all failed closed.
