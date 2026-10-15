# d065 (gemini)

- status: done
- chat: https://gemini.google.com/app/0ac662b6db80fa62
- model: 4 argon (thinking: high)
- finished: 2026-10-15T21:29:24Z

## Question

Gemini, independently review exact D063 runner security/containment and design separate harsh-fault test extension ONLY for designated disposable box, per D065. Source supplied inline because retrieval fallback. Baseline ACCEPT/CHANGES REQUIRED separately, concrete blockers and security limits, TESTS_NOT_RUN. No code/tests/deploy; Sarvam handles implementation. Directory-order-sensitive suite finding must not be hidden by filesystem selection.

(input files: Dolesh-avkalan/drive-tool:tasks/d065-runner-security-review.txt@d905b4853afca2a1e3b3cd649a9629e8e8e47674)

## Answer

EXECUTION STATUS: TESTS_NOT_RUN (Static security audit and architectural specification only; no code written, no tests executed, no deployment performed.)
DESIGNATED DISPOSABLE TARGET: instance-20261015-210506 ONLY (2 vCPU / 4 GiB RAM / 10 GiB disk, Debian, Python 3.13). All other hosts, local PCs, browser sessions, and credential stores remain strictly off-limits.
D063 BASELINE RUNNER VERDICT: CHANGES REQUIRED (Host-safe under strict no-argument default /tmp execution on the disposable box, but blocked from unqualified baseline acceptance by three concrete defects: B1 directory-order failure masking/coupling, B2 non-fail-closed extra files in verify_identities(), and B3 unconstrained --base-dir/--workdir CLI paths).

## 1. D063 Pinned Runner Security & Containment Review

Reviewed Artifact: SOURCE PIN dropa0f5368d62623c5ed939915275f7732cda74011b (runner/run_cloud_stress.py, runner/stress_checks.py, runner/README.md) targeting candidate Dolesh-avkalan/drive-tool @ b7f8d17b9dcc4aec68d54b38f994290e05264e67.

### 1.1 Guard & Containment Verification Matrix

| Audit Dimension | Code Location | Observed Implementation | Verdict |
| --- | --- | --- | --- |
| Synthetic /tmp Workspace Only | run_cloud_stress.py:276-288, 233-241 | Default invocation creates /tmp/d063-b7f8d17b-<uniq> via tempfile.mkdtemp, sets TMPDIR=<ws>/tmp, D063_WORKSPACE=<ws>, and PYTHONDONTWRITEBYTECODE=1. However, --base-dir and --workdir accept arbitrary paths without enforcing a /tmp/ prefix check. | PARTIAL (B3) |
| No Credentials / Cloud API / Service Changes | Both files (full AST scan) | Uses Python stdlib only. Zero reads of ~/.ssh, ~/.config, /etc/shadow, environment secrets, or GCP metadata endpoints (169.254.169.254). Zero package installs, service mutations, mount calls, or listening sockets. Outbound network is a single HTTPS GET to codeload.github.com. | PASS |
| No Unrelated Host Paths Touched | stress_checks.py:79-111, run_cloud_stress.py:134-169 | Read-only host inspection is strictly limited to /proc/meminfo, /etc/os-release, /proc/self/status, and /proc/self/fd. Synthetic outside probe (<ws>/outside/secret.txt) and symlink (<ws>/roots/r*/link_out) reside strictly inside <ws>. | PASS |
| Source & Payload Identity Pinning | run_cloud_stress.py:32-65, 111-131, 290-298, 328-341 | Verifies stress_checks.py against STRESS_CHECKS_SHA256 before preflight. Verifies all 26 known source/test files against EXPECTED_BLOBS (git blob SHA-1) before execution. Defect: verify_identities() logs unexpected extra files as a note: without failing closed, and the archive .tar.gz SHA-256 is not pinned. | FAIL (B2) |
| Archive Traversal, Link & Size Guards | run_cloud_stress.py:182-230 | download_archive enforces MAX_ARCHIVE_BYTES (50 MiB) during streaming read. safe_extract rejects count > 2000, absolute paths, .. segments, symlinks (issym), hardlinks (islnk), non-regular files, m.size > 5 MiB, cumulative uncompressed size above 50 MiB, and verifies os.path.realpath(outpath).startswith(dest_real + os.sep). | PASS |
| Subprocess, Output, Resource & Deadline Bounds | run_cloud_stress.py:67-81, 205-224, 343-413; stress_checks.py:34-42 | Caps concurrency at MAX_CONCURRENT = 6, real fixture data at ~1.5 MiB (13.5 MiB including apparent sparse size, well below 32 MiB), save pool at 32 slots/agent, RSS growth at 96 MiB, FD slack at +2, workspace size at 128 MiB, per-stage timeouts (120s–420s), and overall deadline at 900s. Minor gaps exist in socket-read vs. wall-clock download timeout and unpassed --deadline-seconds. | PASS WITH LIMITS (L1–L4) |
| Directory-Order Defect Handling | run_cloud_stress.py:352-374, README.md:155-162 | README prescribes overriding --base-dir onto a disk-backed filesystem in the sandbox to mask test_metadata_failure_below_root_is_skipped_and_charged, while run_cloud_stress.py hard-aborts before smoke/soak/edges if any of the 506 tests fail. | FAIL (B1) |

