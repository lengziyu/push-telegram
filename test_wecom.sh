#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "[test_wecom] Missing .env file at ${ENV_FILE}"
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

if [[ -z "${WECOM_WEBHOOK_URL:-}" ]]; then
  echo "[test_wecom] WECOM_WEBHOOK_URL is missing in .env"
  exit 1
fi

MESSAGE="${1:-wecom test ok}"
PAYLOAD="{\"msgtype\":\"markdown\",\"markdown\":{\"content\":\"${MESSAGE}\"}}"

echo "[test_wecom] Sending test message ..."
curl -sS "${WECOM_WEBHOOK_URL}" \
  -H "Content-Type: application/json" \
  -d "${PAYLOAD}"

echo
echo "[test_wecom] Done."
