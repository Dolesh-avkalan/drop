#!/usr/bin/env python3
"""Emit MANIFEST.md + HASHES.txt for a directory tree (self-excluded)."""
import hashlib
import os
import sys
import time

root = sys.argv[1]
bundle_name = sys.argv[2]

EXCLUDE = {"MANIFEST.md", "HASHES.txt"}
rows = []
for dp, dns, fns in os.walk(root):
    dns[:] = sorted(d for d in dns if d != "__pycache__")
    for fn in sorted(fns):
        full = os.path.join(dp, fn)
        rel = os.path.relpath(full, root)
        if rel in EXCLUDE:
            continue
        data = open(full, "rb").read()
        rows.append((rel, len(data), hashlib.sha256(data).hexdigest()))
rows.sort()

lines = [f"# {bundle_name} manifest", "",
         f"Bundle: {bundle_name}/",
         f"generated: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}", "",
         "`HASHES.txt` and this `MANIFEST.md` are excluded from the table (mutual self-reference).", "",
         "| file | bytes | sha256 |", "| --- | --- | --- |"]
for rel, sz, h in rows:
    lines.append(f"| `{rel}` | {sz} | `{h}` |")
open(os.path.join(root, "MANIFEST.md"), "w").write("\n".join(lines) + "\n")

with open(os.path.join(root, "HASHES.txt"), "w") as fh:
    for rel, sz, h in rows:
        fh.write(f"{h}  {sz}  {rel}\n")
print(f"{bundle_name}: {len(rows)} files hashed")
