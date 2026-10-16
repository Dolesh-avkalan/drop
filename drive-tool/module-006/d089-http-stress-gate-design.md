# d089 (gemini)

- status: done
- chat: https://gemini.google.com/app/6b4b75afbc8f408d
- model: 4 argon (thinking: high)
- finished: 2026-10-16T00:45:50Z

## Question

Gemini, concise rigorous stress-gate workload adjudication D089. Distinguish validbelowcapacitysuccess from expectedsaturationbusy/readonlydenial; unexpectedunavailable remainsblockingpendingD088. No thresholdrelaxation/resultsfitting or implementation. Exactreplayablecriteria before rerun, retainoldFAILhistory. StaticTESTS_NOT_RUN.

(input files: Dolesh-avkalan/drive-tool:tasks/d089-http-stress-gates.txt@c8ed19d931ddb72ccefd4b9feca8a9ac7c817060)

## Answer

D089 Adjudication Verdict: The D085 (7dab4357) smoke600 failure (busy = 28..32) and soak10000 busy count (busy = 300..326) are deterministic protocol artifacts of driving a 6-slot, zero-queue server adapter (cc1cd326 / 8cd137f7) with 6 unpaced closed-loop clients across a 50ms post-response server drain window, whereas soak10000 unavailable = 6..7 is a genuine, unexplained defect that remains a hard release blocker pending D088. Threshold relaxation, blanket error budgets, and blind retries are rejected.

### 1. Root-Cause Attribution & Counterexample Preservation
#### Protocol Mechanics of the C=6 Overlap

The HTTP adapter enforces $S = 6$ hard slots with zero queue (busy on slot exhaustion). Each server worker holds its slot for:

$$T_{\text{slot}} = T_{\text{service}} + T_{\text{drain}} \quad (\text{where } T_{\text{drain}} = 50\text{ ms})$$

Because the HTTP response is flushed to the client at $T_{\text{service}}$ before $T_{\text{drain}}$ completes, an unpaced closed-loop client turns around in $T_{\text{turnaround}} \ll 50\text{ ms}$ and dispatches its next request while its previous server worker is still draining. With $C = 6$ unpaced clients, actual server slot demand spikes to $6 + k$ (for $k \in \{1..6\}$ draining workers), deterministically triggering busy. At $C \in \{4, 5\}$, residual slack absorbs single-worker drain overlap (busy = 0).

#### Immutable Historical Counterexamples (Retain FAIL History)

The D085 (7dab4357) test records must be retained intact in the audit log as baseline counterexamples prior to any rerun:

| Historical Run (7dab4357) | Mode | Requested | Busy | Denied | Unavailable | Resource / Lifecycle | Retained Disposition |
| --- | --- | --- | --- | --- | --- | --- | --- |
| smoke600 ($C=4, 5$) | Diagnostic probe | 600 | 0 | Per policy | 0 | fd 11 to 4, threads 1 to 8 to 1, closed=True | Empirical capacity boundary |
| smoke600 ($C=6$ unpaced) | Gated acceptance | 600 | 28–32 | Per policy | 0 | fd 11 to 4, threads 1 to 8 to 1, closed=True | FAIL (Retained) — unpaced drain collision |
| soak10000 ($C=6$ unpaced) | Diagnostic (post-fail) | 10,000 | 300–326 | 320 (RO saves) | 6–7 | fd 11 to 4, threads 1 to 8 to 1, closed=True | FAIL (Retained) — unpaced collision + BLOCKING D088 unavailable |

### 2. Orthogonal Telemetry & Accounting Rules

Every stress gate must classify operations by pre-dispatch intent and terminal outcome with zero blind save retries (retries corrupt arrival-rate invariants and mask transient unavailable states):

$$\text{Requested} = \text{Completed} + \text{Incomplete}$$
$$\text{Completed} = \underbrace{\text{valid\_below\_capacity\_success}}_{\text{Authorized op } \to \text{ HTTP OK}} + \underbrace{\text{expected\_saturation\_busy}}_{\text{Overload probe } \to \text{ Busy}} + \underbrace{\text{expected\_readonly\_denial}}_{\text{RO save probe } \to \text{ Denied}} + \underbrace{\text{unexpected\_unavailable}}_{\text{Hard blocker (D088)}} + \underbrace{\text{unexpected\_other\_error}}_{\text{Busy below cap / 5xx / timeout}}$$

