import os, re, shutil, subprocess, sys

PRISTINE = "/scratch/repos/drive-tool"
MUT = "/scratch/work/mut"

if os.path.exists(MUT):
    shutil.rmtree(MUT)
shutil.copytree(PRISTINE, MUT)

FILES = ["drive_tool/local.py", "drive_tool/search.py", "drive_tool/listing.py"]
pristine_text = {f: open(os.path.join(PRISTINE, f), encoding="utf-8").read() for f in FILES}

COUNT_BLOCK = '''                    entry_count += 1
                    if entry_count > effective_limit:
                        raise EnumerationLimitError(
                            effective_limit,
                            f"directory {parent.file_id!r} exceeds limit of "
                            f"{effective_limit} entries",
                        )
'''
NAME_LINE = '                    name = entry.name\n'
FILTER_BODY = '''                    if (
                        name in ("", ".", "..")
                        or "/" in name
                        or "\\\\" in name
                        or "\\x00" in name
                    ):
                        continue
'''
ENTRY_CHECK = COUNT_BLOCK + NAME_LINE
NAME_FILTER = NAME_LINE + FILTER_BODY
FILTER_END = '''                    # Special entries (FIFOs, sockets, device nodes) are omitted.
        except OSError as exc:
'''
CHECK_AFTER_LOOP = '''                    # Special entries (FIFOs, sockets, device nodes) are omitted.
            if entry_count > effective_limit:
                raise EnumerationLimitError(
                    effective_limit,
                    f"directory {parent.file_id!r} exceeds limit of "
                    f"{effective_limit} entries",
                )
        except OSError as exc:
'''

# each mutation: (id, file, [(old,new), ...])
MUTATIONS = [
    ("M1 limit-check-moved-after-scan-loop", "drive_tool/local.py",
     [(ENTRY_CHECK, '                    entry_count += 1\n                    name = entry.name\n'),
      (FILTER_END, CHECK_AFTER_LOOP)]),

    ("M2 counting-moved-below-odd-name-filter", "drive_tool/local.py",
     [(COUNT_BLOCK + NAME_FILTER, NAME_FILTER + COUNT_BLOCK)]),

    ("M3 parent_fd-not-added-to-owned", "drive_tool/local.py",
     [('''                if parent_fd != root_fd:
                    owned.append(
                        (parent_fd, f"parent directory of {parent.file_id!r}")
                    )
''',
       '''                if parent_fd != root_fd:
                    pass
''')]),

    ("M4a drop-or-more_dirs_queued (search.find)", "drive_tool/search.py",
     [("                        if more_entries_in_dir or more_dirs_queued:\n",
       "                        if more_entries_in_dir:\n")]),

    ("M4b drop-more_dirs_at_this_level (search.find)", "drive_tool/search.py",
     [('''                        more_dirs_queued = (
                            more_dirs_at_this_level or bool(next_level_dirs)
                        )
''',
       '''                        more_dirs_queued = bool(next_level_dirs)
''')]),

    ("M5 list_page-always-passes-max_entries", "drive_tool/listing.py",
     [('''        if max_entries is None:
            items = list(self._adapter.list_children(parent))
        else:
            items = list(
                self._adapter.list_children(parent, max_entries=max_entries)
            )
''',
       '''        items = list(
            self._adapter.list_children(parent, max_entries=max_entries)
        )
''')]),
]

def restore():
    for f in FILES:
        with open(os.path.join(MUT, f), "w", encoding="utf-8") as fh:
            fh.write(pristine_text[f])

def run_proofs(py="python3.12"):
    r = subprocess.run([py, "-m", "unittest", "tests.test_enumeration_proofs", "-v"],
                       cwd=MUT, capture_output=True, text=True)
    out = r.stdout + r.stderr
    statuses = {}
    for m in re.finditer(r"^(test_\w+) \([^)]+\) \.\.\. (ok|FAIL|ERROR|skipped.*)$", out, re.M):
        statuses[m.group(1)] = m.group(2)
    return statuses, out

print("== baseline (no mutation) ==")
restore()
base, _ = run_proofs()
print("  all pass:", all(v == "ok" for v in base.values()), "|", sorted(base))
print()

for mid, f, reps in MUTATIONS:
    restore()
    path = os.path.join(MUT, f)
    txt = open(path, encoding="utf-8").read()
    ok = True
    for old, new in reps:
        if old not in txt:
            print(f"!! mutation {mid}: OLD NOT FOUND in {f}"); ok = False; break
        txt = txt.replace(old, new, 1)
    if not ok:
        continue
    open(path, "w", encoding="utf-8").write(txt)
    chk = subprocess.run([sys.executable, "-c", f"import ast;ast.parse(open({path!r}).read())"],
                         capture_output=True, text=True)
    if chk.returncode != 0:
        print(f"!! mutation {mid}: syntax error: {chk.stderr}"); continue
    st, out = run_proofs()
    failing = sorted(t for t, s in st.items() if s in ("FAIL", "ERROR"))
    print(f"== {mid} ==")
    print("  failing:", failing if failing else "NONE (proof gap!)")
    print()

restore()
print("restored pristine sources in scratch copy")
