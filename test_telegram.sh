#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "[test_telegram] Missing .env file at ${ENV_FILE}"
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" || -z "${TELEGRAM_CHAT_ID:-}" ]]; then
  echo "[test_telegram] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing in .env"
  exit 1
fi

MESSAGE="${1:-telegram test ok}"
API_URL="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage"

echo "[test_telegram] Sending test message to chat_id=${TELEGRAM_CHAT_ID} ..."
curl -sS "${API_URL}" \
  -H "Content-Type: application/json" \
  -d "{\"chat_id\":\"${TELEGRAM_CHAT_ID}\",\"text\":\"${MESSAGE}\"}"

echo
echo "[test_telegram] Done."