- No Cross-Bucket Masking: A busy response during a below-capacity workload is counted in unexpected_other_error (gate FAIL), never in expected_saturation_busy.

- Deterministic Policy Attribution: denied is valid if and only if the request was dispatched by a read-only agent executing a save operation (expected_readonly_denial). Any denied on a read/list/search or authorized write, or any OK on a read-only save, is an immediate gate FAIL.

- Zero Tolerance on unavailable: unexpected_unavailable must equal 0 across all gates. No percentage or count budget is permitted.

### 3. Six-Agent Workload Split & Occupancy Bounding

To test all 6 agent personas without altering production adapter code (cc1cd326 / 8cd137f7), the stress suite is split into two orthogonal, deterministic tracks:

#### Track A: Below-Capacity Six-Agent Stress (smoke600 & soak10000)

- Six-Agent Persona Preservation: All 6 distinct agent state machines (including read-only agent personas) execute their deterministic operation schedules (600 total ops for smoke600; 10,000 total ops including 320 scheduled read-only saves for soak10000).

- Server Occupancy Bound (No Adapter Changes): The client harness mediates dispatch through a Drain-Aware Lease Limiter with capacity $K = 5$ active leases (or $K = 6$ with strict per-slot post-response drain hold):

1. An agent worker acquires one of $K = 5$ client leases before sending a request.

2. Upon receiving the HTTP response, the lease enters a mandatory client-side drain hold of $T_{\text{hold}} \ge 55\text{ ms}$ ($\ge T_{\text{drain}} = 50\text{ ms}$ plus scheduling margin) before returning to the pool for the next agent turn.

3. This guarantees actual in-flight plus draining server slot occupancy remains strictly $\le 5$ (below the 6-slot ceiling) while all 6 agents interleave continuously.

#### Track B: Deterministic 6+1 Saturation Gate

- Dedicated Overload Verification: Conducted as a separate, deterministic sub-gate rather than relying on stochastic closed-loop collisions.

- Mechanism: Hold 6 server slots concurrently (via 6 barrier-synchronized in-flight requests or 6 requests within their active service/drain window) and dispatch $M$ additional probes (minimum $+1$ per barrier cycle, e.g., 50 barrier cycles).

- Assertion: The 6 admitted requests succeed (valid_below_capacity_success == 6 per cycle) and the $+1$ excess probe deterministically returns busy (expected_saturation_busy == 1 per cycle, unexpected_unavailable == 0).

### 4. Exact Replayable Pass/Fail Criteria (Pre-Rerun Specification)

No rerun may claim acceptance unless the seed/schedule is pinned prior to execution and satisfies every invariant below:

| Gate Track | Total Scheduled (Requested) | valid_below_capacity_success | expected_readonly_denial | expected_saturation_busy | unexpected_unavailable | unexpected_other_error (incl. unscheduled busy) | Resource & Lifecycle Bounds |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1. smoke600 (6-Agent Below-Capacity) | $600$ ($N_{\text{valid}} + N_{\text{ro\_save}}$) | Exactly $N_{\text{valid}}$ (e.g., $580$ if $N_{\text{ro\_save}}=20$) | Exactly $N_{\text{ro\_save}}$ ($100\%$ of RO saves) | $0$ | $0$ | $0$ | fd: 11 to 4, threads: 1 to 8 to 1, closed == True, 50ms drain intact |
| 2. soak10000 (6-Agent Below-Capacity) | $10,000$ ($9,680$ valid $+ 320$ RO saves) | Exactly $9,680$ | Exactly $320$ ($100\%$ of RO saves) | $0$ | $0$ (Blocked by D088) | $0$ | fd: 11 to 4, threads: 1 to 8 to 1, closed == True, zero residue |
| 3. saturation_6plus1 (Deterministic Overload) | $7 \times R$ cycles | Exactly $6 \times R$ | $0$ | Exactly $1 \times R$ | $0$ | $0$ | fd: 11 to 4, threads: 1 to 8 to 1, closed == True, zero queue intact |

#### Dependency Hold Conditions

1. D088 Blocker: soak10000 cannot pass acceptance until D088 isolates and resolves the root cause of the 6–7 unavailable responses and unexpected_unavailable == 0 is demonstrated on replay.

2. D087 Alignment: Close-budget verification remains tracked under D087; stress gates must continue asserting closed == True, fd return to 4, and threads return to 1 with zero leaked descriptors or workers.

TESTS_NOT_RUN
