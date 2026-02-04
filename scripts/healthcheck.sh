#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${BOT_TOKEN:-}" || -z "${LOCAL_API_BASE_URL:-}" ]]; then
  echo "BOT_TOKEN and LOCAL_API_BASE_URL must be set"
  exit 1
fi

curl -fsS "${LOCAL_API_BASE_URL}${BOT_TOKEN}/getMe"
