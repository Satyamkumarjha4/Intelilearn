---
description: Run or resume the one-time Socra pre-launch audit (docs/audit/RUNBOOK.md)
---

You are the orchestrator of the Socra pre-launch audit.

Argument: `$ARGUMENTS` (either `start` or `resume`; with no argument, use `resume` if any `docs/audit/*/STATUS.md` exists, otherwise `start`).

1. Read `docs/audit/RUNBOOK.md` and `docs/audit/AUDIT-RULES.md` in full.
2. `start`: create the run folder for today and begin at Stage −1.
   `resume`: open the latest `docs/audit/<run>/STATUS.md` and continue from the first stage that isn't `done`.
3. Follow the runbook exactly:
   - stop at the checkpoints;
   - send one status line to the user after each stage;
   - keep your own context small by reading only report summaries.
4. Never print secret values. Never merge or push, except where Stage −1 says to (ship-branch PRs, the audit-prep PR, the baseline tag) and the final reports PR.
