# Socra full pre-launch audit — runbook (one-time, deep)

This is a one-time, deep audit before the first deployment. It finds problems and recommends fixes. The only code it changes is in Stage −1: consolidating branches, getting CI green, and preparing mock mode. After the first deployment, a separate and lighter re-check procedure will be built.

**You, the main session, are the orchestrator.** Run the stages in order. Hand each stage to its subagent in `.claude/agents/` and keep your own context small:
- Read only the summary and counts of each report, never the whole report.
- Pass file paths to agents, not file contents.

## Run setup

- `<run>` = today's date, `YYYY-MM-DD`. Create `docs/audit/<run>/`.
- Copy `docs/audit/STATUS.template.md` to `docs/audit/<run>/STATUS.md`. Update it after every stage; it is how a new session resumes.
- Every subagent prompt starts with:
  `Run: <run>. Baseline tag: audit-baseline-<run>. Read docs/audit/AUDIT-RULES.md first, then your scope below.`
  After that comes the slice, if there is one, and anything the stage depends on (the paths of earlier reports).

## Stages

| # | Stage | Agent | Model / effort | Needs | Mode | Owns stack? |
|---|---|---|---|---|---|---|
| −1 | Consolidate branches, CI green, audit prep, baseline tag | you (orchestrator) | main session | — | — | yes |
| 0 | Product brief + scope map | `audit-product-brief` | Opus / high | −1 | — | no |
| B1 | Backend code quality & design | `audit-backend-quality` | Opus / high | 0 | — | no |
| B2 | Backend functionality, spec compliance, dead code | `audit-backend-functionality` | Opus / high | 0 | mock (tests only) | no |
| B3 | Backend security & privacy | `audit-backend-security` | Opus / xhigh | 0 | mock | short, for probes |
| B4 | Backend deployment readiness | `audit-backend-deploy` | Sonnet / high | B3 | — | no |
| F1 | Frontend design, UX, a11y, performance | `audit-frontend-design` | Opus / high | 0 | mock | **yes** |
| F2 | Frontend code quality | `audit-frontend-code` | Opus / high | 0 | — | no |
| F3 | Frontend security | `audit-frontend-security` | Opus / high | 0 | — | no |
| L1 | LLM output quality, prompts, cost per lesson | `audit-llm-quality` | Opus / high | B2 | **live** + mock | **yes** |
| X1 | Frontend ↔ backend integration contract | `audit-integration` | Sonnet / high | B1–B3, F2 | mock | yes, for probes |
| X2 | Full click-through demo | `audit-clickthrough` | Sonnet / high | X1 | mock, then live happy paths | **yes** |
| V | Skeptic verification of every Critical/High | `audit-skeptic` | Opus / high | all above | mock | for proofs |
| D1 | Whole-system deployment & infra security (VPS; Vercel/Render) | `audit-deployment` | Opus / high | B3, B4, F3, X1 | — | short |
| X3 | Release gate: merged report, verdict, fix plan | `audit-release-gate` | Opus / high | V, D1 | — | no |

### Order and parallelism

Never more than 3 subagents run at once, and never two that own the stack.

1. Stage −1, then **Checkpoint 1**.
2. Stage 0, then **Checkpoint 2**.
3. **Backend wave:** B1, B2 and B3 in parallel, including slices (at most 3 running at once). B3's local probes need the stack, so start it once for B3 and run the probes when no other agent needs it. Then B4.
4. **Frontend wave:** F1 owns the stack. F2 and F3 run in parallel with it, since they only read code.
5. **Checkpoint 3**, before any live spend. Then L1, which owns the stack.
6. X1, then X2. X2 owns the stack.
7. V on every Critical and High finding. Batch by report; at most 3 run in parallel when no stack is needed, and proofs that need the stack run one at a time.
8. D1, then X3, then **Checkpoint 4**, the final one.

### Slicing for depth

Stage 0's scope map proposes slices: groups of Django apps, frontend routes, graph nodes. Each slice should be small enough that one agent can read every file fully, roughly ≤ 40 files or ≤ 6k lines of code.

Run one agent per slice. Name slice reports `B1a-…`, `B1b-…` and so on, and continue the finding IDs across slices (B1a-001…, B1b-001…).

If a report starts with `CONTINUE NEEDED`, start a continuation agent of the same type. Give it the report path and tell it to continue from the named unit and add to the same report.

### After each stage

1. Check the report exists, has the header with the baseline SHA, and that its ledger has no `not reviewed` without a reason. If something is missing, send the agent back with its report path and what's missing.
2. Update `STATUS.md`: status, report path, counts, Critical/High IDs, live spend.
3. Send the user one line: the stage, the counts, and what's next.

## Stage −1 — consolidate, CI, prep, baseline (you do this)

