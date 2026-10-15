#!/usr/bin/env python3
"""Parse DeepSeek's d020 output into FILE blocks and REPLACE blocks."""
import json
import re
import sys

SRC = "/scratch/work/inputs/d020-deepseek-implementation.md"

with open(SRC, "r", encoding="utf-8") as f:
    lines = f.read().split("\n")

# lines list: index 0 == file line 1

def find_fence_blocks():
    """Yield (marker_line_idx, marker_kind, target, hint_line, content)."""
    blocks = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        m_file = re.match(r"^FILE:\s+(\S+)\s*$", line)
        m_repl = re.match(r"^REPLACE IN\s+(\S+):\s*$", line)
        if m_file or m_repl:
            if m_file:
                kind = "FILE"
                target = m_file.group(1)
                hint = None
                j = i + 1
            else:
                kind = "REPLACE"
                target = m_repl.group(1)
                # next non-empty line is the hint (first line of definition)
                j = i + 1
                while j < n and lines[j].strip() == "":
                    j += 1
                hint = lines[j]
                j = j + 1
            # skip blanks to the opening fence
            while j < n and lines[j].strip() == "":
                j += 1
            if j >= n or not lines[j].startswith("```"):
                raise SystemExit(f"no fence after marker at line {i+1}: {line!r}")
            fence_open = lines[j]
            k = j + 1
            content_lines = []
            while k < n and not lines[k].startswith("```"):
                content_lines.append(lines[k])
                k += 1
            if k >= n:
                raise SystemExit(f"unterminated fence for {target}")
            fence_close = lines[k]
            content = "\n".join(content_lines) + "\n"
            blocks.append({
                "kind": kind,
                "target": target,
                "hint": hint,
                "fence_open": fence_open,
                "fence_close": fence_close,
                "marker_line": i + 1,
                "content": content,
            })
            i = k + 1
        else:
            i += 1
    return blocks


blocks = find_fence_blocks()
print(f"Found {len(blocks)} blocks:")
for b in blocks:
    print(f"  line {b['marker_line']:5d}  {b['kind']:7s}  {b['target']:28s} "
          f"hint={b['hint']!r}  bytes={len(b['content'])}  "
          f"fence={b['fence_open']}")

# Save to JSON for the apply step
with open("/scratch/work/d020_blocks.json", "w", encoding="utf-8") as f:
    json.dump(blocks, f, indent=1)
print("wrote /scratch/work/d020_blocks.json")
