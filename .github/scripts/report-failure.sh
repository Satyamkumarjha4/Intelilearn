#!/usr/bin/env bash
# Open (or comment on) one "ci-failure" issue per branch with what failed and the log tails.
#
# Env: BRANCH, AFTER, ACTOR, COMMIT_MESSAGE, COMPARE_URL, RUN_URL, LINT_RESULT, TEST_RESULT,
#      REVERT_OUTCOME (main only), LOG_DIR. GH_TOKEN/GH_REPO for the gh CLI.
# DRY_RUN=1 prints the title and body instead of calling GitHub.
set -euo pipefail

LABEL="ci-failure"
TAIL_LINES=60
title="CI failing on \`${BRANCH}\`"
body="$(mktemp)"

log_section() {
  local name="$1" file="$2"
  [[ -s "$file" ]] || return 0
  printf '\n<details><summary>%s: last %s lines</summary>\n\n```text\n' "$name" "$TAIL_LINES"
  # strip ANSI colour codes; keep the body well under GitHub's size limit
  tail -n "$TAIL_LINES" "$file" | sed -E 's/\x1B\[[0-9;]*[A-Za-z]//g' | cut -c1-300
  printf '```\n</details>\n'
}

subject="$(head -n1 <<<"${COMMIT_MESSAGE:-}")"
subject="${subject//|/\\|}" # keep the markdown table intact

{
  echo "### CI failed on \`${BRANCH}\`"
  echo
  echo "| | |"
  echo "|---|---|"
  echo "| Commit | \`${AFTER:0:7}\`: ${subject} |"
  echo "| Pushed by | @${ACTOR:-unknown} |"
  echo "| Lint | ${LINT_RESULT:-unknown} |"
  echo "| Tests | ${TEST_RESULT:-unknown} |"
  echo "| Run | ${RUN_URL:-unknown} |"
  [[ -n "${COMPARE_URL:-}" ]] && echo "| Changes | ${COMPARE_URL} |"
  if [[ "$BRANCH" == "main" ]]; then
    echo
    echo "> [!WARNING]"
    echo "> The automatic revert of main did not happen (outcome: \`${REVERT_OUTCOME:-skipped}\`), so main is still failing."
    echo "> Either this was the first push to main, or main moved on since the push. Fix or revert by hand."
  fi
  log_section "Lint" "${LOG_DIR:-.}/lint.log"
  log_section "Tests" "${LOG_DIR:-.}/test.log"
  echo
  echo "Reproduce locally with \`make check\`. This issue closes automatically when \`${BRANCH}\` passes CI."
} >"$body"

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  echo "TITLE: $title"
  cat "$body"
  exit 0
fi

gh label create "$LABEL" --color B60205 --description "Opened automatically when CI fails" --force >/dev/null

existing="$(gh issue list --label "$LABEL" --state open --limit 100 --json number,title \
  --jq ".[] | select(.title == \"${title//\"/\\\"}\") | .number" | head -n1)"

if [[ -n "$existing" ]]; then
  gh issue comment "$existing" --body-file "$body"
  echo "Updated issue #$existing"
else
  gh issue create --title "$title" --label "$LABEL" --body-file "$body"
fi
