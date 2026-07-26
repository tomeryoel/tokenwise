# Local MomiHelm Cursor SDK Bridge
#
# This bridge must run on the developer machine (not inside Docker).
# It uses the official Python cursor-sdk package.
#
# Setup:
#   python3 -m venv bridges/cursor-sdk/.venv
#   bridges/cursor-sdk/.venv/bin/pip install -r bridges/cursor-sdk/requirements.txt
#   export CURSOR_API_KEY=...
#   export MOMIHELM_CURSOR_BRIDGE_TOKEN=...
#   ./momihelm cursor-bridge
#
# Endpoints (127.0.0.1 only by default):
#   GET  /health
#   GET  /models
#   POST /run
#
# Auth header:
#   X-MomiHelm-Bridge-Token: <MOMIHELM_CURSOR_BRIDGE_TOKEN>
