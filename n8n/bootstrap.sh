#!/bin/sh
set -eu

WORKFLOW_DIR=${MOMIHELM_WORKFLOW_DIR:-/workflows}
STATE_FILE=${MOMIHELM_WORKFLOW_STATE_FILE:-/home/node/.n8n/momihelm-workflows.sha256}
N8N_HEALTH_URL=${MOMIHELM_N8N_HEALTH_URL:-http://n8n:5678/healthz}
GATEWAY_WORKFLOW="$WORKFLOW_DIR/tokenwise-skeleton.workflow.json"
USAGE_WORKFLOW="$WORKFLOW_DIR/tokenwise-usage-summary.workflow.json"

CURRENT_DIGEST=$(
    sha256sum "$GATEWAY_WORKFLOW" "$USAGE_WORKFLOW" |
        sha256sum |
        awk '{print $1}'
)
SAVED_DIGEST=$(sed -n '1p' "$STATE_FILE" 2>/dev/null || true)

if [ "$CURRENT_DIGEST" = "$SAVED_DIGEST" ]; then
    echo "MomiHelm workflows are unchanged; skipping import."
    exit 0
fi

if wget -q -O /dev/null -T 2 "$N8N_HEALTH_URL" 2>/dev/null; then
    echo "Refusing to update workflows while n8n is running." >&2
    echo "Use ./momihelm start so n8n is stopped before its database is updated." >&2
    exit 1
fi

echo "Importing changed MomiHelm workflows..."
n8n import:workflow --input="$GATEWAY_WORKFLOW"
n8n import:workflow --input="$USAGE_WORKFLOW"

echo "Publishing MomiHelm workflows..."
n8n publish:workflow --id=tokenwiseskeleton
n8n publish:workflow --id=tokenwiseusagesummary

mkdir -p "$(dirname "$STATE_FILE")"
STATE_TMP="${STATE_FILE}.tmp.$$"
trap 'rm -f "$STATE_TMP"' EXIT
printf '%s\n' "$CURRENT_DIGEST" >"$STATE_TMP"
mv "$STATE_TMP" "$STATE_FILE"

echo "MomiHelm workflows are ready."
