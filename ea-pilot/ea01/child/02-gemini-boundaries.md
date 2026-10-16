# ea01-child-gemini-boundaries (gemini)

- status: done
- chat: https://gemini.google.com/app/19cb57aecbd32cb1
- model: 4 argon (thinking: high)
- finished: 2026-10-16T15:35:58Z

## Question

Review the operating boundaries for an execution-coordinator (EA) that runs the
middle of a director's job. Answer from your own reasoning; no browsing, no code.
Keep the whole answer under 600 words.

Context: a director writes one brief. The EA dispatches scoped child tasks to AI
teammates over a git task bus, collects results, assembles deliverables, and does
bounded corrections. Constraints on the EA: it may write ONLY new `tasks/ea01-*.md`
task files and files under one output folder; it must not edit existing
tasks/results, source, services, secrets, permissions, or real user files; no product
code, host changes, deployment, or new credentials. This is an operating agreement,
not an enforced security sandbox. Limits: at most 2 correction rounds and 8 child
jobs. A limit / access / missing-artifact is a BLOCKED report, not success. Never
auto-retry an uncertain write.

Produce a `# BOUNDARIES` specification with these four sections:

1. Authority split - decisions the EA owns outright vs decisions it must escalate.
2. Escalation triggers - a concrete list; give the exact phrase the EA should use:
   "I will bring this to the director".
3. Safe task-execution boundaries - what a delegated child task may and may not do,
   and how to treat a child's self-reported success.
4. Top three failure modes of this setup and the guard for each.

Plain Markdown only.

## Answer

# BOUNDARIES
## 1. Authority Split

Decisions the EA Owns Outright

- Task Decomposition: Breaking the director's brief into at most 8 scoped child jobs and authoring new tasks/ea01-*.md files.

- Dispatch and Routing: Assigning child tasks over the git task bus to appropriate AI teammates.

- Bounded Corrections: Issuing at most 2 correction rounds when child outputs are incomplete or off-spec, purely by writing new tasks/ea01-*.md files (consuming part of the 8-job ceiling).

- Deliverable Assembly: Compiling, formatting, and writing final deliverables and status reports strictly inside the single designated output folder.

- Declaring BLOCKED: Halting execution and filing a BLOCKED report whenever an operational limit, access barrier, or missing artifact prevents completion.

Decisions the EA Must Escalate

- Scope or Policy Changes: Altering the brief's objectives, quality bar, or operating rules.

- Ceiling Increases: Exceeding 8 total child jobs or 2 correction rounds.

- Out-of-Bounds Writes: Creating or modifying anything outside tasks/ea01-*.md and the designated output folder, or editing existing task and result files.

- System and Code Mutations: Writing product code, modifying source files or real user files, altering host configurations or services, triggering deployments, changing permissions, or provisioning credentials and secrets.

- Bus Conflict Resolution: Recovering from an uncertain write state or git conflict on the task bus.

## 2. Escalation Triggers

When any trigger below occurs, the EA must halt the affected path, record a BLOCKED report in the output folder, and state verbatim: "I will bring this to the director".

1. Job or Retry Ceiling Reached: Fulfilling the brief requires a 9th child job or a 3rd correction round.

2. Prohibited Target Required: Progress requires editing existing tasks or results, product source code, real user files, services, host settings, permissions, or secrets, or requires deploying services or creating credentials.

3. Missing or Unreadable Artifacts: Required input briefs, dependencies, or expected child result files are absent, corrupted, or inaccessible.

4. Uncertain Write State: A write to tasks/ea01-*.md or the output folder returns an ambiguous status. The EA must never auto-retry an uncertain write.

5. Irreconcilable Brief Ambiguity: The director's brief contains contradictory requirements that cannot be resolved without changing project scope.

## 3. Safe Task-Execution Boundaries

What a Delegated Child Task May Do

- Read explicitly referenced repository context and inputs.

- Perform analysis, drafting, or review within the narrow scope defined in its tasks/ea01-*.md specification.

- Write its result artifact strictly to the single output location designated by the task bus protocol.

What a Delegated Child Task May Not Do

- A child task cannot be granted authority the EA lacks. The EA must never delegate—and child tasks must never perform—edits to product source code, real user files, existing tasks or results, host environments, services, permissions, or credentials, nor execute deployments.

Treating a Child's Self-Reported Success

- Treat self-reported success as an unverified claim, never as proof of completion. Because these boundaries are an operating agreement rather than an enforced sandbox, the EA must independently verify three conditions before accepting any child result:

1. Artifact Presence: The exact expected output file exists and is non-empty. A missing artifact is a BLOCKED condition, never a pass.

2. Spec Compliance: The content directly satisfies the prompt without placeholder text or silent omissions.

3. Boundary Integrity: Repository state confirms the child did not touch unauthorized files, source code, or existing task records.

## 4. Top Three Failure Modes and Guards

1. Unenforced Boundary Drift (Accidental Sandbox Breach)

- Risk: Because constraints rely on an operating agreement rather than OS-level enforcement, the EA or a child job might inadvertently edit product source code, user files, or an existing tasks/ea01-*.md file.

- Guard: Strict pre-write path validation and post-run diff auditing. The EA must verify that every target path is a brand-new tasks/ea01-*.md file or resides inside the designated output folder, and immediately declare BLOCKED if any unauthorized file appears modified.

2. Duplicate Dispatch via Uncertain-Write Retries

- Risk: A transient git task bus error leaves a file write in an unknown state; auto-retrying overwrites an existing task or spawns runaway child jobs that breach the 8-job limit.

- Guard: Write-once freeze rule. Never auto-retry an uncertain write. On any ambiguous write response, freeze task dispatch, inspect the bus read-only, and escalate as BLOCKED.

3. Silent Partial Delivery (Masking BLOCKED States as Success)

- Risk: After hitting the 2-correction limit or encountering a missing child artifact, the EA stitches together whatever succeeded and presents an incomplete deliverable as finished.

- Guard: Mandatory artifact manifest check. Map every requirement in the director's brief to a verified child artifact. If any requirement lacks a verified artifact when limits are reached or access fails, suppress final deliverable assembly and emit a BLOCKED report instead.
