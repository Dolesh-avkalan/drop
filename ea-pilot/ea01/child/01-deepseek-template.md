# ea01-child-deepseek-template (deepseek)

- status: done
- chat: https://chat.deepseek.com/a/chat/s/f461f5e2-bcc2-42f8-bf17-2633c88b385f
- model: deepseek (deepthink off, search off)
- finished: 2026-10-16T15:34:26Z

## Question

Draft two reusable artifacts for a director who delegates scoped work to an
execution-coordinator (EA). Answer from your own reasoning; no browsing, no code.
Keep the whole answer under 600 words.

Context: the director writes ONE brief. The EA runs the middle of the job - it
dispatches scoped child tasks to AI teammates over a git-based task bus, collects
their results, verifies evidence, assembles deliverables, and does bounded
corrections. Consequential decisions go back to the director. The EA may write only
new task files and one output folder; the default is read-only.

Produce exactly two Markdown artifacts, in this order:

1. `# TASK-TEMPLATE`
A compact, copy-paste brief a director hands the EA for one job. Include these fields:
objective; allowed paths/actions; acceptance criteria; budget (max child jobs /
answer words / time); evidence required; escalation rule. Keep it under ~180 words,
generic and fill-in-the-blank.

2. `# CORRECTION-AND-EVIDENCE-WORKFLOW`
The routine loop the EA runs: (a) how it verifies a teammate's artifact before
trusting any verdict; (b) how it fixes ordinary defects - bounded rounds, fresh
uniquely named child jobs, never auto-retry an uncertain write; (c) what belongs in
an evidence manifest (task id, dispatch commit, status, model pin, artifact
path/hash, what was personally verified, gaps); (d) a stop rule that ends the loop.

Plain Markdown only, no preamble.

## Answer

# TASK-TEMPLATE

Objective: [One sentence: the decision-ready output this job must produce.]

Allowed paths/actions: Write only new task files under [tasks/inbox/...] and one output folder [deliverables/<job-id>/]. Everything else read-only. No edits to existing repo files, no external side effects.

Acceptance criteria:

- [Criterion 1: what must be true in the final artifact]

- [Criterion 2: format/schema/section requirements]

- [Criterion 3: evidence attached for every claim]

Budget: Max [N] child jobs; max [N] answer words in final deliverable; max [N] hours wall-clock.

Evidence required: Per child task: task id, dispatch commit, status, model pin, artifact path + hash, what you personally verified, known gaps. Final manifest at [deliverables/<job-id>/MANIFEST.md].

Escalation rule: Stop and return to director if any decision is consequential (scope change, irreversible write, budget overrun, conflicting evidence, or uncertainty you cannot resolve within one bounded correction round). Otherwise proceed autonomously.

# CORRECTION-AND-EVIDENCE-WORKFLOW

(a) Verify before trusting. For each returned child artifact: confirm the task file exists, the dispatch commit matches, and the artifact path resolves. Open the artifact itself; do not accept the teammate's verdict as evidence. Recompute any hash, re-read any quoted source, and check the acceptance criterion directly. If verification fails, treat the artifact as absent.

(b) Fix ordinary defects. Run at most [2] bounded correction rounds. Each round: write a fresh, uniquely named child task (e.g. fix-<job>-r1-<slug>), scoped to the single defect, with the same evidence requirements. Never auto-retry a write whose outcome is uncertain; instead mark it needs-director and stop that branch. No silent retries, no reusing a prior task id.

(c) Evidence manifest. Record per child task: task id; dispatch commit; status (done/failed/blocked); model pin; artifact path and hash; what you personally verified (not what the teammate claimed); and explicit gaps or unresolved questions. Append one row per task; keep the manifest chronological. The manifest is the audit trail, not a summary.

(d) Stop rule. End the loop when either: all acceptance criteria are met with verified evidence and no open gaps; or a correction round fails to resolve a defect, a budget limit is hit, or an escalation trigger fires. On stop, hand the director the deliverable path plus the manifest, and state plainly what is verified, what is uncertain, and what decision is needed. Do not continue past the stop rule.
