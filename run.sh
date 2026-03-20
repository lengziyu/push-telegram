#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR=""

if [[ -f "${ROOT_DIR}/.venv/bin/activate" ]]; then
  VENV_DIR="${ROOT_DIR}/.venv"
elif [[ -f "${ROOT_DIR}/../.venv/bin/activate" ]]; then
  VENV_DIR="${ROOT_DIR}/../.venv"
else
  echo "[run.sh] No virtual environment found. Creating ${ROOT_DIR}/.venv ..."
  python3 -m venv "${ROOT_DIR}/.venv"
  VENV_DIR="${ROOT_DIR}/.venv"
fi

# shellcheck disable=SC1090
source "${VENV_DIR}/bin/activate"

if ! python -c "import requests, bs4, dotenv, openai" >/dev/null 2>&1; then
  echo "[run.sh] Installing dependencies from requirements.txt ..."
  python -m pip install -r "${ROOT_DIR}/requirements.txt"
fi

exec python "${ROOT_DIR}/main.py" "$@"
