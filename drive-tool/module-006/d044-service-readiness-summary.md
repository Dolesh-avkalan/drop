# D044 — service readiness audit: summary

**TESTS_NOT_RUN.** Design/source review only. No implementation, tests, installs, credentials, merge,
or deployment. Independent of, and non-duplicative of, local Sarvam's D043 range verification.

**Access:** GitHub read + publish access confirmed for `Dolesh-avkalan/drive-tool` and
`Dolesh-avkalan/drop`. All five inputs were retrieved directly from their pinned commits (not inline
relay text): D044 brief `d6d1a8e3`; accepted lib `03a8250` (`storage.py`, `local.py`, `local_write.py`,
`listing.py`, `search.py`); pending range candidate `121faf84` (`local.py`, `docs/evidence/MODULE-005B.md`);
D041 requirements `99404948`; D042 DeepSeek proposal `0f352c7b`. SHA-256 recorded for each source file.
The full report is at `drive-tool/module-006/d044-service-readiness/REPORT.md`.

**Key findings**

- **API surface is confirmed from source, not invented.** `FileMetadata` has **no `mtime`** and there is
  **no per-result `stat`**; `search.find` is a **module function** whose key parameter is
  `name_contains` — **not `query`**, and **not `LocalAdapter.find`**. `ListingService.list_page` (default
  20, cap 100), `LocalWriter.write_bytes`/`mkdir` (no-replace publish; parent-fsync **after** the name may
  exist), `LocalAdapter.read_bytes` (whole file, 1 MiB cap). The four client methods map 1:1 to
  find / list / read / save.
- **Accepted vs pending range.** Accepted `03a8250` has **no** `read_range`/`RangeReadResult`; only
  `read_bytes`. The `121faf84` candidate adds them but carries **no independent-acceptance claim** and is
  unmerged. The service range path is **deferred** until an accepted exact pin exists.
- **Grant anchoring.** The constructor already opens an **anchored root fd at any existing directory**, so
  a per-grant anchored adapter is just a second `LocalAdapter` at the grant root with service-side
  id remapping — **no new resolver needed**. The anchor is an inode, so it survives ancestor rename; a
  **lexical string prefix is not a security boundary**. Fallback if anchors are unprovisioned:
  whole-source-root grants only.
- **Resource budget** is fixed and small (64 connections, 16 workers, bounded 64-queue, 4/agent, 8/source,
  1 MiB read+write caps, 8/16/64 KiB + 1 MiB request caps, 1 MiB response cap, 32 MiB buffered request and
  32 MiB buffered response hard caps). Aggregate memory includes **concurrently buffered bodies and
  completed-but-timed-out work** that still holds slots and leases. Absolute accept→final-write deadlines
  (not inactivity timeouts); duplicate `Content-Length` / `Transfer-Encoding` rejected before body;
  `Connection: close`.
- **Shutdown critique.** D042's "then process exits" is not achievable: **Python non-daemon threads block
  interpreter exit** if a worker is in an uninterruptible local-fs syscall. Chosen honest rule: stop
  accepting, drain the queue (503), let dispatched workers run, bounded `shutdown_grace_ms` wait, then a
  **graceful-timeout report**; exit only when threads actually return; operator kill/restart fallback. No
  cancellable kernel I/O, no closing/reusing active descriptors. Saves after grace are **uncertain**.
- **Uncertain writes.** Post-publish durability error → `unavailable`, `retry_safe=false`,
  `file_may_exist=true`; lost/timed-out completion → `timeout`, `retry_safe=false`, no
  known-not-committed claim; missing-parent `mkdir` side effects persist (no rollback); idempotency deferred.
- **Acceptance matrix:** 12 pre-implementation rows covering auth/policy non-leakage, framing/trickle,
  saturation, retained quotas on timeout, delayed/post-publish saves, missing-parent side effects, observed
  EOF, redaction, drain, and 600-smoke-before-10000-soak; correctness rows separated from hardware-sensitive
  benchmark rows.

**Blockers + minimal alternatives:** (1) range path deferred → ship whole-file read now; (2) unprovisioned
grant anchors → whole-source-root grants only; (3) stdlib HTTP framing must be explicit and
keepalive/pipelining/chunked rejected; (4) no cancellable syscall → deadlines are response budgets;
(5) use `name_contains`, not `query`; (6) never `close()` an adapter a worker holds.

**TESTS_NOT_RUN.** The final contract and integration are the director's to choose.