### 1.2 Concrete Blockers (CHANGES REQUIRED for Baseline Acceptance)

1. B1 — Directory-Order-Sensitive Test Failure Masking & Stage Coupling (run_cloud_stress.py:352-374, README.md:155-162)

- Finding: test_partial_scan_review_fixes.PostYieldStorageErrorTests.test_metadata_failure_below_root_is_skipped_and_charged assumes os.scandir() / readdir(3) yields a.txt before b.txt. The D063 README relies on selecting a creation-order filesystem via --base-dir to make the 506-test suite pass. On instance-20261015-210506, using --base-dir outside /tmp violates workspace containment and masks a real defect; conversely, running in /tmp will either silently mask the defect (if the target's /tmp returns a.txt first) or fail the suite at Step 6 and abort before running Steps 7–9 (smoke, soak, edges).

- Required Change: Lock execution to /tmp. Add a dedicated, deterministic confirmation step that executes test_metadata_failure_below_root_is_skipped_and_charged under both native directory order and inverted directory order (['b.txt', 'a.txt']), recording the reproduction explicitly. If the 506-test suite fails solely on this known directory-order-sensitive test on native /tmp, record the suite failure accurately in summary.json (suite_result: "FAIL_KNOWN_READDIR_ORDER") and still execute smoke, soak, and edges (while keeping overall runner exit non-zero if strict suite pass is required, or reporting both gates independently).

2. B2 — Non-Fail-Closed Handling of extra Files in verify_identities() (run_cloud_stress.py:125-131, 328-341)

- Finding: verify_identities() checks that all 26 pinned files match EXPECTED_BLOBS, and collects all other extracted files into extra. However, main() only prints note: N file(s) present beyond the pinned set: ... and continues execution. Because the archive .tar.gz SHA-256 is not pinned and build_env() prepends src directly to PYTHONPATH, any unexpected .py, .pyc, .pth, or .so file in src/ (e.g., sitecustomize.py, usercustomize.py, or an extra tests/test_*.py file discovered by unittest discover) would execute despite passing verify_identities().

- Required Change: Either pin EXPECTED_ARCHIVE_SHA256 for the codeload tarball, or enforce a strict fail-closed allow-list on extra so that any unexpected file under drive_tool/ or tests/, or any file with an executable/importable extension (.py, .pyc, .pyo, .pth, .so, .sh) anywhere in src, immediately triggers FAIL-CLOSED (identity).

3. B3 — Unconstrained --base-dir and --workdir CLI Arguments (run_cloud_stress.py:276-288)

- Finding: Although default flags use /tmp, passing --base-dir /var/tmp or --workdir /home/.../ws is permitted by the parser and creates workspaces outside /tmp.

- Required Change: Canonicalize ws = os.path.realpath(ws) before creation and fail closed unless ws.startswith("/tmp/") and ws != "/tmp". Set workspace permissions to 0o700.

### 1.3 Security & Operational Limits (Non-Blocking for Default Run, Must Be Addressed in Harsh Extension)

- L1 — Per-Socket vs. Wall-Clock Download Timeout (run_cloud_stress.py:182-193): urllib.request.urlopen(req, timeout=timeout) bounds individual read() syscalls rather than total elapsed download time. A slow trickle connection can exceed DEFAULT_DOWNLOAD_TIMEOUT (120s). Check time.monotonic() > deadline inside the while True: chunk loop.

- L2 — Unpassed Internal --deadline-seconds (run_cloud_stress.py:384-385, stress_checks.py:390-393): stress_checks.py supports --deadline-seconds=N to stop worker loops cleanly and emit STRESS_JSON:, but run_cloud_stress.py never passes that flag. If a stage hits its timeout, subprocess.run kills the child and loses the structured STRESS_JSON: telemetry.

- L3 — Unbounded capture_output=True & Single-PID Timeout Kill (run_cloud_stress.py:205-220): subprocess.run(..., capture_output=True) buffers child stdout/stderr in memory without a byte cap and only kills the direct child PID on TimeoutExpired. Safe for the single-process D063 stages, but insufficient for multi-process harsh fault tests (which require start_new_session=True and os.killpg()).

- L4 — Symlink Safety in write_manifest() and dir_size() (run_cloud_stress.py:157-166, 244-253): Neither function guards against file symlinks via os.path.islink(p). Currently benign only because link_out targets a directory (<ws>/outside), which os.walk(..., followlinks=False) places in dns rather than fns.

- L5 — Apparent vs. Allocated Bytes in build_roots() (stress_checks.py:104-106): total += SPARSE_SIZE counts the 2 MiB apparent size of each of the 6 sparse files (12 MiB total) rather than os.stat(p).st_blocks * 512, and does not add the savepool files (<= 768 KiB) written during the workload.

### 1.4 Operational Guidance Prior to Target Bootstrap

- If the Director chooses to run D063 as-is before patches: Running python3 run_cloud_stress.py with zero CLI flags on instance-20261015-210506 is host-safe (strictly confined to /tmp/d063-b7f8d17b-<uniq>, no credential or service impact), but do not pass --base-dir to work around a suite failure, and do not treat a passing Step 6 on /tmp as disproving the readdir-order bug.

- Recommended Path: Apply fixes B1–B3 to run_cloud_stress.py and pair it with the separate D065 harsh-fault extension contract below.

## 2. Mandatory Handling of the Directory-Order-Sensitive Suite Finding

D063 documented that test_partial_scan_review_fixes.PostYieldStorageErrorTests.test_metadata_failure_below_root_is_skipped_and_charged fails when the underlying filesystem returns directory entries in [b.txt, a.txt] order rather than [a.txt, b.txt] creation order.

On Debian (instance-20261015-210506), /tmp is mounted either as tmpfs or on the root ext4 filesystem (which enables dir_index HTree hash indexing by default). Because POSIX explicitly leaves readdir(3) ordering unspecified, relying on whichever filesystem happens to return a.txt first hides a real bug in the test/implementation contract.

### Mandatory Confirmation Contract (No Filesystem Masking)

1. Prohibition on Filesystem Selection: Neither the baseline runner nor the harsh extension may set --base-dir outside /tmp or mount a special filesystem to make the 506-test suite pass.

2. Filesystem & Native Ordering Telemetry: Before running the suite, capture and log in <ws>/logs/readdir_order_confirmation.json:

- The exact backing filesystem of /tmp parsed from /proc/mounts (fstype and mount options).

- The native iteration order returned by [e.name for e in os.scandir(probe_dir)] when a.txt is created before b.txt inside <ws>/tmp.

3. Deterministic Dual-Order Reproduction Gate: Execute tests.test_partial_scan_review_fixes.PostYieldStorageErrorTests.test_metadata_failure_below_root_is_skipped_and_charged in two isolated subprocess invocations on /tmp:

- Sub-run 1 (order="lex_asc"): With os.scandir / os.listdir wrapped to yield entries sorted ascending (['a.txt', 'b.txt']). Expected: PASS (rc == 0).

- Sub-run 2 (order="lex_desc"): With os.scandir / os.listdir wrapped to yield entries sorted descending (['b.txt', 'a.txt']). Expected: FAIL (rc != 0, reproducing the exact failure observed in the D063 sandbox).

4. Gate Classification: The confirmation gate passes (CONFIRMED_ORDER_SENSITIVE_DEFECT) only if Sub-run 1 passes and Sub-run 2 fails, proving deterministically on the target instance that the committed test is directory-order-sensitive regardless of the host's default /tmp mount behavior.

## 3. Separate Harsh-Fault Test Extension Contract (D065)

This extension is strictly separate from the D063 baseline runner and is authorized only on disposable VM instance-20261015-210506 (2 vCPU / 4 GiB RAM / 10 GiB disk / Debian / Python 3.13). Sarvam will implement and test against this contract.

### 3.1 Host Survivability, SSH Protection & Containment Bounds

To prevent harsh resource pressure, ENOSPC, or SIGKILL tests from dropping the Cloud Shell SSH session, invoking the kernel OOM killer against sshd/systemd, filling /tmp or /, or losing evidence logs, the extension must enforce the following hard boundaries:

| Resource / Boundary | Hard Limit / Control | Enforcement Mechanism (Stdlib + Linux Kernel Only) |
| --- | --- | --- |
| Target Host Identity | instance-20261015-210506 exact match | Fail-closed preflight checks socket.gethostname() == "instance-20261015-210506" AND requires CLI flag --confirm-disposable-host=instance-20261015-210506. |
| Workspace Containment | /tmp/d065-<commit8>-<uniq> (0700) | Canonical os.path.realpath(ws).startswith("/tmp/d065-") check; TMPDIR=<ws>/tmp; PYTHONDONTWRITEBYTECODE=1; max retained workspace size <= 192 MiB. |
| Host Free Disk Floor | >= 1024 MiB free on /tmp and / | Checked before every stage. Never fill the host /tmp or / filesystem to induce ENOSPC. Pre-allocate a 16 MiB emergency reserve file <ws>/logs/.reserve_ballast at startup; unlink it in _finalize() if free space drops below 64 MiB so logs and MANIFEST.md can always be written. |
| SSH & Parent OOM Immunity | Parent runner + sshd protected; child RLIMIT_AS <= 512 MiB | Parent runner executes at normal OOM score (0). Every memory-stress child process immediately writes b"1000\n" to /proc/self/oom_score_adj (permitted unprivileged on Linux) and sets resource.setrlimit(RLIMIT_AS, (512 MiB, 512 MiB)). Check host MemAvailable >= 1024 MiB before starting RAM pressure. |
| CPU Starvation Guard | Child CPU workers at os.nice(15) + RLIMIT_CPU | Stress worker subprocesses call os.nice(15) and resource.setrlimit(RLIMIT_CPU, (60, 60)) so sshd (nice 0) always preempts test workers immediately on both vCPUs. |
| Process Group Isolation | start_new_session=True per child | Every stage and fault worker runs in its own session/process group. On timeout or stage teardown, parent sends os.killpg(pgid, signal.SIGKILL) and os.waitpid(-pgid, 0) so zero runaway processes survive. |
| Subprocess Output Cap | <= 2 MiB per stage log | Redirect child stdout/stderr to bounded log files in <ws>/logs/ rather than unbounded in-memory capture_output=True pipes. |
| Wall-Clock Deadlines | Per-stage <= 120s; Overall <= 600s | Enforced via monotonic clock checks and SIGKILL process-group reaping. |

### 3.2 Extension Deliverables & CLI Contract

Sarvam shall create two stdlib-only files alongside the baseline runner:

- runner/run_harsh_faults.py — Outer orchestrator (workspace setup, host/identity verification, preflight/postflight telemetry, stage execution, manifest generation).

- runner/harsh_checks.py — Pinned payload (HARSH_CHECKS_SHA256 verified by run_harsh_faults.py before execution) implementing the fixed allow-list of harsh stages.

Exact Target Invocation:

```bash
python3 runner/run_harsh_faults.py --confirm-disposable-host=instance-20261015-210506
```

Fixed Allow-Listed Stages (in execution order):

1. readdir_order — Independent confirmation of the directory-order-sensitive suite defect.

2. enospc — Constrained-filesystem ENOSPC / write-limit exhaustion and recovery.

3. crash_kill — Deterministic mid-write SIGKILL crash injection and recovery invariants.

4. resource_pressure — Concurrent CPU saturation, RLIMIT_AS memory pressure, and EMFILE descriptor exhaustion.

Each stage prints a single HARSH_JSON: {...} summary line and writes detailed logs under <ws>/logs/harsh_<stage>.out, rolled up into <ws>/logs/summary.json and <ws>/logs/MANIFEST.md.

### 3.3 Stage Specifications & Reproducible Failure Gates
#### Stage H1: readdir_order (Independent Directory-Order Defect Confirmation)

- Mechanism: Executes the dual-order verification protocol defined in Section 2 against tests.test_partial_scan_review_fixes.PostYieldStorageErrorTests.test_metadata_failure_below_root_is_skipped_and_charged inside /tmp.

- Reproducible Gate:

- lex_asc (['a.txt', 'b.txt']) MUST exit 0.

- lex_desc (['b.txt', 'a.txt']) MUST exit non-zero with the expected assertion/charging failure.

- Native /tmp order (native_order) and mount type (fstype) MUST be recorded in HARSH_JSON.

#### Stage H2: enospc (Constrained-Filesystem ENOSPC & Write Exhaustion)

- Mechanism (Two-Tier Strategy Without Installing Packages):

- Tier 1 (Real Constrained Fixture Filesystem — Preferred): Attempt to create an isolated 16 MiB fixture filesystem at <ws>/mnt_enospc using only pre-installed Debian base tools and non-interactive privilege if present:

- Method 1A (Private Mount Namespace tmpfs): unshare --mount (via sudo -n if unprivileged user namespaces are restricted) mounting mount -t tmpfs -o size=8M,nr_inodes=64,nodev,nosuid,noexec tmpfs <ws>/mnt_enospc. Because the mount exists only inside the child process's private mount namespace, kernel teardown on child exit is automatic and cannot leak a host mount.

- Method 1B (Loopback ext4 image in private mount namespace): truncate -s 16M <ws>/enospc.img + /sbin/mkfs.ext4 -F -m 0 -q <ws>/enospc.img, mounted inside unshare --mount at <ws>/mnt_enospc.

- Tier 2 (Unprivileged Kernel + Syscall Fallback — Always Executed): Regardless of whether Tier 1 succeeds or is skipped due to lack of CAP_SYS_ADMIN / sudo -n, execute:

- Sub-test 2A (Kernel RLIMIT_FSIZE mid-write enforcement): In a child process with signal.signal(signal.SIGXFSZ, signal.SIG_IGN) and resource.setrlimit(resource.RLIMIT_FSIZE, (8192, 8192)), attempt svc.save(..., data=b"X" * 32768). This forces the Linux kernel write(2) syscall to fail mid-write with OSError(errno.EFBIG).

- Sub-test 2B (Deterministic ENOSPC injection across all 4 write phases): Deterministically fault LocalWriter with OSError(errno.ENOSPC, "No space left on device") at: (i) temp file creation, (ii) mid-stream os.write (after writing 50% of bytes), (iii) os.fsync, and (iv) atomic publish (os.link / os.replace).

- Reproducible Invariant Gates:

1. Error Classification: Every pre-publish ENOSPC/EFBIG failure raises ServiceError with code == "unavailable", outcome_uncertain is False, and retry_safe is True.

2. Overwrite Preservation (overwrite=True): Pre-existing target file p/savepool/existing.bin (4096 bytes, known SHA-256) remains byte-for-byte identical after a failed ENOSPC overwrite.

3. No Partial Publication (overwrite=False): Target file p/savepool/new_fail.bin does not exist after a failed ENOSPC create.

4. Zero Temp File or FD Leaks: _scan_temp_leaks(roots) returns [] and _nfd() remains within baseline + 2 after all failed writes.

5. Full Recovery: After unlinking the space-filler file (Tier 1) or restoring RLIMIT_FSIZE / removing fault hooks (Tier 2), subsequent save(), read(), list(), and find() calls on the same LocalFileService instance succeed and verify by SHA-256.

#### Stage H3: crash_kill (Deterministic SIGKILL Mid-Write & Recovery Invariants)

- Mechanism: Uses an inter-process os.pipe() synchronization barrier between the parent test controller and a disposable child worker process (start_new_session=True) so SIGKILL (kill -9) hits at exact, deterministic points in LocalWriter, followed by an uninstrumented multi-process SIGKILL storm:

- Case C1 (Kill Mid-Write / Pre-Fsync): Child wraps os.write on the staging TEMP_PREFIX file to write the first 2048 bytes of a 4096-byte payload, writes a ready byte to the coordination pipe, and blocks on select.select() while parent sends os.kill(pid, signal.SIGKILL) and asserts waitpid status -signal.SIGKILL. Tested for both overwrite=False and overwrite=True.

- Case C2 (Kill Post-Fsync / Pre-Publish): Child completes os.write and os.fsync of the TEMP_PREFIX staging file, signals parent on the coordination pipe immediately before os.link / os.replace, and blocks until parent terminates it with SIGKILL.

- Case C3 (Concurrent Multi-Process SIGKILL Storm): Spawn 4 concurrent child processes continuously performing save(overwrite=True/False) with self-verifying payloads (32-byte ASCII sha256 header + 4064-byte payload) across 8 shared files while the parent sends SIGKILL to a random worker every 50 ms across 16 kill cycles.

- Reproducible Invariant Gates (Verified by a Fresh LocalFileService Instance After Crashes):

1. Zero Torn or Corrupted Target Files: Every published file in p/savepool/ matches either its exact initial SHA-256 or a complete, valid new write (header_sha256 == sha256(body)). Zero truncated, zero-byte, or half-written target files.

2. No Lock Wedge on Restart: A freshly instantiated LocalFileService immediately succeeds on read(), list(), find(), save(overwrite=True), and save(overwrite=False) against the crash-affected root without blocking or raising busy/unavailable.

3. Explicit Orphan Temp File Audit: Because SIGKILL bypasses user-space finally: blocks, Case C1 and Case C2 deterministically leave 1 orphaned TEMP_PREFIX file per killed child on disk. The check must:

- Verify len(orphan_temps) >= 1 immediately after SIGKILL (proving the kill genuinely interrupted staging before cleanup).

- Test whether svc.list() and svc.find() on the fresh LocalFileService expose or hide orphaned TEMP_PREFIX files, recording orphan_temps_visible_in_list and orphan_temps_visible_in_find in HARSH_JSON (and failing closed if the service contract requires TEMP_PREFIX omission from listings/searches and leaks them).

#### Stage H4: resource_pressure (CPU Saturation, RAM RLIMIT_AS Pressure & EMFILE Exhaustion)

- Mechanism:

- Sub-stage R1 (2-vCPU Preemption & Race Stress): Spawn 4 background CPU-bound child processes (os.nice(15), tight hashlib.pbkdf2_hmac loops) to saturate both vCPUs on instance-20261015-210506, then execute a 1,200-call 6-agent workload plus 20 iterations of the 6-thread overwrite=False barrier race and active-lease svc.close(timeout=10.0) drain.

- Sub-stage R2 (Constrained-Process Memory Pressure & MemoryError Recovery): In a dedicated child process (oom_score_adj=1000, RLIMIT_AS = 384 MiB), hold a 192 MiB bytearray ballast while running 300 windowed 256 KiB reads and saves. Then trigger an intentional MemoryError boundary (attempting buffer growth past RLIMIT_AS or injecting MemoryError inside a read/save call) and verify that subsequent normal-sized read() and save() calls succeed once ballast is released.

- Sub-stage R3 (EMFILE File-Descriptor Exhaustion & Recovery): In a dedicated child process, query soft/hard RLIMIT_NOFILE, lower the soft limit to current_nfd + 3, and run concurrent list, find, read, and save calls so real kernel OSError(errno.EMFILE, "Too many open files") errors occur during os.open / os.scandir. Then restore the soft RLIMIT_NOFILE limit and re-run operations on the same LocalFileService instance.

- Reproducible Invariant Gates:

1. R1 Gate: Exactly 1 winner per overwrite=False race (others == "exists"), svc.close() returns True, zero unexpected exceptions, and zero temp leaks under 2-vCPU saturation.

2. R2 Gate: Child RSS stays within RLIMIT_AS, host MemAvailable never drops below 512 MiB, target files remain uncorrupted across MemoryError, and child exits 0.

3. R3 Gate: Under EMFILE, no unhandled OSError escapes LocalFileService (every failure is mapped to ServiceError), zero target files are corrupted, FD count returns to baseline + 2 after restoring RLIMIT_NOFILE, and subsequent calls on the same LocalFileService instance pass 100%.

### 3.4 What Cannot Be Guaranteed (Explicit Non-Guarantees)

Even on a dedicated disposable VM, the following properties cannot be guaranteed by user-space Python testing and must be explicitly documented as non-guarantees in summary.json:

1. Power-Loss / Kernel-Panic Block-Device Durability (fsync vs. Virtual Disk Cache): SIGKILL (kill -9) terminates the user-space process while keeping the Linux kernel page cache and ext4 journal intact. It proves process-crash atomicity, not physical power-loss durability across hypervisor disk write-back caches.

2. Automatic Cleanup of SIGKILL-Orphaned TEMP_PREFIX Files Without a Startup Sweep: A process killed by SIGKILL between mkstemp() and os.unlink() cannot execute its Python finally: block. Unless LocalFileService implements an explicit startup or periodic janitor sweep, orphaned TEMP_PREFIX files remain in the directory after SIGKILL (consuming inodes/space and potentially appearing in list()/find() unless filtered by TEMP_PREFIX).

3. Unprivileged Loopback/Tmpfs Mount Availability: If instance-20261015-210506 disables unprivileged user/mount namespaces (kernel.unprivileged_userns_clone=0 or AppArmor restrictions) AND the runner is invoked without passwordless sudo -n, Tier 1 real mount-full ENOSPC cannot be mounted without root; the runner must record enospc_tier1_mount: "SKIPPED_NO_PRIVILEGE" and rely on Tier 2 (RLIMIT_FSIZE kernel EFBIG + deterministic 4-phase ENOSPC syscall faults) rather than dangerously filling the host /tmp filesystem.

4. Exact Hardware Timing of Uninstrumented Races: Under Sub-stage R1 and Case C3 (SIGKILL storm), Linux CFS scheduler preemption order on 2 vCPUs is non-deterministic; determinism for mid-write crash invariants is guaranteed by Cases C1 and C2 (pipe-synchronized barriers), while C3 and R1 provide statistical concurrency validation.
