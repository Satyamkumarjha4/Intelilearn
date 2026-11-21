# Socra audit kit: how to use it

## Install

1. Unzip this kit into the **root of the Socra repo**. It adds:
   - `.claude/agents/audit-*.md`: 14 specialist agents, each with its model and effort set;
   - `.claude/commands/audit.md`: the `/audit` command;
   - `docs/audit/RUNBOOK.md`, `AUDIT-RULES.md` and `STATUS.template.md`.
2. Don't commit the kit yourself. Stage −1 commits it to `main` in the audit-prep PR.
3. Open a **new** Claude Code session in the repo. Set the main session to **Sonnet 5.5, high effort**; it orchestrates and does the Stage −1 merges. The subagents use their own models: Opus for the judgment-heavy stages, Sonnet for the mechanical ones.

## Start

Type `/audit start` and send the kickoff prompt below.

## Resume (after a break, or in a new session)

Type `/audit resume`.

## Where you're needed (4 checkpoints)

1. Approve the branch list and merge order.
2. Approve the product brief. **Read the business-rules table carefully**, because it's what everything is tested against. Also approve the slice plan and the live LLM test plan.
3. Approve the live LLM budget.
4. Read the final verdict and fix plan.

## Kickoff prompt (main session: Sonnet 5.5, high effort)

```
/audit start

This is the one-time deep pre-launch audit. Follow docs/audit/RUNBOOK.md exactly.

- Stage −1 first: inventory all branches, show me the classification at Checkpoint 1, then merge the
  ship branches into main through PRs with GitHub CI green (fix CI at the root cause, never skip or
  weaken tests), add the audit prep (scripted fake LLM with failure injection, make audit-up/down
  MODE=mock|live, audit_seed personas) in its own PR, and tag the baseline.
- Then run every stage in order with the specified agents, parallel where the runbook allows, never
  more than 3 at once and only one stage owning the stack (my machine is low on memory:
  PYTEST_WORKERS=4, E2E_WORKERS=2).
- Audit only: after Stage −1 no code changes; every finding comes with a recommended fix, and
  X3 writes FIX-PLAN.md.
- Stop at the 4 checkpoints. Between them, send me one status line per stage.
- Never print secrets, never use real learner data, live LLM calls on synthetic inputs only and within
  LIVE_MAX_COST_USD.
- The pending phase-m items are covered: the validator topic probes run inside L1; failed-output
  capture goes into the fix plan.
```
