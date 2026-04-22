#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BRANCH="${1:-master}"

cd "${REPO_DIR}"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Not a git work tree: ${REPO_DIR}" >&2
  exit 1
fi

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "Tracked local changes exist; deployment aborted." >&2
  git status --short --untracked-files=no >&2
  exit 1
fi

echo "repo_dir=${REPO_DIR}"
echo "branch=${BRANCH}"
echo "remote=$(git remote get-url origin)"
echo "before_head=$(git rev-parse HEAD)"

git fetch origin "${BRANCH}"
git checkout "${BRANCH}"
git pull --ff-only origin "${BRANCH}"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

. .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt

python -m py_compile scripts/run_market_daily_job.py tests/test_run_market_daily_job.py tests/test_quotes_collector.py
python -m unittest tests.test_run_market_daily_job tests.test_quotes_collector -v

echo "after_head=$(git rev-parse HEAD)"
echo "deploy_ok=1"
