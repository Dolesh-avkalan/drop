# Actual cloud validation — 2026-10-15 Asia/Calcutta

Owner explicitly requested execution on the connected existing box. Director reviewed and orchestrated Sarvam's published runner without editing implementation or test code. This is actual target execution, distinct from d014's earlier sandbox run.

- Candidate: 99e102522da4f0eeee465fe231ad62f0cc4ecad8.
- Runner/evidence publication: drop a017f66fa0460681bea6da1e916616bb30adb30f. All 28 artifact manifest entries and 17 candidate blob pins verified before orchestration.
- Target: directortemp, GCP europe-west2-b; Ubuntu 26.04.1 LTS, kernel 7.0.0-1011-gcp, Python 3.14.4.
- Runner SHA256: 947d8a5d22fa0fa46bc85959a1abed6202c080f6f2713082e40027141d9e9cae. Kernel-check script SHA256: 216a753a68d58459db057bf315dd37acb780ad22d80356dcb5d1a292da766583. Both checked on target before execution.
- Whole runner bounded by timeout 180s, download timeout 30s, suite timeout 60s and individual check timeout 15s. No dependencies installed and no service changes/reboot.
- Observed runner exit 0, RESULT PASS. 140 committed tests, zero skips, on the available Python 3.14.4 interpreter. Six checks PASS: nofollow, bounded_read, root_anchor, dir_symlink_swap, fifo, fd_lifetime.
- Target workspace /tmp/d014-99e10252-7utf_021 measured 400 KiB; runner staging /tmp/d014-runner-FPAPpc measured 44 KiB before packaging. Retained for evidence, no broad cleanup.
- Post-test bh-brave, bh-mcp, bh-hostd each active; local API health returned ok. Screenshot: outputs/cloud-core-pass.png in the director workspace.
- Packaged target synthetic evidence SHA256: 24d640b9befd624051d858479ca9ab1f5c1f0e8929a2c989504af53ef5e2abd4. Artifact retrieval and raw manifest review follow.

This accepts the read-only core's cloud compatibility gate. Whole-directory listing is still unbounded and pagination is not a snapshot. Google Drive/OAuth, writes, jobs/API and production service deployment remain outside this test. No implementation merge has occurred.
