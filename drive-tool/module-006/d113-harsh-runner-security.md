# d113 (gemini)

- status: done
- chat: https://gemini.google.com/app/c9bc910cce2cfe16
- model: 4 argon (thinking: high)
- finished: 2026-10-16T04:21:13Z

## Question

Gemini review D113 exact actual outer harsh runner plus README security. ACCEPT_RUNNER_ONLY or concrete blockers; payload review separate, no package acceptance yet. Static TESTS_NOT_RUN. Preserve sandbox PARTIAL/skip honesty and exact disposable-host/containment/resource guards.

(input files: Dolesh-avkalan/drive-tool:tasks/d113-harsh-runner-security.txt@da9e74df9b10b32148fa7c7a04769412de835c98)

## Answer

Verdict: ACCEPT_RUNNER_ONLY (STATIC_REVIEW_ONLY / TESTS_NOT_RUN — applies strictly to run_harsh_d110.py and README.md; the whole package is not approved for target execution until Part 2 static security review of harsh_checks_d110.py is completed).

### 1. Static Security & Containment Verification (run_harsh_d110.py & README.md)

| Guard / Requirement | Status | Code Reference & Verification Detail |
| --- | --- | --- |
| Pinned Identities & Hashes | PASS | run_harsh_d110.py (f55f1ca20d79f576b32006e7a9745fd9baa4b2af8cf55e6b77cf62e541712c87, 32,554 B) pins repo Dolesh-avkalan/drive-tool at commit 337e4c713829af76615472eb47b81244ff399528 (lines 60–65) and payload harsh_checks_d110.py at SHA256 5599d32fa9df7918a8809098492284cebbce42b9141c61844c18c069fc17db43 and exact size 75545 B (lines 69–71). |
| Fail-Closed Source & Executable Verification | PASS | EXPECTED_BLOBS (lines 99–128) pins all 28 source and test files (10 drive_tool/*.py + 18 tests/test_*.py) by Git blob SHA-1, SHA-256, and exact byte length. verify_identities() (lines 292–337) walks the extracted tree before any execution, rejects symlinks (S_ISLNK) and non-regular files (not S_ISREG), verifies every expected file's size/SHA-1/SHA-256, and fails closed on any missing file, any unexpected file under drive_tool/ or tests/, or any unexpected executable/importable file (.py, .pyc, .pyo, .pth, .so, .sh, .bash, .pyw, sitecustomize.py, usercustomize.py) anywhere in the tree (lines 429–434). |
| Fail-Closed Payload Verification | PASS | verify_payload() (lines 340–348) checks existence, exact byte size (75545), and exact SHA-256 (5599d32f...) of harsh_checks_d110.py prior to invoking any stage subprocess (lines 436–442). |
| Safe Archive Acquisition & Extraction | PASS | acquire_archive() (lines 239–256) enforces MAX_ARCHIVE_BYTES = 50 MiB and bounded curl download timeouts. safe_extract() (lines 259–299) enforces MAX_MEMBERS = 2000, MAX_FILE_BYTES = 5 MiB, and MAX_TOTAL_UNCOMPRESSED = 64 MiB; rejects absolute paths, .. traversal segments, symlinks, hardlinks, and special files (fifos/devices); verifies os.path.realpath(target) stays inside dest; and streams regular file bytes manually with 0o600 file / 0o700 directory modes instead of calling tar.extractall(). |
| Fail-Closed Target Hostname Guard | PASS | EXPECTED_HOST = "instance-20261015-210506" (line 66). Lines 360–367 require both socket.gethostname() == EXPECTED_HOST and --confirm-disposable-host == EXPECTED_HOST to set host_verified = True; otherwise the runner aborts via SystemExit unless --sandbox is explicitly set. |
| Workspace /tmp Containment & Isolation | PASS | make_workspace() (lines 207–231) resolves os.path.realpath(base_dir) against os.path.realpath("/tmp"), creates a new unique directory d110-337e4c71-<pid>-<ms> with mode 0o700, verifies strict descendancy (ws.startswith(base + os.sep)) and 0o700 permissions, and never deletes retained evidence. build_env() (lines 234–246) confines TMPDIR/TEMP/TMP to <ws>/tmp, sets PYTHONDONTWRITEBYTECODE=1, PYTHONHASHSEED=0, PYTHONNOUSERSITE=1, and replaces PYTHONPATH with the verified src tree. |
| Disk Floor & Workspace Size Bounds | PASS | Enforces MIN_FREE_BYTES = 1 GiB on both base_real and / prior to archive download/extraction (lines 390–403). Post-run dir_allocated_size(ws) sums st_blocks * 512 across the workspace and fails the run if allocation exceeds MAX_WORKSPACE_BYTES = 192 MiB (lines 155–165, 494–502). |
| Process-Group, Time & Output Bounds | PASS | run() (lines 177–214) launches every child with start_new_session=True (pgid == pid). On timeout, _kill_group() sends SIGKILL strictly to os.getpgid(p.pid) (lines 168–174), preserving the runner, parent shell, and SSH session. Reader thread drains child stdout to EOF while capping buffered bytes at MAX_SUBPROCESS_OUTPUT = 8 MiB (preventing both OOM and pipe-full deadlocks). Per-stage timeout defaults to 120s (budget = wall - 15) and overall deadline defaults to 1080s (< 1200s outer operator timeout, lines 88–90, 446–450). |
| Stdlib-Only & Prohibited Operations | PASS | Uses Python stdlib only (argparse, hashlib, json, os, platform, shutil, signal, socket, stat, subprocess, sys, tarfile, tempfile, threading, time). Contains no root/sudo invocation, no filesystem mounts, no host-filling loops, no cloud/metadata API calls, no credentials, and no public network service bindings. |
| Sandbox PARTIAL/SKIPPED & Relaxation Honesty | PASS | Aggregation (lines 470–487, 510–524) maps any stage returning SKIPPED or PARTIAL (including resource_pressure when R2 is skipped due to baseline VmSize > 512 MiB) to aggregate PARTIAL with exit code 1—never PASS. In sandbox mode (mode == "sandbox"), even an all-pass run is rewritten to SANDBOX_PASS with exit code 1 (lines 520–523), and any relaxed /tmp or disk-floor setting is explicitly logged in summary["sandbox_relaxations"] (lines 395–399). |
| Diagnostic Separation & Save Semantics | PASS | Runner executes only the fixed 8-stage harsh allow-list (REQUIRED_STAGES, lines 73–75) in an isolated workspace without altering product code, existing unit tests, baseline D104 gates, or conservative uncertain-write save semantics. README.md accurately distinguishes expected adverse fault mappings (403/404/413, 503 busy, 503 unavailable) from true defects. |

### 2. Mandatory Operational Guardrails & Non-Blocking Hardening Notes

While no code changes are required to run_harsh_d110.py (preserving its pinned SHA256 f55f1ca20d79f576b32006e7a9745fd9baa4b2af8cf55e6b77cf62e541712c87), operator execution on the disposable target must adhere to the following constraints:

1. Never combine --sandbox with --confirm-disposable-host on target (lines 360–367, 383, 390):
In main(), mode is computed as "sandbox" if (args.sandbox and not host_verified) else "target", whereas make_workspace(..., allow_outside_tmp=args.sandbox) and floor = min(args.min_free_bytes, MIN_FREE_BYTES) if args.sandbox else MIN_FREE_BYTES inspect args.sandbox directly. Passing both --confirm-disposable-host=instance-20261015-210506 and --sandbox on the real target would evaluate mode = "target" while still permitting --base-dir outside /tmp and --min-free-bytes < 1 GiB. The target operator command in README.md (timeout 1200 python3 run_harsh_d110.py --confirm-disposable-host=instance-20261015-210506 --json d110_summary.json) omits --sandbox, --base-dir, --workdir, and --min-free-bytes, and must be used verbatim without sandbox flags.

2. Do not override --payload with a relative path (lines 345, 436, 456):
verify_payload(args.payload) validates args.payload relative to the caller's working directory, whereas run(cmd, src, penv, wall) executes [py, args.payload, ...] with cwd=src. Keep the default --payload (os.path.join(HERE, PAYLOAD_FILENAME), which is absolute) or pass an absolute path.

3. Minor observations (non-blocking):

- fh.truncate(BALLAST_BYTES) (lines 405–408) creates a sparse file (0 physical blocks allocated on tmpfs/ext4), so physical free-space enforcement relies on the pre-run 1 GiB statvfs floor (lines 390–403) and post-run 192 MiB st_blocks cap (lines 494–502).

- README.md prose refers to "26 pinned drive_tool/ + tests/ blob-sha1/sha256 set", whereas EXPECTED_BLOBS in run_harsh_d110.py pins all 28 files (10 under drive_tool/ + 18 under tests/).

### 3. Next Gate (Part 2 Required Before Target Execution)

- Runner & README Status: ACCEPT_RUNNER_ONLY

- Package / Target Execution Status: HOLD — Pending Part 2 static security review of harsh_checks_d110.py (5599d32fa9df7918a8809098492284cebbce42b9141c61844c18c069fc17db43) to verify child-only RLIMIT_AS <= 512 MiB, host MemAvailable floors (>= 1 GiB entry / 512 MiB abort), <= 4 nice-15 CPU children with RLIMIT_CPU, child-scoped RLIMIT_FSIZE/RLIMIT_NOFILE, loopback-only socket bindings, and stage-level file containment.
