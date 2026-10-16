# ea01-child-grok-review (grok)

- status: done
- chat: https://grok.com/c/596bb6c5-0fe6-4f21-b032-67fd6d77e698?rid=6959af8f-8334-4f7f-b25a-ff147bcc8bbb
- model: expert (thinking: -)
- finished: 2026-10-16T15:36:52Z

## Question

You are an independent reviewer. The input file above is a draft `TASK-TEMPLATE`
and `CORRECTION-AND-EVIDENCE-WORKFLOW` written by another teammate. Judge it against
cost/quality acceptance criteria. No browsing, no code. Keep the whole answer under
600 words.

Acceptance criteria to check the draft against:
- Usable as-is by a busy director - copy-paste, no ambiguity.
- Keeps cost bounded - states a task/job budget and a stop rule.
- Produces verifiable evidence - task id, commit, status, model pin, artifact, gaps.
- Bounded corrections - no open-ended loop.
- Separates routine EA decisions from escalated ones.

Produce a `# COST-QUALITY REVIEW` with:
1. Verdict - PASS / PASS-WITH-FIXES / FAIL.
2. Up to five concrete defects, each with a one-line fix.
3. A short "missing for practical usefulness" list.
4. One line on whether the draft survives a cost-overrun scenario.

Critique and fix; do not rewrite the whole draft. Plain Markdown only.

(input files: Dolesh-avkalan/drop:ea-pilot/ea01/child/01-deepseek-template.md@main)

## Answer

# COST-QUALITY REVIEW
1. Verdict: PASS-WITH-FIXES
2. Defects (up to five):
- Correction-round cap is a blank “[2]” with no default or tie to the brief’s budget. Fix: Set default max = 2 and state “director may lower it in the TASK-TEMPLATE”.
- Wall-clock budget lacks an operational definition (start moment, inclusion of waits). Fix: Define as elapsed time from EA job receipt, checked before every dispatch.
- No rule that every dispatched child job (done/failed/blocked) counts against the max-N budget. Fix: Add “every child task file written counts as one job”.
- Escalation text (“within one bounded correction round”) conflicts with the stated max of two rounds. Fix: Change to “after the allowed correction rounds”.
- Verification does not require the manifest to record the concrete checks performed. Fix: Mandate each row list the checks (hash recomputed, criterion re-read, etc.).
1. Missing for practical usefulness:
- Recommended defaults for budget numbers (e.g., 5 jobs / 400 words / 2 h).
- One-line example of a completed manifest row.
- Explicit handling when a child returns no artifact, wrong path, or unparseable content.
- Statement that the EA writes no further task files once any stop condition fires.
1. Cost-overrun survival: Survives — explicit budget, stop rule that halts on limit, and escalation that returns the partial deliverable plus manifest to the director.
