#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "[test_feishu] Missing .env file at ${ENV_FILE}"
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

if [[ -z "${FEISHU_WEBHOOK_URL:-}" ]]; then
  echo "[test_feishu] FEISHU_WEBHOOK_URL is missing in .env"
  exit 1
fi

MESSAGE="${1:-feishu test ok}"
TIMESTAMP="$(date +%s)"

if [[ -n "${FEISHU_SIGN_SECRET:-}" ]]; then
  PAYLOAD="$(MESSAGE="${MESSAGE}" TIMESTAMP="${TIMESTAMP}" FEISHU_SIGN_SECRET="${FEISHU_SIGN_SECRET}" python3 - <<'PY'
import base64
import hashlib
import hmac
import json
import os

ts = os.environ["TIMESTAMP"]
secret = os.environ["FEISHU_SIGN_SECRET"]
message = os.environ["MESSAGE"]
string_to_sign = f"{ts}\n{secret}"
sign = base64.b64encode(
    hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
).decode("utf-8")
print(json.dumps({
    "timestamp": ts,
    "sign": sign,
    "msg_type": "text",
    "content": {"text": message},
}, ensure_ascii=False))
PY
)"
else
  PAYLOAD="$(MESSAGE="${MESSAGE}" python3 - <<'PY'
import json
import os
print(json.dumps({
    "msg_type": "text",
    "content": {"text": os.environ["MESSAGE"]},
}, ensure_ascii=False))
PY
)"
fi

echo "[test_feishu] Sending test message ..."
curl -sS "${FEISHU_WEBHOOK_URL}" \
  -H "Content-Type: application/json" \
  -d "${PAYLOAD}"

echo
echo "[test_feishu] Done."
