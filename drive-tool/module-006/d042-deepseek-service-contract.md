# d042 (deepseek)

- status: done
- chat: https://chat.deepseek.com/a/chat/s/71bbf79a-39f5-40c7-b102-f480fd351a78
- model: deepseek (deepthink on, search off)
- finished: 2026-10-15T16:19:31Z

## Question

DeepSeek, I am leading Drive Tool. I need you to take over the design-only D041 service-contract review in the supplied file; task ID for this execution is D042. Gemini could not start because its higher-model quota is exhausted. Sarvam is independently implementing range reads on the local VM; do not duplicate or alter that module. Treat the supplied versioned brief as my contract requirements, and return <=1600 words with a minimal developer brief, source-confirmation prerequisites, concrete policy/HTTP/deadline/drain/write-uncertainty choices and truthful limitations. No code, tests, installs, credentials, implementation merge or deployment. TESTS_NOT_RUN; end STATUS: REVIEWED. I will review the design before assigning implementation. File context is supplied inline by relay because direct file retrieval is not assumed.

(input files: Dolesh-avkalan/drive-tool:tasks/d041-service-contract-review.md@994049485885994fe8653d8b4ec7a25fb578816d)

## Answer

TESTS_NOT_RUN. Design-only D042 review of D041. No code, tests, installs, credentials, merge, or deployment. Sarvam/D040 range-read work is treated as an external module: not duplicated, not altered. Implementation is gated on an accepted exact source pin.

## Source-confirmation prerequisites

1. Pin main91ebbf5 and implementation source e88c9c79fdc27057622d44ba51e008f2e4ea4f4f; confirm actual layout is drive_tool/, not src/drive_tool/.

2. Confirm exact signatures/return fields for LocalAdapter, listing helper, search.find, FileMetadata, ScanBatch, and LocalWriter. Do not invent parameter names. Confirm FileMetadata has no mtime and no per-result stat.

3. Confirm D040/Sarvam range-read accepted source pin. If not accepted, service range-read path is deferred; consume only the accepted API. Do not implement pread/range logic in this service.

4. Confirm LocalWriter.write_bytes failure ordering: no-replace publish, parent-fsync failure after file may exist, mkdir, max_write_bytes.

5. Confirm whether a per-grant anchored adapter can be opened at a grant root with grant-relative remapped IDs. If not, restrict grants to source roots only until confirmed. A lexical string prefix alone is not a security boundary.

6. Confirm configured source aliases/roots and that request paths never carry host roots. Confirm HTTP/1.1 stdlib parser limits available in Python 3.11.

7. Confirm lifecycle close racing active operations remains unsupported and external mutation/hardlinks/mounts/operator-provisioned roots remain documented boundaries.

## Minimal developer brief

Scope. One service package under drive_tool/ plus one thin local Python client and dedicated tests/docs. At most two justified boundaries: service policy/HTTP core, and local client. Do not modify existing storage/local/search/local_write modules except read-only imports. Isolated feature branch only.

Config shape. Static JSON/TOML: loopback bind; max_connections=64; max_workers=16; global_queue=64; global_buffered_request=8MiB; global_buffered_response=32MiB; request_line_bytes=8KiB; header_bytes=16KiB; json_body_bytes=64KiB; binary_body_bytes=1MiB; response_bytes=1MiB; control_deadline_ms=5000; io_deadline_ms=15000; response_wait_ms=2000; shutdown_grace_ms=10000; audit_ring=1024. Per agent: id, token reference external, permissions find/list/read/save, max_items=20 default/cap 100, read/write byte limits, max_concurrent=4, source slots. Per grant: agent, source alias, anchor/root, permissions. Credentials are external references only.

HTTP/wire. Loopback HTTP/1.1, Connection: close, no keepalive, no pipelining, no chunked. Require exactly one Content-Length; reject duplicate length, Transfer-Encoding, or conflicting framing before body. Authenticate, then authorize, before filesystem side effects. Endpoints: POST /v1/find, POST /v1/list, POST /v1/read, POST /v1/save. find/list use JSON control and JSON results. read uses JSON control and raw application/octet-stream response with observed metadata headers. save uses control query/headers plus raw body. Client methods mirror these operations and use stdlib HTTP; this is the actual supported local entry point. Remote browser access is deferred.

Errors. Fixed eight: invalid 400, denied 403, not_found 404, exists 409, too_large 413, busy 429, unavailable 503, timeout 504. Error body includes code, redacted message, retry_safe, and save side_effects where relevant.

Deadlines/caps/concurrency. Absolute accept-to-final-write deadlines and byte/count caps; socket inactivity alone is insufficient and slow trickle is rejected. Bound accepted connections, queue, global/per-agent/source slots, and buffered request/response bytes. No unbounded executor queue. Over-cap queue returns busy. Once dispatched, a worker retains quotas/adapter lease until the syscall actually returns. Response timeout does not cancel filesystem syscall or stop a later save. Source/agent saturation can affect unrelated callers under finite global capacity; no immunity. Syscall deadlines are not enforceable for local FS with stdlib; distinguish response-wait budget from compute completion and network delivery.

Shutdown/drain. Stop accepting new work. Let active workers finish until shutdown_grace_ms; then process exits. Do not close/reuse active descriptors and do not promise descriptor rebind. Operator fallback is kill/restart. In-flight saves after grace may be uncertain. No supervisor architecture in first scope.

Save/write uncertainty. Save may create missing parents in one call, only within the grant anchor, default no overwrite. Parent mkdir side effects persist on later failure; no shared-dir rollback. Existing file with no overwrite returns exists. Post-publish durability/fsync error returns unavailable, retry_safe=false, file_may_exist=true. Lost/timed-out save completion after dispatch returns timeout, retry_safe=false. No durable idempotency; explicitly deferred. Verify-before-retry is guidance only and does not protect against a still-active save racing verification. No known-not-committed claim.

List/find/read. List offset windows are per-call observations, not snapshots. Every short reply still reports incomplete coverage via complete/truncated/reason. find reports items/inspected/skipped/truncated/reason with no cursor. No mtime. read preserves observed-only range metadata and eof_observed; never promise final EOF or coherent versions under concurrent mutation. Range read waits for accepted D040 pin; do not duplicate Sarvam’s module.

Policy/non-leakage. Prefer per-grant anchored adapters with remapped grant-relative IDs. Ancestor renames are handled by the anchor, not by a string prefix; if the grant root is replaced/detached, treat as external-mutation boundary. Nested grants must not expose ancestor/sibling metadata, search results, or closest-name hints. If anchored sub-grants are not confirmed, allow only source-root grants.

Acceptance before implementation. Synthetic six identities/grants; auth/malformed/framing/slow-trickle rejection; policy non-leakage; saturation with controlled blocked adapter; response timeout while quotas remain held; delayed/post-publish save uncertainty; safe drain; redacted bounded audit logs/health; fd/temp/RSS stability. 600-call smoke before 10000-call soak. Correctness thresholds separate from benchmark observations; no fake hardware-dependent p99 claims.

Truthful deferred limitations. No MCP, public remote, OAuth, durable jobs, indexing, remote browser transport, idempotency, snapshot list/find, syscall cancellation, or lifecycle-close racing. External mutation/hardlinks/mounts/operator roots remain boundaries. No production security guarantee beyond confirmed design. No D040 acceptance implied.

STATUS: REVIEWED
