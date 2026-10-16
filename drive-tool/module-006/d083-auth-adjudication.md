# d083 (gemini)

- status: done
- chat: https://gemini.google.com/app/875c215451b51cad
- model: 4 argon (thinking: high)
- finished: 2026-10-16T00:11:22Z

## Question

Gemini, short focused auth/schema observable contract decision D083, retry failed D075 (no reply). Exact backend excerpts supplied; no fullaudit/implementation. Choose safe implementable boundary and regression matrix, distinguish malformed unextractable source from unknown token without private policy access. Static TESTS_NOT_RUN. Return concise decision for director adoption.

(input files: Dolesh-avkalan/drive-tool:tasks/d083-short-auth-adjudication.txt@4ad412c94e2966ee78f4c5ad4b80d49edbb31c2c)

## Answer

Decision D083 (Retry of D075): Adopt Uniform 403 denied for Unextractable/Missing source_id Under the Frozen Backend, and Classify 10+ Digit Syntactically Valid Content-Length as 413 too_large (Post-Auth) via Bounded Clamping (TESTS_NOT_RUN).

## 1. Auth vs. Schema Boundary Decision (Missing / Unextractable source_id)
### Technical Root Cause in Frozen Backend (b7f8d17)

- DriveService exposes no public authentication-only method; self._policy_table is private.

- Every public service operation (read, save, stat, etc.) executes self._authenticate_and_authorize(token, source_id, operation) before validating file_id or payload parameters (_parse_canonical_parts).

- Inside _policy_table.authorize(agent_id, source_alias, operation), if not isinstance(source_alias, str): raise PolicyDeniedError(), and any source_alias not matching an active grant for (agent_id, operation) likewise raises PolicyDeniedError $\rightarrow$ ServiceError("denied") (403 denied).

- Consequently, delegating service.read(token, candidate_source_id, None) when candidate_source_id is None (malformed JSON or missing/non-string source_id) always raises ServiceError("denied") (403) for both known and unknown tokens.

### Adopted Contract & Boundary

1. Keep Backend Frozen & Forbid Private _policy_table Access: Do not access service._policy_table from the HTTP adapter and do not invent heuristic dummy aliases.

2. Distinguish Extractable vs. Unextractable source_id via service.read(token, candidate_source_id, None):

- Unextractable / Missing / Non-String source_id (candidate_source_id = None): Delegate service.read(token, None, None) (or reject at the service auth gate). Both unknown tokens and known tokens receive 403 denied (503 unavailable if service is draining/closed). Zero binding leases are acquired and zero filesystem I/O occurs.

- Extractable String source_id (isinstance(candidate_source_id, str) with malformed/invalid remaining schema): Delegate service.read(token, candidate_source_id, None):

- Unknown/lexically invalid token $\rightarrow$ _policy_table.authenticate raises PolicyDeniedError $\rightarrow$ 403 denied.

- Known token + unauthorized candidate_source_id (no "read" grant) $\rightarrow$ _policy_table.authorize raises PolicyDeniedError $\rightarrow$ 403 denied.

- Known token + authorized candidate_source_id ("read" grant present) $\rightarrow$ _authenticate_and_authorize succeeds, and _parse_canonical_parts(None, allow_root=False) immediately raises ServiceError("invalid") $\rightarrow$ 400 invalid prior to _acquire_binding_lease or any filesystem I/O.

3. Test Suite Correction Justification: Any test asserting 400 invalid for {known token + raw malformed JSON with unextractable source_id} assumes a standalone token-authentication boundary that does not exist in the frozen capability-based backend (where capability resolution requires (token, source_id, op)). Correct those test expectations to 403 denied.

- Conditional Escape Hatch (Not Recommended unless Director Unfreezes Service API): Returning 400 invalid on {known token + unextractable source_id} without touching _policy_table is strictly impossible unless DriveService adds a narrow public method authenticate_token(self, token: Any) -> None (calling self._ensure_not_draining() and self._policy_table.authenticate(token)). Unless b7f8d17 is explicitly unfrozen for that single method, enforce uniform 403 denied on candidate_source_id=None.

