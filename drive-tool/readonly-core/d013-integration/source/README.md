# Drive Tool — director plan and architecture

Owner: Dolesh. Director: Codex in the current session.
Status: specification only; no implementation or tests are claimed complete.

## Goal
An agent can search, retrieve, collect, transfer, and organize files in authorized Google Drive folders and configured local storage roots. Test on the Ubuntu VPS first, stabilize a pinned release, then deploy that release on Dolesh's PC.

## Division of work
The director owns architecture, interfaces, task briefs, acceptance criteria, integration decisions, and verification. Browser chatbots implement and execute tests. Sarvam operates the browser, delivers briefs, waits for completion, and returns evidence. A chatbot's success claim is insufficient: require commands, outputs, source revision, environment, and artifacts. Use an independent capable chatbot for review of authorization, deletion, transfer recovery, and credentials.

## Architecture
Python service with:
1. Storage adapters: LocalAdapter, GoogleDriveAdapter, plus a fake adapter for deterministic tests.
2. Shared file service: explicit source IDs and opaque file IDs, metadata, paginated listing/search, streaming reads/writes, mkdir, move, trash.
3. Durable jobs: SQLite job journal for transfers and collection; bounded retries, cancellation, progress, idempotency keys, byte limits, provenance.
4. Agent interfaces: authenticated REST first, MCP wrapper over the same operations after REST acceptance.
5. Policy and audit: configured roots/folders, operation permissions, mutation preview, confirmed destructive actions, redacted audit records.

Initial deployment is one service on the VPS; its local test root stands in for the PC drive. It does not imply access to the PC. Later run the same service on the PC with configured local roots. A future remote coordinator must use an authenticated outbound connection from the PC; never expose arbitrary filesystem or shell access.

## Interface decisions
Sources are configured by operators, never by arbitrary agent filesystem paths.
FileRef = {source_id, file_id}. FileMetadata includes file_id, source_id, name, parent_id, kind, size_bytes (nullable), modified_at (nullable), checksum (nullable).
list(parent, cursor, limit) -> {items, next_cursor}; stat(ref); read(ref) -> binary stream; write(parent, name, stream, overwrite=false); mkdir(parent, name).
Search starts as bounded filename matching; content indexing is a later module.
Move and trash are separate planned operations. No permanent delete in v1.
Transfers initially support files only, explicit destinations, no overwrite by default, temporary destination plus verified finalization. Later tasks must specify each backend's actual atomicity and checksum guarantees rather than assume them.
Collection initially accepts explicit HTTPS file URLs or storage references with a destination and byte budget; record source and collection time. Web crawling, arbitrary code execution, and automatic synchronization are outside v1.

## Credentials and data
Never commit tokens, OAuth credentials, private files, browser sessions, or production logs. Public task briefs contain synthetic examples only.
Google OAuth is configured on the host through an operator flow; choose minimum permissions matching authorized folders and required operations. Shared Drive behavior, export of Google-native files, shortcuts, and permission limitations require an explicit connector task and tests.
Filesystem containment must handle traversal, symlinks, root replacement, and concurrency; lexical path checks alone are insufficient.
Network collection must reject private/loopback/link-local destinations and revalidate redirects; it gets its own review and tests.

## Milestones and release gates
1. Local core: adapter contract, local containment, atomic no-overwrite writes, synthetic tests.
2. Agent API: authentication, pagination, explicit errors, audit and limits.
3. Google Drive: OAuth, authorized scope, list/search/read/upload, quotas and refresh behavior.
4. Durable transfer: local-to-Drive and Drive-to-local, restart recovery, cancellation, integrity and duplicate policies.
5. Collection and management: provenance, safe URLs, usage reports, previewed move/trash.
6. Stabilization: independent review, full test suite, VPS integration using synthetic data, restart/expiry/retry tests, pinned dependencies, operational documentation, release candidate.
7. PC deployment: OS-specific packaging, local root setup, credentials supplied locally, repeat smoke/integration tests, tagged stable release and rollback.

Each milestone is gated by verified evidence. Unit tests alone do not establish production filesystem or OAuth safety.

## VPS constraints
The browser VPS recently reported about 1.3 GB free disk. Preserve the existing browser-tool installation and services. No installation, service changes, credential changes, or production storage access until the director supplies a separate deployment task. Use tiny synthetic fixtures and bounded downloads.

## Delegation workflow
Public self-contained briefs live in tasks/. The director selects a capable browser chatbot and sends a link through Sarvam. Sarvam must verify access to the brief, or paste its exact contents. Outputs must be retrievable as source files/patch plus evidence. If the chatbot cannot execute code, it must explicitly say NOT RUN; testing is then delegated to an execution-capable chatbot. Do not assume a browser chatbot can access a private repository, push commits, run shell commands, or operate the VPS.
