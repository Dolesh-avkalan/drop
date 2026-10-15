"""d037 mutation harness: 3 new-protection mutations + the original 7 d034 ones.

Applies each mutation to a scratch copy of the corrected candidate and runs the
full suite; reports CAUGHT/SURVIVED and the failing tests.
"""
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


def edit(path: Path, old: str, new: str):
    text = path.read_text()
    if text.count(old) == 0:
        raise SystemExit(f"target not found in {path}: {old[:60]!r}")
    path.write_text(text.replace(old, new, 1))


# --- the three NEW protections (d035 corrections) ---
NEW = {
    "N1_remove_skipped_terminal_truncation": (
        "drive_tool/search.py",
        "    if skipped:\n"
        "        # A directory that could not be scanned means the subtree was not fully\n"
        "        # searched: an unqualified complete result must not be claimed.\n"
        "        return FindResult(\n"
        "            items=tuple(matches),\n"
        "            truncated=True,\n"
        "            reason=\"skipped\",\n"
        "            inspected=inspected,\n"
        "            skipped=tuple(skipped),\n"
        "        )\n\n",
        "",
    ),
    "N2_restore_root_only_error_validation": (
        "drive_tool/search.py",
        "                # Validate the reported error at EVERY depth, before deciding\n"
        "                # whether to unwrap it at the root or skip below the root: a\n"
        "                # malformed report is rejected loudly and is never converted\n"
        "                # into a skipped directory.\n"
        "                error = failure.error\n"
        "                if not isinstance(error, StorageError):\n"
        "                    raise StorageError(\n"
        "                        \"ScanFailure.error must be a StorageError, got \"\n"
        "                        f\"{type(error).__name__}\"\n"
        "                    )\n"
        "                if depth == 0:\n"
        "                    # The starting parent's own failure re-raises the original\n"
        "                    # error object (and its preserved cause).\n"
        "                    raise error\n",
        "                if depth == 0:\n"
        "                    if not isinstance(failure.error, StorageError):\n"
        "                        raise StorageError(\n"
        "                            \"ScanFailure.error must be a StorageError\"\n"
        "                        )\n"
        "                    raise failure.error\n",
    ),
    "N3_remove_post_yield_storage_wrapping": (
        "drive_tool/local.py",
        "        except StorageError as exc:\n"
        "            # Any StorageError escaping the scan body (for example from the\n"
        "            # metadata or stat seam) after a nonzero prefix is charged the same\n"
        "            # way; an existing ScanFailure is preserved without double wrapping\n"
        "            # and a pre-yield error is left unchanged.\n"
        "            wrapped = self._post_yield_storage_error(entry_count, exc)\n"
        "            if wrapped is exc:\n"
        "                raise\n"
        "            raise wrapped from exc\n",
        "",
    ),
}

# --- the original seven d034 protections ---
OLD = {
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
    for group, muts in (("NEW", NEW), ("OLD", OLD)):
        for name, (rel, old, new) in muts.items():
            dst = SCRATCH / name
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(SRC, dst)
            try:
                edit(dst / rel, old, new)
            except SystemExit as e:
                print(f"[{group}:{name}] APPLY_FAILED: {e}")
                continue
            rc, ran, fails = run_suite(dst)
            status = "CAUGHT" if rc != 0 else "SURVIVED"
            print(f"[{group}:{name}] {status} (ran={ran}, rc={rc}); "
                  f"failing={len(fails)} -> {fails[:8]}")


if __name__ == "__main__":
    main()
