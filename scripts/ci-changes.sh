#!/usr/bin/env bash
# Write code=false to $GITHUB_OUTPUT when every file the pull request or push changes is
# documentation, code=true otherwise or when the changed files cannot be listed.
set -euo pipefail

is_docs() {
  case "$1" in
    apps/*) return 1 ;;
    docs/* | llms.txt | .github/ISSUE_TEMPLATE/* | .github/DISCUSSION_TEMPLATE/* | *.md) return 0 ;;
    *) return 1 ;;
  esac
}

changed_files() {
  case "${GITHUB_EVENT_NAME:-}" in
    pull_request)
      git diff --name-only HEAD^1 HEAD || return 1
      ;;
    push)
      local before="${BEFORE_SHA:-}"
      if [[ -z "$before" || "$before" =~ ^0+$ ]]; then
        return 1
      fi
      git fetch --quiet --no-tags --depth=1 origin "$before" || return 1
      git diff --name-only "$before" HEAD || return 1
      ;;
    *)
      return 1
      ;;
  esac
}

code=true
if files=$(changed_files) && [[ -n "$files" ]]; then
  code=false
  while IFS= read -r file; do
    if ! is_docs "$file"; then
      echo "not documentation: $file"
      code=true
      break
    fi
  done <<<"$files"
fi

echo "code=$code"
echo "code=$code" >>"${GITHUB_OUTPUT:-/dev/null}"
