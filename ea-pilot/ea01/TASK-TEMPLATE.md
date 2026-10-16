# TASK-TEMPLATE

Objective: [One sentence: the decision-ready output this job must produce.]

Allowed paths/actions: Write only new task files under [tasks/inbox/...] and one output
folder [deliverables/<job-id>/]. Everything else read-only. No edits to existing repo
files, no external side effects.

Acceptance criteria:

- [Criterion 1: what must be true in the final artifact]
- [Criterion 2: format/schema/section requirements]
- [Criterion 3: evidence attached for every claim]

Budget: Max [N] child jobs (default 5); max [N] answer words in final deliverable
(default 400); max [N] hours wall-clock (default 2). Every child task file written counts
as one job, whether it ends done, failed, or blocked. Wall-clock is elapsed time from EA
job receipt, checked before every dispatch. The director may lower any of these here.

Evidence required: Per child task: task id, dispatch commit, status, model pin, artifact
path + hash, the concrete checks you performed (hash recomputed, criterion re-read), and
known gaps. Final manifest at [deliverables/<job-id>/MANIFEST.md]. Example row:
`| <task-id> | <dispatch-commit> | done | <model pin> | <artifact path> | sha256 <hash> | artifact opened; path resolved; criterion 1 re-read | none |`.

Escalation rule: Stop and return to the director if any decision is consequential (scope
change, irreversible write, budget overrun, conflicting evidence, or uncertainty you
cannot resolve after the allowed correction rounds). Otherwise proceed autonomously. A
child returning no artifact, a wrong path, or unparseable content is treated as an absent
artifact — a BLOCKED condition, never a pass.

# CORRECTION-AND-EVIDENCE-WORKFLOW

(a) Verify before trusting. For each returned child artifact: confirm the task file
exists, the dispatch commit matches, and the artifact path resolves. Open the artifact
itself; do not accept the teammate's verdict as evidence. Recompute any hash, re-read any
quoted source, and check the acceptance criterion directly. If verification fails, treat
the artifact as absent.

(b) Fix ordinary defects. Run at most 2 bounded correction rounds (default max = 2; the
director may lower it in the TASK-TEMPLATE). Each round: write a fresh, uniquely named
child task (e.g. `fix-<job>-r1-<slug>`), scoped to the single defect, with the same
evidence requirements. Never auto-retry a write whose outcome is uncertain; instead mark
it needs-director and stop that branch. No silent retries, no reusing a prior task id.

(c) Evidence manifest. Record per child task: task id; dispatch commit; status
(done/failed/blocked); model pin; artifact path and hash; the concrete checks you
personally performed (hash recomputed, criterion re-read — not just a status); and
explicit gaps or unresolved questions. Append one row per task; keep the manifest
chronological. The manifest is the audit trail, not a summary.

(d) Stop rule. End the loop when either: all acceptance criteria are met with verified
evidence and no open gaps; or a correction round fails to resolve a defect, a budget
limit is hit, or an escalation trigger fires. Once any stop condition fires, the EA
writes no further task files. On stop, hand the director the deliverable path plus the
manifest, and state plainly what is verified, what is uncertain, and what decision is
needed. Do not continue past the stop rule.