This is the only stage that changes code. It follows the rules in `CLAUDE.md`:
- tests first;
- fail-without proofs in a worktree;
- `git diff` review before every commit;
- no bulk rewrite scripts;
- `make check` plus `make e2e-affected` at the end, and the full `make e2e` before merging to main.

1. **Inventory.** Run `git fetch --all --prune`. For every local and remote branch, record:
   - commits ahead of and behind `main`;
   - the last commit date and subject;
   - whether it's already merged;
   - any open PR (`gh pr list --state all`);
   - any worktree using it.

   Write `docs/audit/<run>/S-1-branches.md`. Classify each branch as **ship** (finished, unmerged work), **already merged**, or **stale/experimental**.
2. **Checkpoint 1.** Show the user the classification and the planned merge order. Wait for an OK. Don't delete any branch, even an already-merged one; list them for the user.
3. **Merge each ship branch** in dependency order:
   - Update it from `main` and resolve conflicts. If a conflict involves logic that both sides changed, ask the user.
   - Run `make check` and the full `make e2e` locally.
   - Push the branch, open a PR with `gh pr create`, and watch CI with `gh pr checks --watch`.
   - Fix each CI failure at its root cause, on the branch. Never skip, `xfail` or delete a test, never lower a threshold, never disable a check.
   - Merge the PR once CI is green, using the repo's usual merge style.
4. **Make `main`'s CI green.** If `main` itself fails, fix it the same way, through a PR.
5. **Audit prep PR** (branch `audit/prep`). Check what already exists and add only what's missing, with tests:
   - **Scripted fake LLM.** It returns deterministic, schema-valid outputs for every graph node, and it can be told to fail on demand: invalid JSON, output the validator rejects, timeout, 429, 401. That exercises the fallback layers and refund paths.
     - It must be impossible in production: add a system check that refuses the fake LLM when `DEBUG` is false, like `payments.E004`.
   - **`make audit-up MODE=mock|live` and `make audit-down`.**
     - `mock` uses the fake LLM, FakeGateway, the console mailer and the fake sign-in provider.
     - `live` uses the real LLM keys present, with FakeGateway or the payment test mode, and `LIVE_MAX_COST_USD`.
     - Both respect the memory limits.
   - **`manage.py audit_seed`.** It is idempotent and creates synthetic personas only, with emails `audit-<persona>@example.test` (a hyphen, not `+<persona>`: the app drops a `+tag` when it decides whether two addresses are one inbox, so tagged personas would all be one account). The personas:
     - a new learner with the signup grant;
     - a learner with zero credits;
     - holders of the Weekly, Monthly and Pro Plus plans;
     - a learner with a streak and a repair available;
     - a learner with lesson, quiz, retest and sheet history;
     - a learner whose language is Hindi;
     - a learner linked to Google (fake provider);
     - a staff user.

     It prints the persona names, never the passwords. Put the passwords in a git-ignored `docs/audit/<run>/personas.local` (add it to `.gitignore`).
   - Commit this kit (`.claude/agents/audit-*`, `.claude/commands/audit.md`, `docs/audit/*.md`) in the same PR if it isn't on `main` yet.
6. **Baseline.** When `main` is green, tag it `audit-baseline-<run>`, push the tag, and record the SHA in `STATUS.md`. From here on the code is frozen for the audit. All later stages audit this tag.

## Checkpoints (stop and wait for the user)

- **Checkpoint 1:** the branch classification and merge order.
- **Checkpoint 2:** the product brief and scope map. Show the user:
  - the slice plan and the number of agent runs it means;
  - the business rules digest (the user corrects anything wrong — this digest is the oracle for B2, L1 and X2);
  - L1's planned live-call matrix and its estimated tokens.
- **Checkpoint 3:** before L1 goes live. Tell the user which keys are present (by name only), which billing tiers apply, and what the run is expected to cost against `LIVE_MAX_COST_USD`.
- **Checkpoint 4:** the final verdict, the top risks, and the fix plan.

Between checkpoints, don't stop to ask unless a decision can't be undone.

## Resuming in a new session

The user types `/audit resume`. Read `docs/audit/<latest run>/STATUS.md` and continue from the first stage that isn't `done`. A stage marked `running` with no report, or with a report starting `CONTINUE NEEDED`, is restarted or continued.

## The audit's outputs

`docs/audit/<run>/`:
- `S-1-branches.md`
- `00-product-brief.md` and `00-scope-map.md`
- one report per stage or slice
- `V-verification.md`
- `D1-deployment.md`
- `FINAL-REPORT.md` and `FIX-PLAN.md`
- `STATUS.md`

These are committed to `main` through a PR (`audit/<run>-reports`) at the end. Screenshots and traces bigger than 1 MB each stay out of git; list them in `.gitignore`.
