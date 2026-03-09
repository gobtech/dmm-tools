#!/bin/bash
cd "$(dirname "$0")"
source .venv/bin/activate
source .env 2>/dev/null
# Auto-install flask if missing
python -c "import flask" 2>/dev/null || pip install flask
python -c "import apscheduler" 2>/dev/null || pip install APScheduler
python -c "import google.auth" 2>/dev/null || pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client
# Start SearXNG (metasearch engine for Press Pickup)
if command -v docker &> /dev/null; then
  bash press-pickup/setup_searxng.sh start 2>/dev/null || echo "SearXNG unavailable — Press Pickup will skip web search source"
fi
python web/app.py
