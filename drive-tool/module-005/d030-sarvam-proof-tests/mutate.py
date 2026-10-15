#!/usr/bin/env python3
"""Apply each MODULE-005 mutation to a scratch copy and record failing tests."""
import os
import shutil
import subprocess
import sys

BASE = "/scratch/work/mutbase"
RUN = "/scratch/work/mut_run"

# Each mutation: (id, label, d029_ref, file, old, new)
MUTATIONS = [
    (
        "M1",
        "Drop O_NOFOLLOW from intermediate directory traversal",
        "nit1",
        "drive_tool/local.py",
        """        dir_flags = _dir_open_flags()
        current_fd = root_fd""",
        """        dir_flags = os.O_RDONLY | os.O_NONBLOCK
        current_fd = root_fd""",
    ),
    (
        "M2",
        "Accept a symlink strictly inside parts[:-1] (follow + do not reject)",
        "nit1",
        "drive_tool/local.py",
        [
            (
                """        dir_flags = _dir_open_flags()
        current_fd = root_fd""",
                """        dir_flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
        current_fd = root_fd""",
            ),
            (
                """                        if stat.S_ISLNK(st.st_mode):
                            raise UnsafePathError(
                                f"symlink encountered at {part!r} for {file_id!r}"
                            )
""",
                "",
            ),
        ],
    ),
    (
        "M3",
        "check-then-rename instead of atomic link for overwrite=False",
        "nit2 / extra",
        "drive_tool/local_write.py",
        """                    self._os_link(
                        tmp_name,
                        name,
                        src_dir_fd=parent_fd,
                        dst_dir_fd=parent_fd,
                        follow_symlinks=False,
                    )""",
        """                    try:
                        self._adapter._os_stat_nofollow(name, dir_fd=parent_fd)
                    except OSError as _exc:
                        if _exc.errno != errno.ENOENT:
                            raise
                    else:
                        raise AlreadyExistsError(
                            f"entry {name!r} already exists"
                        )
                    self._os_rename(
                        tmp_name,
                        name,
                        src_dir_fd=parent_fd,
                        dst_dir_fd=parent_fd,
                    )""",
    ),
    (
        "M4",
        "Drop O_CLOEXEC from the temp-file open flags",
        "nit3 / extra",
        "drive_tool/local_write.py",
        """            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0)
        )""",
        """            | os.O_NOFOLLOW
        )""",
    ),
    (
        "M5",
        "Use 8 hex characters in the temp name (token_hex(4))",
        "nit3 / extra",
        "drive_tool/local_write.py",
        "            candidate = TEMP_PREFIX + secrets.token_hex(8)",
        "            candidate = TEMP_PREFIX + secrets.token_hex(4)",
    ),
    (
        "M6",
        "Move tmp_on_disk = False back after the post-link unlink",
        "nit4 / extra",
        "drive_tool/local_write.py",
        """                tmp_on_disk = False
                try:
                    self._os_unlink(tmp_name, dir_fd=parent_fd)
                except OSError as exc:
                    raise LocalStorageError(
                        f"failed to unlink temp name after linking "
                        f"{name!r}: {exc}"
                    ) from exc""",
        """                try:
                    self._os_unlink(tmp_name, dir_fd=parent_fd)
                except OSError as exc:
                    raise LocalStorageError(
                        f"failed to unlink temp name after linking "
                        f"{name!r}: {exc}"
                    ) from exc
                tmp_on_disk = False""",
    ),
    (
        "M7",
        "Check closed state before source mismatch (_check_source_and_state)",
        "nit5",
        "drive_tool/local.py",
        """        if ref.source_id != self._source_id:
            raise SourceMismatchError(
                f"ref source_id {ref.source_id!r} does not match "
                f"adapter source_id {self._source_id!r}"
            )
        if self._closed or self._root_fd is None:
            raise AdapterClosedError(
                f"LocalAdapter for source {self._source_id!r} is closed"
            )""",
        """        if self._closed or self._root_fd is None:
            raise AdapterClosedError(
                f"LocalAdapter for source {self._source_id!r} is closed"
            )
        if ref.source_id != self._source_id:
            raise SourceMismatchError(
                f"ref source_id {ref.source_id!r} does not match "
                f"adapter source_id {self._source_id!r}"
            )""",
    ),
    (
        "M8",
        "Let mkdir validate the name before checking the source",
        "nit5 / extra",
        "drive_tool/local_write.py",
        """        root_fd = self._adapter._check_source_and_state(parent)
        parts = _parse_file_id(parent.file_id)
        self._reject_temp_in_parent(parts)
        self._validate_name(name)
        if not isinstance(exist_ok, bool):""",
        """        parts = _parse_file_id(parent.file_id)
        self._reject_temp_in_parent(parts)
        self._validate_name(name)
        root_fd = self._adapter._check_source_and_state(parent)
        if not isinstance(exist_ok, bool):""",
    ),
]


def run_suite(interp=None):
    interp = interp or os.environ.get("MUT_INTERP", "python3.12")
    proc = subprocess.run(
        [interp, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=RUN,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout + proc.stderr


def failing_tests(log):
    fails = []
    for line in log.splitlines():
        s = line.strip()
        if s.startswith("FAIL: ") or s.startswith("ERROR: "):
            fails.append(s.split(":", 1)[1].strip())
    return fails


def summary_line(log):
    for line in log.splitlines():
        if line.startswith("Ran ") or line.startswith("OK") or line.startswith("FAILED"):
            pass
    ran = [l for l in log.splitlines() if l.startswith("Ran ")]
    tail = [l for l in log.splitlines() if l.startswith(("OK", "FAILED"))]
    return (ran[-1] if ran else "?"), (tail[-1] if tail else "?")


results = []
for mid, label, ref, rel, *rest in MUTATIONS:
    pairs = rest[0] if len(rest) == 1 else [(rest[0], rest[1])]
    if os.path.isdir(RUN):
        shutil.rmtree(RUN)
    shutil.copytree(BASE, RUN, ignore=shutil.ignore_patterns("__pycache__"))
    path = os.path.join(RUN, rel)
    src = open(path).read()
    ok = True
    for old, new in pairs:
        if src.count(old) != 1:
            results.append(
                (mid, label, ref, "APPLY-ERROR", f"pattern count={src.count(old)} for {old[:40]!r}")
            )
            ok = False
            break
        src = src.replace(old, new, 1)
    if not ok:
        continue
    open(path, "w").write(src)
    rc, log = run_suite()
    fails = failing_tests(log)
    ran, tail = summary_line(log)
    results.append((mid, label, ref, f"{ran}; {tail}; exit={rc}", fails))

print("=" * 100)
for mid, label, ref, status, fails in results:
    print(f"\n{mid} [{ref}] {label}")
    print(f"   {status}")
    if isinstance(fails, list):
        if fails:
            for f in fails:
                print(f"     FAIL -> {f}")
        else:
            print("     NO TEST FAILED  <-- UNCAUGHT MUTATION")
    else:
        print(f"     {fails}")

# machine-readable dump
import json
with open("/scratch/work/mutation_results_" + os.environ.get("MUT_TAG","py312") + ".json", "w") as fh:
    json.dump(
        [{"id": m, "label": l, "ref": r, "status": s, "fails": f} for m, l, r, s, f in results],
        fh,
        indent=2,
    )
print("\nwrote /scratch/work/mutation_results_" + os.environ.get("MUT_TAG","py312") + ".json")
