#!/bin/sh
set -eu

WORKFLOW_DIR=/workflows

echo "Importing MomiHelm workflows..."
n8n import:workflow --input="$WORKFLOW_DIR/tokenwise-skeleton.workflow.json"
n8n import:workflow --input="$WORKFLOW_DIR/tokenwise-usage-summary.workflow.json"

echo "Publishing MomiHelm workflows..."
n8n publish:workflow --id=tokenwiseskeleton
n8n publish:workflow --id=tokenwiseusagesummary

echo "MomiHelm workflows are ready."
