#!/usr/bin/env python3
"""Apply DeepSeek d020 blocks to the cloned repo. Dry-run by default; --write to apply."""
import json
import re
import sys
import os

REPO = "/scratch/work/drive-tool"
BLOCKS = "/scratch/work/d020_blocks.json"
WRITE = "--write" in sys.argv

with open(BLOCKS, encoding="utf-8") as f:
    blocks = json.load(f)

file_blocks = [b for b in blocks if b["kind"] == "FILE"]
replace_blocks = [b for b in blocks if b["kind"] == "REPLACE"]

# ---- 1. FILE blocks: write complete file contents ----
print("=== FILE blocks ===")
for b in file_blocks:
    dest = os.path.join(REPO, b["target"])
    print(f"  write {b['target']}  ({len(b['content'])} bytes)")
    if WRITE:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            f.write(b["content"])

# ---- 2. REPLACE blocks for local.py ----
local_path = os.path.join(REPO, "drive_tool/local.py")
with open(local_path, encoding="utf-8") as f:
    local_lines = f.read().split("\n")

def find_import_block(lines, first_line):
    for i, ln in enumerate(lines):
        if ln.strip() == first_line.strip() and ln.startswith("from "):
            # find closing paren line (starts with ")")
            j = i + 1
            while j < len(lines) and lines[j].strip() != ")":
                j += 1
            return i, j  # inclusive end index
    raise SystemExit(f"import block not found: {first_line!r}")

def find_def_block(lines, hint):
    m = re.match(r"\s*def\s+(\w+)\s*\(", hint)
    if not m:
        raise SystemExit(f"cannot parse hint {hint!r}")
    name = m.group(1)
    start = None
    for i, ln in enumerate(lines):
        dm = re.match(r"^(\s*)def\s+(\w+)\s*\(", ln)
        if dm and (name in dm.group(2) or dm.group(2) in name):
            start = i
            break
    if start is None:
        raise SystemExit(f"def not found for hint {hint!r} (name={name})")
    # find end: next non-blank line with indent <= 4 that is a def/@/class or top-level
    end = None
    for j in range(start + 1, len(lines)):
        ln = lines[j]
        if ln.strip() == "":
            continue
        if re.match(r"^    (def |@)", ln) or re.match(r"^[^\s]", ln):
            end = j
            break
    if end is None:
        end = len(lines)
    # strip trailing blank lines from the block
    k = end - 1
    while k > start and lines[k].strip() == "":
        k -= 1
    return start, k  # inclusive end index

print("\n=== REPLACE blocks (local.py) ===")
edits = []  # (start_idx, end_idx, new_text, hint)
for b in replace_blocks:
    hint = b["hint"]
    if hint.strip().startswith("from "):
        s, e = find_import_block(local_lines, hint)
    else:
        s, e = find_def_block(local_lines, hint)
    old = "\n".join(local_lines[s:e+1])
    print(f"  hint={hint!r}  lines[{s+1}..{e+1}]  old_bytes={len(old)}  new_bytes={len(b['content'])}")
    print(f"    first old line: {local_lines[s]!r}")
    print(f"    last  old line: {local_lines[e]!r}")
    edits.append((s, e, b["content"], hint))

# Apply edits from bottom to top
if WRITE:
    for s, e, new_text, hint in sorted(edits, key=lambda t: -t[0]):
        new_lines = new_text.rstrip("\n").split("\n")
        local_lines[s:e+1] = new_lines
    with open(local_path, "w", encoding="utf-8") as f:
        f.write("\n".join(local_lines))
    print("\nWROTE local.py")
else:
    print("\n(dry run - nothing written; pass --write to apply)")
