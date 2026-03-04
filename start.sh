#!/bin/bash
cd "$(dirname "$0")"
source .venv/bin/activate
source .env 2>/dev/null
# Auto-install flask if missing
python -c "import flask" 2>/dev/null || pip install flask
python -c "import apscheduler" 2>/dev/null || pip install APScheduler
python web/app.py
