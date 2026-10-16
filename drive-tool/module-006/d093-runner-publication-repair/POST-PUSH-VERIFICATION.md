# D093 post-push verification — actual git file list and bytes

Verification performed **after** the `relay: d093` push, by re-reading the
repository (not from local state).

## Method

1. `GITHUB_GET_REPOSITORY_CONTENT` on each published directory at `ref=main`
   lists the exact entries and their git blob SHAs.
2. Each git blob SHA is content-addressed, so it was compared against the git
   blob SHA computed locally from the verified file
   (`sha1("blob <len>\0" + bytes)`). A match proves the pushed bytes are
   **byte-identical** to the local verified file — hence also identical to that
   file's sha256.

## Published file list (verified present at main)

`drive-tool/module-006/`

    d093-runner-publication-repair.md
    d093-complete-runner/HASHES.txt
    d093-complete-runner/IDENTITIES.md
    d093-complete-runner/MANIFEST.md
    d093-complete-runner/PUBLICATION-NOTES.md
    d093-complete-runner/RECONSTRUCTION-NOTES.md
    d093-complete-runner/gates/dual_order_asc.out
    d093-complete-runner/gates/dual_order_desc.out
    d093-complete-runner/gates/readdir_order_confirmation.json
    d093-complete-runner/negatives/logs_stdout.txt
    d093-complete-runner/negatives/logs_stdout_py311.txt
    d093-complete-runner/negatives/logs/negatives_results.json
    d093-complete-runner/negatives/logs_py311/negatives_results.json
    d093-complete-runner/negatives/run_negatives.py
    d093-complete-runner/negatives/run_negatives_311.py
    d093-complete-runner/runner/run_cloud_stress.py
    d093-complete-runner/sandbox/compile_checks.log
    d093-complete-runner/sandbox/default_invocation.log
    d093-complete-runner/sandbox/workspace_logs/_dual_order_repro.py
    d093-complete-runner/sandbox/workspace_logs/dual_order_asc.out
    d093-complete-runner/sandbox/workspace_logs/dual_order_desc.out
    d093-complete-runner/sandbox/workspace_logs/env_after.json
    d093-complete-runner/sandbox/workspace_logs/env_before.json
    d093-complete-runner/sandbox/workspace_logs/identity.txt
    d093-complete-runner/sandbox/workspace_logs/readdir_order_confirmation.json
    d093-complete-runner/sandbox/workspace_logs/stress_edges.out
    d093-complete-runner/sandbox/workspace_logs/stress_smoke.out
    d093-complete-runner/sandbox/workspace_logs/stress_soak.out
    d093-complete-runner/sandbox/workspace_logs/summary.json
    d093-runner-publication-repair/README.md
    d093-runner-publication-repair/build_publish.py
    d093-runner-publication-repair/d093-complete-runner-HASHES.txt

## Byte verification of the corrected sources

| pushed file | git blob sha1 (GitHub) | git blob sha1 (local) | match | local sha256 |
| --- | --- | --- | --- | --- |
| `runner/run_cloud_stress.py` | `60c6b8280f20a1916d6e8c6ba735338b4d49149a` | `60c6b8280f20a1916d6e8c6ba735338b4d49149a` | YES | `f58f61dced9b8df2d92e710bc654190dc32f92f0e426d0f499386e5b84cf57f2` (== D086 doc) |
| `negatives/run_negatives.py` | `b40411538453daf18343a4bb981cb8cea1d81f8a` | `b40411538453daf18343a4bb981cb8cea1d81f8a` | YES | `96a34f07d3e14ca315a64a62243ed5c37acd9da37a6a41d2d7246ac1aa3670bc` |
| `negatives/run_negatives_311.py` | `b37b6edef53900cff52c514bc32561d83a0d643d` | `b37b6edef53900cff52c514bc32561d83a0d643d` | YES | `e93699f0b743227b209eb7cc4085e03ddf82fbc0aca6ce3998388860eab43e68` |

## Scope note (no over-claim)

The report `d093-runner-publication-repair.md` §8 describes the **full local
bundle**. The repository copy under `d093-complete-runner/` publishes the
new/changed artifacts and all raw evidence; the unchanged duplicate copies
(`runner/stress_checks.py`, `runner/README.md`, `originals/`, `exactbytes/`) and
the two very large suite logs are **not duplicated there** — see
`d093-complete-runner/PUBLICATION-NOTES.md`. `MANIFEST.md`/`HASHES.txt` list
**exactly** the files present; no absent file is claimed.
