"""d034 mutation harness: apply each mutation to a scratch copy, run the suite,
record whether it is caught (some test fails) and by which tests."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "cand"
SCRATCH = HERE / "mut"
PY = sys.argv[1] if len(sys.argv) > 1 else "python3.11"


def edit(path: Path, old: str, new: str, occurrence: int = 1):
    text = path.read_text()
    n = text.count(old)
    if n == 0:
        raise SystemExit(f"mutation target not found in {path}: {old!r}")
    if occurrence > n:
        raise SystemExit(f"occurrence {occurrence}>{n} for {old!r} in {path}")
    # replace the Nth occurrence
    idx = -1
    for _ in range(occurrence):
        idx = text.index(old, idx + 1)
    text = text[:idx] + new + text[idx + len(old):]
    path.write_text(text)


MUTATIONS = {
    "M1_search_discard_partial_matches": (
        "drive_tool/search.py",
        "            if not batch_complete:\n"
        "                # A partially scanned folder is truncation, even if it held no\n"
        "                # matches: incomplete coverage is not \"not found\".\n"
        "                return FindResult(\n"
        "                    items=tuple(matches),",
        "            if not batch_complete:\n"
        "                return FindResult(\n"
        "                    items=(),",
    ),
    "M2_local_count_only_metadata": (
        "drive_tool/local.py",
        "                items=tuple(children),\n                inspected=entry_count,",
        "                items=tuple(children),\n                inspected=len(children),",
    ),
    "M3_local_read_b_plus_1": (
        "drive_tool/local.py",
        "while entry_count < max_entries:",
        "while entry_count <= max_entries:",
    ),
    "M4_local_complete_true_at_cap": (
        "drive_tool/local.py",
        "                    complete = False",
        "                    complete = True",
    ),
    "M5_search_ignore_scanfailure_inspected": (
        "drive_tool/search.py",
        "inspected += _validate_failure_inspected(failure, remaining_budget)",
        "_validate_failure_inspected(failure, remaining_budget)",
    ),
    "M6_search_scan_sibling_after_exhaust": (
        "drive_tool/search.py",
        "if remaining_budget <= 0:",
        "if remaining_budget < 0:",
    ),
    "M7_local_leak_fd_on_partial_return": (
        "drive_tool/local.py",
        "        finally:\n            try:\n                self._release_owned(owned)\n"
        "            except LocalStorageError as cleanup_exc:",
        "        finally:\n            try:\n                pass  # leaked\n"
        "            except LocalStorageError as cleanup_exc:",
    ),
    # --- reviewer's own probes against the findings ---
    "X1_set_truncated_when_skipped": (
        "drive_tool/search.py",
        "    return FindResult(\n"
        "        items=tuple(matches),\n"
        "        truncated=False,\n"
        "        reason=None,",
        "    return FindResult(\n"
        "        items=tuple(matches),\n"
        "        truncated=bool(skipped),\n"
        "        reason='skipped' if skipped else None,",
    ),
    "X2_add_scanfailure_error_check_at_depth": (
        "drive_tool/search.py",
        "                # A subdirectory that failed mid-scan is skipped; the walk only\n"
        "                # continues while budget remains.\n"
        "                skipped.append(dir_ref.file_id)",
        "                if not isinstance(failure.error, StorageError):\n"
        "                    raise StorageError('ScanFailure.error must be a StorageError')\n"
        "                skipped.append(dir_ref.file_id)",
    ),
}


def run_suite(root: Path):
    p = subprocess.run(
        [PY, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"],
        cwd=root, capture_output=True, text=True,
    )
    out = p.stdout + p.stderr
    fails = re.findall(r"^(?:FAIL|ERROR): (\S+)", out, flags=re.M)
    ran = re.search(r"Ran (\d+) tests", out)
    return p.returncode, (ran.group(1) if ran else "?"), sorted(set(fails))


def main():
    print(f"Interpreter: {PY}")
    for name, (rel, old, new) in MUTATIONS.items():
        dst = SCRATCH / name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(SRC, dst)
        try:
            edit(dst / rel, old, new)
        except SystemExit as e:
            print(f"[{name}] APPLY_FAILED: {e}")
            continue
        rc, ran, fails = run_suite(dst)
        caught = rc != 0
        status = "CAUGHT" if caught else "SURVIVED"
        print(f"[{name}] {status} (ran={ran}, rc={rc}); "
              f"failing={len(fails)} -> {fails[:6]}")


if __name__ == "__main__":
    main()
