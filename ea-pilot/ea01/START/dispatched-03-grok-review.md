agent: grok
chat: new
model: expert
project: ea-pilot
timeout_min: 25
after: ea01-child-deepseek-template
read: Dolesh-avkalan/drop:ea-pilot/ea01/child/01-deepseek-template.md@main
save_to: ea-pilot/ea01/child/03-grok-costquality.md
---
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
