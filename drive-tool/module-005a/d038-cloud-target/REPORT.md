# D038 actual cloud target validation — PASS

Candidate e88c9c79fdc27057622d44ba51e008f2e4ea4f4f (tree abc0ffb2f561b375cd5166a6bf223d45e3b834c2). Executed 2026-10-15 on existing directortemp, Ubuntu26.04.1, Python3.14.4, real ext4 workspace /var/tmp/d038-e88c9c79-x_u8hul3. No real storage, installs, reboot, credential or service changes.

Sarvam authored/sandbox-tested the runner in drop5019f5ae266c399af2530d92c079b7e4dd9a3a10. Codex reviewed scripts, verified18 executable Python blob pins against candidate Git tree, verified both downloaded script SHA256 values, and orchestrated this authorized target run through the existing SSH web console. No handwritten target tests or implementation edits by Codex.

Invocation from fresh 0700 runner directory /var/tmp/d038-runner-lyeNmb:

    timeout --kill-after=5s 180s python3 -B run_cloud_validation.py --base-dir /var/tmp --python python3.14 --download-timeout 30 --suite-timeout 60 --check-timeout 10

Exit0. All18 executable Python source/test identities match; archive181071bytes SHA25697a5035b8775795766c161d5eec240de7f954523894f6c29803b49f8669d7f24. Full committed suite274 tests, zero skips, OK. All10 separate checks PASS: nofollow, bounded_read, root_anchor, dir_symlink_swap, fifo, fd_lifetime, strict_b_scanner, partial_search, write_collision, concurrent_writers.

The scan check observes real scandir yields/stats: exact B yields, no B+1, exact-budget EOF unknown; temp entry counted but not stat'ed. Partial-search check retains matches and explicitly labels mid-scan fault SIMULATED. Real eight-thread no-overwrite race:1winner,7AlreadyExists losers, exact4096-byte winner payload, no stray temp files. These checks are bounded evidence, not exhaustive filesystem-race or power-loss proofs.

Post-run bh-brave/bh-mcp/bh-hostd active; loopback API health ok:true. Workspace1.2MiB, runner80KiB before evidence archive; root559MiB free. Synthetic workspace retained. No service deployment or Google Drive/OAuth coverage.

Evidence archive17458bytes, SHA2562e77d6d86e8326e31881686d659034b2f5bd72ce93f07e23eb5287d42372eae2. Transferred through bounded visible-terminal base64 chunks, reassembled locally and hash-matched before extraction. Saved logs, suite/check outputs, environment captures, summary and original workspace manifest included. Individual retained log hashes match the workspace manifest. Original source archive/extracted source stay on target and are not duplicated here. Screenshot retained privately in director outputs/d038-cloud-pass.png.

This result supplements independent D037 Python3.11/3.12 and D036 frontier review. No merge approval is implied. PR4 remains a separate concrete approval gate.
