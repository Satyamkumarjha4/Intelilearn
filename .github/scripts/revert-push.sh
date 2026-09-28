#!/usr/bin/env bash
# Roll main back to the state before a failing push, as one new commit (history is never rewritten).
#
# Env: BEFORE (sha before the push), AFTER (pushed sha), RUN_URL, and optionally REMOTE (default origin).
# Exits non-zero, without changing anything, when an automatic revert would be unsafe:
#   - first push to the branch (nothing to go back to)
#   - main has moved past AFTER since this push (reverting would also undo later work)
# Restoring BEFORE's tree, rather than `git revert` per commit, handles merge and squash commits alike.
set -euo pipefail

REMOTE="${REMOTE:-origin}"

if [[ -z "${BEFORE:-}" || "$BEFORE" =~ ^0+$ ]]; then
  echo "No previous commit on main to return to; not reverting." >&2
  exit 1
fi

git fetch --quiet "$REMOTE" main
current="$(git rev-parse "$REMOTE/main")"
if [[ "$current" != "$AFTER" ]]; then
  echo "main is now at ${current:0:7}, past the failing push ${AFTER:0:7}; not reverting automatically." >&2
  exit 1
fi

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

git checkout --quiet -B main "$AFTER"
git read-tree -u --reset "$BEFORE"
git commit --quiet \
  -m "revert: roll back ${BEFORE:0:7}..${AFTER:0:7} (CI failed)" \
  -m "Restores main to ${BEFORE} because CI failed for ${AFTER}.
Failed run: ${RUN_URL:-unknown}
Reapply the change on a branch, fix it there, and merge again."

git push --quiet "$REMOTE" main
echo "Reverted main to ${BEFORE:0:7} with $(git rev-parse --short HEAD)."
