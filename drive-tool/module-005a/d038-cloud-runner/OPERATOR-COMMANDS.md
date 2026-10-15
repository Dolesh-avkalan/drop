# d038 — operator commands (director, directortemp)

Preparation bundle only. The author does **not** run these on the target, and
claims no target result. Independent candidate execution (D037) is still
finishing on the local host.

Target: existing `directortemp` (Ubuntu 26.04.1 / kernel 7.0.0-1011-gcp /
Python 3.14.4), reached through the director's existing Cloud Shell SSH
connection. The runner is for director orchestration only.

## 1. Preferred: download the pinned archive on the target

```
# from the directory that holds run_cloud_validation.py and kernel_checks.py
timeout 5580 python3 run_cloud_validation.py
```

- Creates a fresh unique workspace `/tmp/d038-e88c9c79-<uniq>`.
- Prints `RESULT: PASS` or `RESULT: FAIL (fail-closed)`; exit `0` only on pass.
- Keeps the workspace; prints the exact `rm -rf <workspace>` cleanup line.

## 2. No egress on the target: pre-stage the archive

On a host with egress:

```
curl -L -o drive-tool-e88c9c79.tar.gz \
  https://codeload.github.com/Dolesh-avkalan/drive-tool/tar.gz/e88c9c79fdc27057622d44ba51e008f2e4ea4f4f
sha256sum drive-tool-e88c9c79.tar.gz   # compare to the value in MANIFEST.md if you have one
```

Then, on the target, copy the two scripts plus the archive into one directory
and run:

```
timeout 5580 python3 run_cloud_validation.py --archive /path/to/drive-tool-e88c9c79.tar.gz
```

## 3. Bounding the run

The runner bounds each sub-step itself; the director should still wrap the whole
invocation in one outer wall-clock timeout (recommended **5580 s**, the
worst-case sum of the default per-step budgets). Adjust the per-step budgets
only if you also adjust the outer timeout:

```
python3 run_cloud_validation.py \
  --download-timeout 180 --suite-timeout 300 --check-timeout 120
```

## 4. Reading the evidence

Inside `<workspace>/logs/`:

- `summary.json` — machine-readable result (suite counts, per-check labels,
  failures, recommended overall timeout).
- `identity.txt` — the 18 pinned files and any mismatch.
- `suite_<py>.out` / `check_<py>_<name>.out` — full stdout/stderr/exits.
- `MANIFEST.md` — SHA-256/length manifest of the whole workspace.

## 5. Cleanup

Run only the exact line the runner prints, and nothing wider:

```
rm -rf /tmp/d038-e88c9c79-<uniq>
```

## Constraints honoured

- No package installation, no service change, no reboot, no mounts.
- Writes stay inside the unique workspace (TMPDIR set inside it, bytecode
  disabled); ≤ 50 MiB new workspace files; probe fixtures ≤ 1 MiB.
- The implementation is never edited; kernel support is never mocked.
- No environment secret is read or printed; no private paths or browser
  profiles are enumerated.
