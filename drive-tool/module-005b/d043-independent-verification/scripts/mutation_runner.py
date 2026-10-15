"""Focused mutation runner for MODULE-005B (LocalAdapter.read_range).

Each mutant is applied to an *isolated copy* of the candidate tree (never to
the committed candidate), the full committed suite is run, and the copy is
discarded. A mutant is "caught" when at least one test fails or errors. This
proves the named guards actually fail the suite when broken. Mutations are never
published in the implementation.

Usage:  python3 mutation_runner.py [python_exe]
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

SRC_REPO = "/scratch/repos/drive-tool"
WORK = "/scratch/work/mutants"
LOGS = "/scratch/work/logs"
PY = sys.argv[1] if len(sys.argv) > 1 else "python3.12"

# (name, description, old, new)
MUTANTS = [
    (
        "M1_read_bytes_and_slice",
        "read_range reimplemented as read_bytes (whole read) then slice "
        "(also inherits whole-size rejection)",
        """        chunks: list[bytes] = []
        collected = 0
        eof_observed = False

        while collected < length:
            request = min(_READ_CHUNK_SIZE, length - collected)
            try:
                chunk = self._os_pread(file_fd, request, offset + collected)
            except OSError as exc:
                if exc.errno == errno.EINTR:
                    continue
                raise LocalStorageError(
                    f"failed while reading range of {file_id!r}: {exc}"
                ) from exc

            if not chunk:
                eof_observed = True
                break

            collected += len(chunk)
            chunks.append(chunk)
""",
        """        whole = self._read_open_file_bounded(file_fd, file_id)
        sliced = whole[offset : offset + length]
        chunks: list[bytes] = [sliced]
        collected = len(sliced)
        eof_observed = collected < length
""",
    ),
    (
        "M2_unbounded_pread_request",
        "pread requests an unbounded amount instead of min(chunk, remaining)",
        "            request = min(_READ_CHUNK_SIZE, length - collected)\n",
        "            request = 1 << 30\n",
    ),
    (
        "M3_early_stop_on_short_read",
        "loop stops early when a pread returns fewer bytes than requested",
        """            if not chunk:
                eof_observed = True
                break

            collected += len(chunk)
            chunks.append(chunk)
""",
        """            if not chunk:
                eof_observed = True
                break

            collected += len(chunk)
            chunks.append(chunk)
            if len(chunk) < request:
                break
""",
    ),
    (
        "M4_incorrect_exact_window_eof",
        "eof_observed derived from observed_size instead of a pread returning b''",
        "            eof_observed=eof_observed,\n",
        "            eof_observed=eof_observed or offset + length >= observed_size,\n",
    ),
    (
        "M5_missing_no_follow",
        "file open flags drop O_NOFOLLOW",
        '''def _file_open_flags() -> int:
    """Return flags for non-blocking, no-follow file opens."""
    return (
        os.O_RDONLY
        | os.O_NOFOLLOW
        | os.O_NONBLOCK
        | getattr(os, "O_CLOEXEC", 0)
    )''',
        '''def _file_open_flags() -> int:
    """Return flags for non-blocking, no-follow file opens."""
    return (
        os.O_RDONLY
        | os.O_NONBLOCK
        | getattr(os, "O_CLOEXEC", 0)
    )''',
    ),
    (
        "M6a_lost_fd_cleanup",
        "read_range no longer releases its acquired descriptors",
        "            return self._read_open_file_range(\n                file_fd, ref.file_id, eff_offset, eff_length\n            )\n        finally:\n            self._release_owned(owned)\n",
        "            return self._read_open_file_range(\n                file_fd, ref.file_id, eff_offset, eff_length\n            )\n        finally:\n            pass\n",
    ),
    (
        "M6b_error_priority_masked",
        "cleanup close failure masks the primary read error",
        "        if first_failure is not None and primary is None:\n",
        "        if first_failure is not None:\n",
    ),
]

_FAIL_RE = re.compile(r"^(FAIL|ERROR): (\S+)", re.MULTILINE)


def _copy_tree(dst: str) -> None:
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(
        SRC_REPO,
        dst,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"),
    )


def _run_suite(repo: str) -> tuple[int, str, list]:
    proc = subprocess.run(
        [PY, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    out = proc.stdout + proc.stderr
    caught = sorted({m.group(2) for m in _FAIL_RE.finditer(out)})
    return proc.returncode, out, caught


def main() -> int:
    os.makedirs(WORK, exist_ok=True)
    os.makedirs(LOGS, exist_ok=True)

    src = open(os.path.join(SRC_REPO, "drive_tool", "local.py")).read()

    # Baseline (no mutation) must be green.
    base_dir = os.path.join(WORK, "baseline")
    _copy_tree(base_dir)
    rc, out, caught = _run_suite(base_dir)
    with open(os.path.join(LOGS, "mutation_baseline.log"), "w") as f:
        f.write(out)
    tail = [ln for ln in out.splitlines() if ln.startswith("Ran ") or ln.strip() in ("OK", "FAILED")]
    print(f"[baseline] exit={rc} {' | '.join(tail)} caught={caught}")
    if rc != 0:
        print("BASELINE NOT GREEN - aborting")
        return 1

    summary = []
    for name, desc, old, new in MUTANTS:
        if old not in src:
            print(f"[{name}] ANCHOR NOT FOUND - mutant invalid")
            summary.append((name, "ANCHOR-NOT-FOUND", 0, []))
            continue
        if src.count(old) != 1:
            print(f"[{name}] ANCHOR NOT UNIQUE ({src.count(old)}) - mutant invalid")
            summary.append((name, "ANCHOR-NOT-UNIQUE", 0, []))
            continue
        repo = os.path.join(WORK, name)
        _copy_tree(repo)
        path = os.path.join(repo, "drive_tool", "local.py")
        mutated = src.replace(old, new)
        with open(path, "w") as f:
            f.write(mutated)
        rc, out, caught = _run_suite(repo)
        with open(os.path.join(LOGS, f"mutation_{name}.log"), "w") as f:
            f.write(out)
        status = "CAUGHT" if rc != 0 else "SURVIVED"
        print(f"[{name}] {status} (exit={rc}) caught_by={len(caught)}: {caught[:6]}")
        summary.append((name, status, len(caught), caught))

    print("\n=== SUMMARY ===")
    for name, status, n, caught in summary:
        print(f"{name}: {status} ({n} tests)")

    survivors = [s for s in summary if s[1] == "SURVIVED"]
    print(f"\nmutants={len(summary)} caught={sum(1 for s in summary if s[1]=='CAUGHT')} "
          f"survivors={len(survivors)}")
    return 0 if not survivors else 1


if __name__ == "__main__":
    raise SystemExit(main())
