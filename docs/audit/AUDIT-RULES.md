# Socra full audit — rules every audit agent follows

Read this file completely before you start. It applies to every stage. Your own agent file adds the stage-specific scope and checklist.

The run folder is `docs/audit/<run>/` (the orchestrator gives you `<run>`, e.g. `2026-11-22`). The product brief `docs/audit/<run>/00-product-brief.md` and scope map `docs/audit/<run>/00-scope-map.md` are your starting context — read both before touching code (Stage 0 excepted, it writes them).

## 1. You audit; you do not fix

- Do not change application code, tests, migrations, settings, Docker files, CI, or docs outside `docs/audit/<run>/`.
- Allowed:
  - reading anything in the repo except secret values;
  - running read-only commands: grep, linters, type checkers, the test suite, coverage, `makemigrations --check --dry-run`, `manage.py check --deploy`, `pip-audit`, `npm audit`, `next build` into a temp dir;
  - writing your report and scratch files inside `docs/audit/<run>/<stage-id>/`.
- If you need a tool that isn't installed, run it without adding it to the project: `uvx`, `pipx run`, `npx --yes`, or a venv/node_modules under `/tmp`. Never add packages to `requirements*`, `pyproject.toml` or `package.json`.
- Proof code goes in a throwaway git worktree from the baseline tag. This means a failing test that demonstrates a bug, or an exploit script run against the local stack.
  - Create it with `git worktree add ../socra-proof-<finding-id> audit-baseline-<run>`.
  - Copy `.env` into the worktree if the proof needs it, and remove the worktree afterwards.
  - Paste the essential lines into the finding.
- Never send a proof or a probe to any system that isn't on this machine.
- Audit only the baseline commit (tag `audit-baseline-<run>`). Put its SHA at the top of your report. If you notice the working tree differs from the tag, stop and tell the orchestrator.

## 2. Secrets, data and money

- Never print, log, quote or copy a secret value. That covers keys, tokens, passwords, webhook secrets, cookies and session ids.
  - Check that a setting is present by its name only (for example `grep -c '^GROQ_API_KEY=' .env`).
  - Never `cat` `.env` or `.env.*`.
- Never use real learner data. Use only the synthetic personas created by `manage.py audit_seed`, and synthetic topics and answers.
- **Live LLM calls take synthetic inputs only.** The Gemini free tier uses submitted content for training and allows human review.
- Payments: use FakeGateway, or the Razorpay/Stripe test mode with test keys. Never set `PAYMENTS_LIVE_MODE`.
- Contact email in any suggestion: `satyamjha4@gmail.com`. Never suggest invented testimonials, ratings or user counts.

## 3. Modes and the machine

- **mock (the default):**
  - a scripted fake LLM (deterministic, schema-valid, with failure injection);
  - FakeGateway, the console mailer and the fake sign-in provider;
  - seeded personas.
  - Start with `make audit-up MODE=mock` and stop with `make audit-down`.
- **live:** only where your agent file says so.
  - Real LLMs on the keys present, synthetic inputs, budget `LIVE_MAX_COST_USD`.
  - Write the tokens used and the spend into your report. `make audit-spend` prints the spend against `LIVE_MAX_COST_USD` and fails when over; run it before each batch of live calls.
- The machine is low on memory and swap:
  - Only the stage that the orchestrator says owns the stack may start Docker or a browser.
  - Use `PYTEST_WORKERS=4` and `E2E_WORKERS=2`.
  - Stop everything you started before you finish.

## 4. Depth: no sampling, and a coverage ledger

- Read every file in your scope completely. Don't sample, and don't stop at the first few findings. Skimming defeats the purpose of this audit.
- Your report ends with a **coverage ledger**. It lists every unit in your scope (file, endpoint, page, graph node, Celery task, business rule), each marked `reviewed`, `partial — <why>` or `not reviewed — <why>`.
- If your scope won't fit in your context:
  - stop at a clean boundary;
  - write the ledger with what's left;
  - put `CONTINUE NEEDED from <unit>` as the first line of the report. The orchestrator will start a continuation agent.
- "I could not verify X" is a valid result. A guess is not.

## 5. Finding format

```
### B3-007 — <one-line title>
- Severity: Critical | High | Medium | Low | Info
- Confidence: Confirmed (reproduced or proven) | Likely (clear from code) | Suspected (needs a check)
- Category: security | correctness | spec-mismatch | design | code-quality | performance | ux | a11y | deploy | llm-quality | test-gap | dead-code | privacy
- Where: path/to/file.py:120-148 (`function_name`) | page /learn/[id] at 360px | POST /api/credits/hold
- Evidence: a minimal code excerpt (≤15 lines), or exact repro steps / command plus the relevant output, or a screenshot path
- Impact: what goes wrong, for whom, how likely
- Recommended fix: concrete — which file and function, the approach, and the tests to add (including the fail-without proof)
- Fix size: S (<1 h) | M (≈half a day) | L (>1 day)
- Related: other finding IDs; spec section (e.g. credits-system.md §S4); decision doc
```

IDs are `<stage-id>-<3 digits>`, for example `B1-001`. A continuation agent continues the numbering.

### Severity guide

- **Critical:** blocks launch. Any of these:
  - credits or money can be created, lost or stolen;
  - account takeover;
  - one user can read or change another user's data;
  - data loss;
  - a secret is exposed;
  - a privacy or legal breach, such as real learner data going to a training tier;
  - the app can't start in production.
- **High:** blocks launch. Any of these:
  - a core learner journey is broken or wrong for many users;
  - an exploit needs only moderate effort;
  - a spec rule is broken in a way users will notice (wrong marks, wrong charge, wrong refund);
  - deployment would fail or be unsafe.
- **Medium:** fix before launch or soon after. A real bug with a workaround or limited reach, a maintainability problem that will soon cause bugs, or missing hardening.
- **Low:** polish, a small inconsistency, or a small refactor.
- **Info:** an observation with no action needed now.

### Rules

- One problem per finding. If one root cause shows up in many places, write one finding and list every place.
- Don't list each linter or style nit separately. Write one summarising finding with counts and the command to reproduce.
- If a spec, the Decisions section, or `docs/process/roadmap.md` says the behaviour is intended or already planned:
  - don't report it as a bug; cite the source;
  - if you think the decision is wrong, report it as `Info — decision to revisit` with your reasoning;
  - if a planned item is a launch blocker, say so.
- Severity describes real-world impact, not how interesting the bug is.

## 6. Report layout

Write `docs/audit/<run>/<stage-id>-<short-name>.md` with these sections:

1. **Header:** stage, agent name, model and effort, baseline SHA, date, mode, live tokens and spend (if any).
2. **Summary:** 5–10 lines, plus a count of findings by severity.
3. **Findings,** sorted Critical → Info.
4. **What's good:** short. These are things a fix must not break.
5. **Coverage ledger.**
6. **Commands run:** the commands, with no secret output.

Screenshots, traces, scratch scripts and raw outputs go in `docs/audit/<run>/<stage-id>/`.

When you finish, reply to the orchestrator with only:
- the report path;
- the counts by severity;
- the IDs of Critical and High findings;
- whether a continuation is needed.

Don't paste the report back.
