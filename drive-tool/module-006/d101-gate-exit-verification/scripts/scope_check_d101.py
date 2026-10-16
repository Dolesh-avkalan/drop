#!/usr/bin/env python3
"""D101 scope proof: show that ONLY the gating helper differs from D097.

Parses both harnesses and compares every top-level definition's source block
verbatim.  Prints the set of differing definitions and confirms the frozen
stage runners / schedules / accounting / budgets are byte-identical.
"""
import ast
import hashlib
import json
import sys

D097 = "/scratch/work/d101/scripts/http_gate_d097.py"
D101 = "/scratch/work/d101/scripts/http_gate_d101.py"


def defs(path):
    src = open(path, "r", encoding="utf-8").read()
    lines = src.splitlines(keepends=True)
    tree = ast.parse(src)
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            seg = "".join(lines[node.lineno - 1:node.end_lineno])
            out[node.name] = hashlib.sha256(seg.encode()).hexdigest()
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    seg = "".join(lines[node.lineno - 1:node.end_lineno])
                    out["ASSIGN:" + t.id] = hashlib.sha256(seg.encode()).hexdigest()
    return out


a = defs(D097)
b = defs(D101)
names = sorted(set(a) | set(b))
differ = [n for n in names if a.get(n) != b.get(n)]
print("total top-level definitions/assigns:", len(names))
print("differing:", differ)
print()
for n in names:
    mark = "DIFF" if a.get(n) != b.get(n) else "same"
    print("  %-6s %s" % (mark, n))

frozen = [n for n in names if n not in differ]
ALLOWED = {"run_gate", "_aggregate_gate", "_run_guarded", "ASSIGN:REQUIRED_STAGES"}
confined = set(differ) <= ALLOWED and ALLOWED <= set(differ)
print()
print("frozen-identical count:", len(frozen))
print("gate-helper delta confined to:", sorted(differ))
print("delta is exactly the gating helper:", confined)

result = {"differing": differ, "allowed": sorted(ALLOWED),
          "delta_is_exactly_the_gate_helper": confined,
          "frozen_identical": frozen,
          "definitions": {n: ("DIFF" if a.get(n) != b.get(n) else "same") for n in names}}
with open("/scratch/work/d101/logs/d101_scope.json", "w", encoding="utf-8") as fh:
    json.dump(result, fh, indent=2, sort_keys=True)
sys.exit(0 if confined else 1)
