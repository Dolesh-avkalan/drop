#!/usr/bin/env python3
"""Assemble the d093-complete-runner publication bundle from the verified run."""
import hashlib, json, os, shutil, subprocess

WORK = "/scratch/work/d093"
SRC = os.path.join(WORK, "bundle")
OUT = "/scratch/work/publish/drive-tool/module-006/d093-complete-runner"

def sh(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()

def cp(a, b):
    os.makedirs(os.path.dirname(b), exist_ok=True)
    shutil.copy2(a, b)

if os.path.exists(OUT):
    shutil.rmtree(OUT)
os.makedirs(OUT)

# 1. bundle payload (runner, originals, negatives, sandbox)
for sub in ("runner", "originals", "negatives", "sandbox"):
    for root, dirs, files in os.walk(os.path.join(SRC, sub)):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if f.endswith(".pyc"):
                continue
            s = os.path.join(root, f)
            rel = os.path.relpath(s, SRC)
            cp(s, os.path.join(OUT, rel))

# 2. raw gate stdout (py3.12 + py3.11), replacing the stale D082 copy
cp(os.path.join(WORK, "negatives_stdout_py312.txt"), os.path.join(OUT, "negatives", "logs_stdout.txt"))
cp(os.path.join(WORK, "negatives_stdout_py311.txt"), os.path.join(OUT, "negatives", "logs_stdout_py311.txt"))
cp(os.path.join(WORK, "compile_checks.log"), os.path.join(OUT, "sandbox", "compile_checks.log"))

# 3. gates/ — the asc PASS / desc FAIL dual-order evidence
wl = os.path.join(OUT, "sandbox", "workspace_logs")
cp(os.path.join(wl, "dual_order_asc.out"), os.path.join(OUT, "gates", "dual_order_asc.out"))
cp(os.path.join(wl, "dual_order_desc.out"), os.path.join(OUT, "gates", "dual_order_desc.out"))
cp(os.path.join(wl, "readdir_order_confirmation.json"), os.path.join(OUT, "gates", "readdir_order_confirmation.json"))

# 4. exactbytes/
cp(os.path.join(OUT, "runner", "run_cloud_stress.py"), os.path.join(OUT, "exactbytes", "runner_run_cloud_stress.py"))
cp(os.path.join(OUT, "negatives", "run_negatives.py"), os.path.join(OUT, "exactbytes", "negatives_run_negatives.py"))

# 5. hashes/ + root manifests
def walk_files(root):
    out = []
    for r, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if f.endswith(".pyc"):
                continue
            out.append(os.path.relpath(os.path.join(r, f), root))
    return sorted(out)

def gen_manifest(root, skip=("hashes/", "MANIFEST.md", "HASHES.txt")):
    rows = []
    for rel in walk_files(root):
        if rel.startswith(skip[0]) or rel in ("MANIFEST.md", "HASHES.txt"):
            continue
        p = os.path.join(root, rel)
        rows.append((rel, os.path.getsize(p), sh(p)))
    return rows

rows = gen_manifest(OUT)
os.makedirs(os.path.join(OUT, "hashes"), exist_ok=True)
with open(os.path.join(OUT, "hashes", "d093-complete-runner-HASHES.txt"), "w") as fh:
    for rel, n, h in rows:
        fh.write(f"{h}  {n:>8}  {rel}\n")
with open(os.path.join(OUT, "hashes", "d093-complete-runner-MANIFEST.md"), "w") as fh:
    fh.write("# d093-complete-runner — sha256 + byte manifest\n\n")
    fh.write("| bytes | sha256 | path |\n| --- | --- | --- |\n")
    for rel, n, h in rows:
        fh.write(f"| {n} | `{h}` | `{rel}` |\n")
# root copies
shutil.copy2(os.path.join(OUT, "hashes", "d093-complete-runner-HASHES.txt"), os.path.join(OUT, "HASHES.txt"))
shutil.copy2(os.path.join(OUT, "hashes", "d093-complete-runner-MANIFEST.md"), os.path.join(OUT, "MANIFEST.md"))

print("assembled:", OUT)
print("files:", len(rows))
print("runner sha256:", sh(os.path.join(OUT, "runner", "run_cloud_stress.py")))
print("harness sha256:", sh(os.path.join(OUT, "negatives", "run_negatives.py")))
