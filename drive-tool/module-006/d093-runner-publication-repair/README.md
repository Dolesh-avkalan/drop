# D093 — runner publication repair (relay artifacts)

This folder holds the artifacts D093 created while repairing the short/missing
D086 publication. The **complete verified bundle** is published under
`drive-tool/module-006/d093-complete-runner/`; the full report is
`drive-tool/module-006/d093-runner-publication-repair.md`.

## What happened

* D086's summary claimed a complete corrected bundle at
  `Dolesh-avkalan/drop @ 60b826e2ee52a6bc1f471dede75d50c19b880ae6`. The **actual
  git tree at that commit contained only** `IDENTITIES.md` +
  `sandbox/compile_checks.log` (plus the sibling `…-summary.md`). The runner
  bytes, the 18 negative-gate raw logs, the harness scripts, `HASHES`/`MANIFEST`
  and `exactbytes/` were **never published**.
* D093 reconstructed the two documented changes from the D082 bundle
  (`… @ 783d09d…`), re-verified the runner byte-for-byte, re-ran the 18 negative
  gates honestly on Python 3.12 and 3.11, and republished a complete bundle.

## Contents

| file | what it is |
| --- | --- |
| `runner_run_cloud_stress.py` | corrected runner (change 1) — sha256 `f58f61dc…` (**matches D086 doc exactly**) |
| `run_negatives.py` | reconstructed harness (change 2) — sha256 `96a34f07…` (behavioural reconstruction; D086-doc `543de9d4…` was never published) |
| `run_negatives_311.py` | identical harness with `PY="python3.11"` |
| `negatives_stdout_py312.txt` | raw 18-gate output, Python 3.12 (18/18 PASS) |
| `negatives_stdout_py311.txt` | raw 18-gate output, Python 3.11 (18/18 PASS) |
| `default_invocation.log` | full default runner run (dual-order confirmed=True, fail-closed exit 1) |
| `compile_checks.log` | py_compile 3.11 / 3.12 |
| `build_publish.py` | script that assembled the published bundle |
| `d093-complete-runner-HASHES.txt` | sha256 + bytes of every published bundle file |

## Honesty boundary

The runner correction reproduces the D086-documented hash **exactly**. The
harness correction is a **behavioural** reconstruction: the original corrected
bytes were never published and cannot be recovered, so this bundle does **not**
claim its hash equals the D086-documented one. No file that was not actually
produced is claimed.
