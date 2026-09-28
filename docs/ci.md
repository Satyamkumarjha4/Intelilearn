# Continuous integration

The workflow is `.github/workflows/ci.yml`, and it runs on **every push to every branch**.

## Jobs

| Job | What it runs | Same as locally |
|---|---|---|
| `lint` | `ruff check`, `ruff format --check` (uv); `eslint`, `next typegen`, `tsc --noEmit` (bun) | `make lint` |
| `test` | `docker compose run --rm backend pytest`, using the docker Postgres and Redis | `make test` |

CI has **no `.env`**. Every setting falls back to the defaults in `.env.example`, which is why every new variable must have a default (see `CLAUDE.md`).

## When checks fail

```
push ──▶ lint ─┐
               ├─▶ all green ──▶ branch: close its open ci-failure issue (if any)
        test  ─┘
               └─▶ something failed
                     ├─ main   ──▶ revert the push (new commit restoring the previous state)
                     │             └─ revert not possible ──▶ open an issue instead
                     └─ branch ──▶ open, or comment on, the branch's "ci-failure" issue
```

### main: automatic revert (`.github/scripts/revert-push.sh`)

- It adds **one new commit** that restores main to its state before the push (`github.event.before`). History is never rewritten, so the failing commits stay visible, followed by `revert: roll back abc1234..def5678 (CI failed)`, which links to the failed run.
- Restoring the earlier tree works for normal pushes, merges, and squash merges alike.
- **It refuses to revert, and opens an issue instead,** in two cases:
  - it was the first push to main, so there's nothing to go back to;
  - main has moved on since the failing push, so reverting would also undo someone else's later work.
- The revert is pushed with the workflow's `GITHUB_TOKEN`. GitHub does not start new workflow runs for such pushes, so a revert can't trigger a loop.
- To recover your change, branch from the failing commit, fix it, and merge again.

### Branches: failure issue (`.github/scripts/report-failure.sh`)

- There is one open issue per branch, titled ``CI failing on `<branch>` `` and labelled `ci-failure` (the label is created automatically). Further failing pushes add comments instead of new issues.
- The issue shows the commit, who pushed it, which jobs failed, a link to the run, a link to the compare view, and the last 60 lines of each failing log.
- The next green run on that branch closes the issue automatically (`resolve-failure.sh`).
- Preview the issue text locally with `DRY_RUN=1 BRANCH=x LOG_DIR=path .github/scripts/report-failure.sh`.

## Repository settings this relies on

- The workflow asks for exactly what it needs: `contents: write` (revert) and `issues: write` (issues) in the failure job only, and read-only everywhere else. This works with the default "read" workflow-permissions setting, as long as your organisation doesn't forbid workflows from elevating permissions.
- **Branch protection on `main`:** if pushes to main require pull requests or status checks, the bot cannot push the revert. The run then opens an issue instead. To keep auto-revert with protection enabled, allow GitHub Actions to bypass the rule, or rely on required status checks on PRs.
- **Concurrency:** on branches, a newer push cancels the older run. On main, every push is checked on its own, because each one may need reverting.
