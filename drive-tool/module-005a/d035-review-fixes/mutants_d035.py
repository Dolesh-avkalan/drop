"""d035 focused mutation checks in throwaway scratch copies.

Each mutant reverts exactly one of the three decided fixes. A mutant is
"caught" if at least one test in the combined suite fails.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SRC = Path("/scratch/repos/drive-tool")

MUTANTS = [
    ("X-a remove skipped terminal truncation (F-B, search.py)", "drive_tool/search.py",
     '    if skipped:\n'
     '        # A directory that could not be scanned means the subtree was not fully\n'
     '        # searched: an unqualified complete result must not be claimed.\n'
     '        return FindResult(\n'
     '            items=tuple(matches),\n'
     '            truncated=True,\n'
     '            reason="skipped",\n'
     '            inspected=inspected,\n'
     '            skipped=tuple(skipped),\n'
     '        )\n\n',
     ''),
    ("X-b restore root-only failure.error validation (F-A, search.py)", "drive_tool/search.py",
     '                error = failure.error\n'
     '                if not isinstance(error, StorageError):\n'
     '                    raise StorageError(\n'
     '                        "ScanFailure.error must be a StorageError, got "\n'
     '                        f"{type(error).__name__}"\n'
     '                    )\n'
     '                if depth == 0:\n'
     '                    # The starting parent\'s own failure re-raises the original\n'
     '                    # error object (and its preserved cause).\n'
     '                    raise error\n',
     '                if depth == 0:\n'
     '                    if not isinstance(failure.error, StorageError):\n'
     '                        raise StorageError(\n'
     '                            "ScanFailure.error must be a StorageError"\n'
     '                        )\n'
     '                    raise failure.error\n'),
    ("X-c remove generic post-yield StorageError wrapping (F-C, local.py)", "drive_tool/local.py",
     '        except StorageError as exc:\n'
     '            # Any StorageError escaping the scan body (for example from the\n'
     '            # metadata or stat seam) after a nonzero prefix is charged the same\n'
     '            # way; an existing ScanFailure is preserved without double wrapping\n'
     '            # and a pre-yield error is left unchanged.\n'
     '            wrapped = self._post_yield_storage_error(entry_count, exc)\n'
     '            if wrapped is exc:\n'
     '                raise\n'
     '            raise wrapped from exc\n'
     '        finally:\n',
     '        finally:\n'),
]


def run_suite(root: Path, py: str) -> list[str]:
    proc = subprocess.run(
        [py, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=root, capture_output=True, text=True,
    )
    return sorted({
        line.split(" ", 2)[2].split(" ")[0]
        for line in (proc.stderr + proc.stdout).splitlines()
        if line.startswith("FAIL:") or line.startswith("ERROR:")
    })


def main() -> None:
    py = sys.argv[1] if len(sys.argv) > 1 else "python3"
    for name, rel, old, new in MUTANTS:
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "repo"
            shutil.copytree(SRC, dest)
            target = dest / rel
            text = target.read_text()
            if text.count(old) != 1:
                print(f"{name}: SETUP FAIL (match count {text.count(old)})")
                continue
            target.write_text(text.replace(old, new))
            failing = run_suite(dest, py)
            print(f"{name}: {'CAUGHT' if failing else 'SURVIVED'}")
            for t in failing:
                print(f"    caught by: {t}")


if __name__ == "__main__":
    main()