## 2. Content-Length (10+ Digits, Leading Zeros, Bounded Conversion) Adjudication

To preserve D080 priority (Syntax $\rightarrow$ Lexical/Token Auth $\rightarrow$ Magnitude Cap) without unbounded int() conversion or misclassifying huge numbers as 400 invalid:

1. Stage 1 — Strict Lexical Syntax Check (400 invalid, Pre-Auth):

- Content-Length must consist solely of ASCII digits ('0' <= ch <= '9', non-empty, no signs, no whitespace, no conflicting duplicate headers).

- Leading Zeros Rule: Reject multi-digit strings with a leading zero (len(raw) > 1 and raw[0] == '0', e.g., "00", "01", "0000000001") as 400 invalid at the syntax stage; only single "0" is a valid zero length. (This prevents zero-padded 10+ digit strings from bypassing value semantics or falsely triggering 413 too_large.)

2. Stage 2 — Bounded Conversion (Overflow Sentinel, No Unbounded int()):

- After Stage 1 passes, the string matches ^(0|[1-9][0-9]*)$.

- If len(raw) >= 10 (i.e. numeric value $\ge 10^9 > \text{MAX\_BODY\_BYTES}$), do not raise 400 invalid and do not call unbounded int(raw) (stopping arbitrary-precision integer DoS); assign bounded sentinel parsed_length = MAX_BODY_BYTES + 1.

- If len(raw) <= 9, compute parsed_length = int(raw) in bounded $O(1)$ time.

3. Stage 3 — Auth Gate Before Cap Reporting (403 denied vs. 413 too_large):

- Perform token authentication/authorization check (or lexical token check per D080) before surfacing 413 too_large.

- Unknown/invalid token with 10+ digit valid-syntax Content-Length $\rightarrow$ 403 denied.

- Authenticated request with parsed_length > MAX_BODY_BYTES (including the 10+ digit sentinel) $\rightarrow$ 413 too_large before reading body bytes.

## 3. Adopted Regression Matrix

| Scenario | Token State | Content-Length Header | Body / source_id State | Expected HTTP Status & Code | Lease / FS I/O |
| --- | --- | --- | --- | --- | --- |
| Non-digit, negative, empty, or multi-digit leading zero ("00", "0000000001") | Any (Known or Unknown) | Malformed syntax | Any (unread) | 400 invalid | None |
| Huge valid digits (10+ digits, e.g., "9999999999", no leading zero) | Unknown / Invalid | Valid syntax, $> \text{cap}$ | Any (unread) | 403 denied | None |
| Huge valid digits (10+ digits, e.g., "9999999999", no leading zero) | Known & Authorized | Valid syntax, $> \text{cap}$ | Any (unread) | 413 too_large | None |
| Valid Content-Length $\le \text{cap}$ | Unknown / Invalid | Valid syntax, $\le \text{cap}$ | Malformed JSON (source_id unextractable) | 403 denied | None |
| Valid Content-Length $\le \text{cap}$ | Known | Valid syntax, $\le \text{cap}$ | Malformed JSON or missing source_id (candidate_source_id=None) | 403 denied (test corrected from 400) | None |
| Valid Content-Length $\le \text{cap}$ | Known (no "read" grant on source_id) | Valid syntax, $\le \text{cap}$ | Invalid schema, extractable source_id | 403 denied | None |
| Valid Content-Length $\le \text{cap}$ | Known (has "read" grant on source_id) | Valid syntax, $\le \text{cap}$ | Invalid schema (file_id missing/bad), extractable source_id | 400 invalid (via service.read(token, src, None)) | None |
| Service draining or closed | Any | Valid syntax | Any delegating to service | 503 unavailable | None |

TESTS_NOT_RUN
