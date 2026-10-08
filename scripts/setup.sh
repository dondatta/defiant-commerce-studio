#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/python -m pip install --cache-dir /workspace/.pip-cache -r requirements.lock
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py seed_studio
.venv/bin/python manage.py check
