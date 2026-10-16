# dt01-gemini (gemini)

- status: done
- chat: https://gemini.google.com/app/e65abf97ff970240
- model: 4 argon (thinking: medium)
- finished: 2026-10-16T12:27:17Z

## Question

Gemini, I need a short design note from you (no code). drive-tool is a small local file service for AI agents: four tools (list, find, read, save) over HTTP on 127.0.0.1, per-agent token + grants (alias -> local root, allowed operations, byte caps), strict containment inside each root. The attached files show the agent API and the policy model.

The owner wants Google Drive access next, but does NOT want a custom Google Drive connector built from scratch. Evaluate using rclone (which already supports Google Drive: list, copy, move, sync) behind the SAME four agent tools, keeping drive-tool's local containment core for local roots.

Cover, briefly: (1) the options (rclone mount vs rclone rcd/remote-control API vs rclone CLI calls vs syncing a local mirror), (2) which one you recommend and why, (3) how a grant would point at a Drive folder, (4) what containment/safety guarantees we keep or lose vs local roots, (5) credentials handling (rclone config stays on the host, never in git or chats), (6) failure modes and limits (rate limits, large files, latency), (7) the smallest first implementation step. Keep it under 900 words.

Use these headings: ## Options, ## Recommendation, ## Grants, ## Safety, ## Credentials, ## Failure modes, ## First step.

## Answer

## Options

- rclone mount (FUSE): Exposes Google Drive as a host directory, allowing reuse of LocalAdapter. However, it requires OS-specific FUSE dependencies, fills the 1.3 GB VPS disk via VFS caching, masks network/quota failures as generic OSErrors, and breaks local inode/atomic-rename semantics.

- rclone rcd (remote-control API): Runs a persistent rclone rcd daemon on loopback or a UNIX socket. GoogleDriveAdapter calls its HTTP endpoints (operations/list, operations/copyfile, etc.). Avoids per-call startup overhead, isolates rclone errors cleanly, and supports streaming, though it adds a sidecar daemon lifecycle to manage.

- rclone CLI calls: Invokes stateless rclone subprocesses (lsjson, cat, rcat, copyto) with shell=False per operation. Requires zero background daemons, uses minimal memory/disk, bounds execution cleanly via subprocess timeouts, and keeps token refresh isolated inside rclone.

- Syncing a local mirror: Runs periodic rclone sync/bisync to a local folder. Violates the README goal ("without a mandatory whole-drive mapping/index or manual staging copy") and is impossible on a VPS with 1.3 GB free disk.

## Recommendation

Use rclone CLI calls wrapped inside a dedicated GoogleDriveAdapter, while leaving LocalAdapter untouched for local filesystem roots.

For an API capped at 1 MB reads/writes and 5-second default client timeouts (service_client.py), subprocess spawning overhead (~30–50 ms) is negligible compared to Google Drive HTTPS latency (200–800 ms). Subprocess calls eliminate daemon supervision and FUSE mount wedging, enforce hard per-call wall-clock timeouts via subprocess.run, and require zero local disk cache when streaming or using memory-backed temp files. If throughput later demands warm connections, the internal implementation of GoogleDriveAdapter can switch to rclone rcd without changing service_policy.py or the wire contract.

## Grants

Currently, SourceGrant.root in service_policy.py enforces a strict POSIX path (_require_root requires a leading / and forbids empty or dot segments). To support Drive folders without weakening policy validation:

1. Host-anchored rclone remotes (zero policy change): The operator defines a folder-locked remote in rclone.conf on the host (setting root_folder_id = <DriveFolderID> under [gdrive_proj]). SourceGrant.root uses a reserved prefix like /__rclone__/gdrive_proj or /gdrive_proj/subpath, which passes _require_root unchanged and routes to GoogleDriveAdapter at startup.

2. Explicit backend field (small policy extension): Add backend: str = 'local' ('local' | 'gdrive') to SourceGrant. For 'gdrive', validate root as <remote_name>:<optional/subpath> while keeping root_folder_id pinned in the host's rclone.conf.

In both cases, agents still pass only the opaque source_id alias ([A-Za-z0-9_-]+) and canonical file_id (root or p/<relative_posix_path>) on the wire.

## Safety

- What we keep:

- Full LocalAdapter kernel-level containment (openat/O_NOFOLLOW) for local roots.

- Strict lexical path validation: file_id must start with p/ and cannot contain .., ., \, or NUL (service_client.py).

- Hard 1 MB caps (MAX_TRANSFER_BYTES) on reads and writes, plus max_depth and max_entries bounds.

- Server-side folder anchoring: pinning root_folder_id in the rclone remote restricts Google Drive API queries to descendants of that folder ID.

- What we lose / must mitigate on Drive roots:

- Symlinks/Shortcuts: Drive shortcuts (application/vnd.google-apps.shortcut) can point outside root_folder_id. Mitigation: Always pass --drive-skip-shortcuts to rclone so shortcuts are ignored and never dereferenced.

- No-overwrite atomicity: Local filesystems guarantee atomic O_CREAT | O_EXCL or rename(2). Drive lacks atomic check-and-set creation and allows duplicate filenames in the same folder. Mitigation: Run --drive-Duplicates checks or pre-stat before save(overwrite=False), and document that concurrent remote writers can race; for overwrite=True, pass --drive-use-trash=false or handle deduplication explicitly.

- Google Docs native files: Docs/Sheets have no raw byte size and fail exact byte-window assumptions (ReadReply requires len(raw) == request_length unless eof_observed is true). Mitigation: Pass --drive-skip-gdocs in v1 so native docs are hidden or rejected with invalid until an explicit export contract exists.

## Credentials

- Host-only storage: OAuth client secrets, refresh tokens, and root_folder_id pins live exclusively in /etc/drive-tool/rclone.conf (or user config dir) with 0600 permissions, owned by the service user.

- Least privilege: Configure rclone with scope = drive.file or drive.readonly where possible, restricted to specific shared folders or a dedicated service account.

- Zero leakage: The service invokes rclone with --config /path/to/rclone.conf. service_policy.py and DriveClientError already redact all internal paths and stderr messages ("access denied" or fixed error codes). If rclone refreshes a token and rewrites rclone.conf, it happens entirely on the host outside the git repo.

## Failure modes

- Rate limits (HTTP 403/429): Drive enforces ~10–15 queries/sec and strict write quotas (~2–3 creates/sec). Configure --tpslimit 8 and --retries 1 on rclone calls so throttling returns fast and maps cleanly to DriveClientError(code="busy", retry_safe=True) rather than hanging past the client timeout.

- Latency & find timeouts: Deep recursive searches over HTTP can exceed the 5.0s client socket timeout. Use rclone lsjson --fast-list --max-depth <N> for find (when depth allows) and map subprocess timeouts to code="timeout".

- Windowed reads & large files: read requests a byte window (offset, length <= 1 MB). Use rclone cat --offset X --count Y so rclone issues an HTTP Range request, never staging the full remote file on the 1.3 GB VPS disk.

- Uncertain writes: If a save subprocess times out or disconnects mid-upload, the server must return code="timeout" or "unavailable" with outcome_uncertain=True, retry_safe=False.

## First step

Implement a read-only RcloneDriveAdapter supporting only list and find against a single pre-configured rclone remote with --drive-skip-shortcuts and --drive-skip-gdocs, verified against a synthetic test folder on the VPS before adding windowed read or save.
