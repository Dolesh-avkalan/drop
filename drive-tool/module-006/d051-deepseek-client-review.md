# d051 (deepseek)

- status: done
- chat: https://chat.deepseek.com/a/chat/s/05bee4d4-aa03-49ad-b621-e4427cbdf8df
- model: deepseek (deepthink on, search off)
- finished: 2026-10-15T17:16:07Z

## Question

DeepSeek, review the entire supplied pinned production client against its director wire contract, D051. This is independent static review while local Sarvam finishes client evidence. Do not write another client or duplicate policy checks. Exact intermediate snapshot81a6485; any later production change needs delta review. Give verdict and concrete malformed-server counterexamples with functions/lines, quote actual code, identify scope/limits, TESTS_NOT_RUN. No source changes, installs, merge/deploy. Compact versioned file input supplied inline as necessary fallback. End STATUS: REVIEWED.

(input files: Dolesh-avkalan/drive-tool:tasks/d051-client-review.txt@8eac68b98481b86e7ae164a5835063584c15fdcb)

## Answer

Verdict: CHANGES REQUIRED

Scope: Static review only of pinned intermediate snapshot 81a6485 (candidate81a6485c300f0a9cecc9c902c90360379c17e946), inline service_client.py. Local Sarvam evidence not reviewed. TESTS_NOT_RUN. No source changes, installs, merge/deploy. Not final acceptance; later production blob change needs delta re-review.

Primary finding — body-read transport errors are not wrapped in DriveClientError:
In _dispatch, only conn.request() / conn.getresponse() are inside the _wrap_transport mapping. Body reads call _read_capped, which does:

```python
data = resp.read(cap + 1)
```

but the outer handler only catches:

```python
except _ProtocolError:
    raise DriveClientError(
        "unavailable", outcome_uncertain=write_op, retry_safe=not write_op
    ) from None
```

So a malformed/slow server that sends headers then stalls or truncates during body read can raise raw TimeoutError, http.client.IncompleteRead, ConnectionResetError, or malformed-chunked HTTPException out of the client. Counterexample: read request; server sends HTTP/1.1 200 OK, Content-Length: 100, then stalls. resp.read(cap + 1) raises TimeoutError; caller sees TimeoutError, not DriveClientError("timeout", outcome_uncertain=False, retry_safe=True). For save, the required conservative outcome_uncertain=True, retry_safe=False is also bypassed. Violates safe error mapping, redaction, and save uncertainty contract.

Secondary NIT — duplicate Content-Length not rejected:
_read_capped uses:

```python
declared = resp.getheader("Content-Length")
```

not get_all. A malformed server can send duplicate Content-Length; if the first is <= cap, the duplicate is not detected. Counterexample: Content-Length: 2 then Content-Length: 100000 with body {}; client may accept based on first. Observation headers correctly use get_all; content-length duplicate handling is weaker.

Secondary NIT — duplicate Content-Type for read not rejected:
_build_read_reply uses resp.getheader("Content-Type"). Counterexample: first Content-Type: application/octet-stream, second Content-Type: text/plain; client accepts first. If duplicate content headers must fail closed, this is a gap.

Compliance positives: Constructor validation is before network; token repr redacts; per-call fresh HTTPConnection and close in finally; Authorization, Connection: close, exact JSON/raw wire paths and save query encoding; bounded cap+1 read logic; observation header duplicate checks via get_all; exact-fill EOF rejection (if received == request_length and eof_observed:); no automatic retries; read-only vs write uncertainty defaults are mostly correct.

Limits: No dynamic tests or local Sarvam evidence. Counterexamples are static reasoning from stdlib http.client behavior. Only this pinned snapshot is reviewed. TESTS_NOT_RUN.

STATUS: REVIEWED
