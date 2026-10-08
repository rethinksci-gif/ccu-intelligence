#!/usr/bin/env bash
# Restore only successful collection artifacts from the trusted default branch.
set -euo pipefail
mkdir -p data/runtime
run_id="$(gh run list --workflow collect.yml --branch "$DEFAULT_BRANCH" --status success --limit 1 --json databaseId --jq '.[0].databaseId // empty')"
if [ -n "$run_id" ]; then
  gh run download "$run_id" --name collection-state --dir data/runtime
else
  echo 'No prior successful collection; starting with curated records.'
fi
