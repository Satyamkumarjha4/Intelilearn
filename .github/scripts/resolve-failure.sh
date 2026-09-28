#!/usr/bin/env bash
# Close the branch's open "ci-failure" issue once CI passes again.
# Env: BRANCH, AFTER, RUN_URL. GH_TOKEN/GH_REPO for the gh CLI.
set -euo pipefail

title="CI failing on \`${BRANCH}\`"
existing="$(gh issue list --label ci-failure --state open --limit 100 --json number,title \
  --jq ".[] | select(.title == \"${title//\"/\\\"}\") | .number" | head -n1 || true)"

if [[ -z "$existing" ]]; then
  echo "No open CI failure issue for ${BRANCH}."
  exit 0
fi

gh issue close "$existing" --comment "CI passes again on \`${BRANCH}\` at \`${AFTER:0:7}\` (${RUN_URL}). Closing."
echo "Closed issue #$existing"
