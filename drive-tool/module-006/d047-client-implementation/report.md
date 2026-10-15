# D047 — minimal Python agent client: implementation & simulated-server tests

**Author:** local Sarvam
**Task brief:** `tasks/d047-agent-client.md` at `d14b1b7f599b48d4b7f3af9ddae9d6829e065769`
**Base commit (confirmed):** `cedaa1342942a33f27a473e4c4ebbff6309c8932`
**Branch:** `feature/module-006a-client`
**Scope:** exactly two new files — `drive_tool/service_client.py`, `tests/test_service_client.py`.
No edits to any existing file, no HTTP server, no policy/storage code, no main merge, no deployment.

> The tests drive **simulated HTTP services** on loopback plus controlled
> transport seams. They pin the client's own wire behaviour and local safety
> properties. They are **not** real Drive-service integration or acceptance
> evidence.

## What was built

`DriveClient(*, port, token, timeout=5.0)` — a stdlib-only loopback caller with
exactly four public operations:

- `list(source_id, file_id="root", *, limit=20, offset=0, name_contains=None) -> dict`
- `find(source_id, file_id="root", *, name_contains, limit=20, max_entries=2000, max_depth=4) -> dict`
- `read(source_id, file_id, *, offset=0, length=262144) -> ReadReply`
- `save(source_id, file_id, data, *, overwrite=False, create_parents=True) -> dict`

Wire: `POST /v1/list|find|read` (UTF-8 JSON controls, `Content-Type: application/json`)
and `POST /v1/save?<urlencoded source_id,file_id,overwrite,create_parents>` (raw
octet-stream body). Every request carries exact `Content-Length`, `Authorization:
Bearer <token>` and `Connection: close`. Host is always `127.0.0.1`, HTTP only,
a fresh `http.client.HTTPConnection` per call, no proxy/redirect/env transport
config, no automatic retries.

`ReadReply` is a frozen dataclass `(data, offset, observed_size, observed_mtime_ns,
eof_observed)`. `DriveClientError` exposes only `code`, `outcome_uncertain`,
`retry_safe`; `str`/`repr` carry fixed local text and never the remote message,
bearer, root or body.

## Interpretation decisions (flagged for director review)

The brief is the director-owned contract; two points were ambiguous and are
recorded here so they can be corrected cheaply:

1. **`list` body `name_contains`.** The brief says "list/find use the exact keys
   above". For `list`, `name_contains` defaults to `None`; the client **omits**
   the key when it is `None` and includes it only when a filter is supplied.
   `find` always includes `name_contains` (required, non-empty).
2. **`file_id` lexical shape.** "canonical p/relative POSIX" is read as a
   non-root relative POSIX path: reject empty, leading `/`, backslash, NUL, and
   any empty/`.`/`..` segment. `root` is allowed only for `list`/`find`.

All other rules (constructor validation, ranges, bounded replies, header
requirements, error mapping, uncertainty defaults) follow the brief literally.

## Raw evidence

Environment (both interpreters present in the execution sandbox):

- Python 3.12.13 (CPython, GCC 12.2.0), Linux x86_64
- Python 3.11.2  (CPython, GCC 12.2.0)

Test runs (see `*.log`, raw unittest output, exit codes in `env.txt`):

| Run | 3.11 | 3.12 |
|-----|------|------|
| Baseline (all pre-existing tests, new file excluded) | 351 OK, 0 skips, exit 0 | 351 OK, 0 skips, exit 0 |
| Full suite (baseline + new file) | 412 OK, 0 skips, exit 0 | 412 OK, 0 skips, exit 0 |
| New file only (`tests.test_service_client`) | 61 OK, exit 0 | 61 OK, exit 0 |

Baseline 351 is preserved unchanged; the new file adds 61 tests.

### Focused isolated mutations (all caught)

Each mutation is applied to a private copy of the tree; the D047 test file is
run against the mutant. Raw logs in `mutations/`.

| Mutation | Result | Tests that caught it |
|----------|--------|----------------------|
| M1 unbounded reply read (`resp.read()` instead of `read(cap+1)`) | CAUGHT | `test_connection_and_response_closed_on_success/_error`, `test_new_connection_per_call_no_reuse` (seam response raises on unbounded read) |
| M2 lost connection close | CAUGHT | `test_connection_and_response_closed_on_success/_error`, `test_new_connection_per_call_no_reuse`, `test_save_transport_failure...`, `test_timeout_maps_to_timeout_code` |
| M3 automatic save retry | CAUGHT | `test_no_automatic_retry_on_save`, `test_save_transport_failure_is_uncertain_and_not_retry_safe`, `test_save_success_body_over_cap_is_uncertain`, `test_missing_flags_use_write_defaults_for_save` |
| M4 raw remote error leakage (embed remote message in code) | CAUGHT | `test_error_is_redacted_even_if_server_echoes_token`, `test_known_codes_recognized`, `test_uncertainty_flags_honored`, `test_missing_flags_use_*_defaults` |
| M5 cross-request connection reuse (cache one connection) | CAUGHT | `test_open_returns_a_new_connection_each_time`, `test_concurrent_calls_are_independent` |
| M6 wrong EOF handling (accept exact-fill with eof_observed) | CAUGHT | `test_read_exact_fill_with_eof_is_protocol_invalid` |

## Files and hashes

| File | Bytes | SHA-256 |
|------|-------|---------|
| `drive_tool/service_client.py` | 20319 | `3df94000e249c9c564bd11a9142417a10494b426a24980e54849dd8730310785` |
| `tests/test_service_client.py` | 38139 | `fcda8541a51d83210cb479c0d0214e3c766895494ea4c1210fcd828ef28be2b1` |

The exact committed source lives on branch `feature/module-006a-client` at head `81a6485c300f0a9cecc9c902c90360379c17e946`; `source_sha256.txt` records the two file hashes, verified byte-identical against a fresh raw download of the committed files.

## Honest status

- Not independently reviewed or accepted; not merged; not deployed.
- Simulated-service tests do not prove real service integration.
- No real Drive roots, tokens or network endpoints were used.
- Blockers: none for this deliverable. Publication target availability is
  reported separately.
