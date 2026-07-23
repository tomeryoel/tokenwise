#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT

WORKFLOW_DIR="$TEMP_DIR/workflows"
STATE_FILE="$TEMP_DIR/state/momihelm-workflows.sha256"
FAKE_BIN="$TEMP_DIR/bin"
CALLS_FILE="$TEMP_DIR/n8n-calls"
mkdir -p "$WORKFLOW_DIR" "$FAKE_BIN"

printf '%s\n' '{"id":"gateway","version":1}' >"$WORKFLOW_DIR/tokenwise-skeleton.workflow.json"
printf '%s\n' '{"id":"usage","version":1}' >"$WORKFLOW_DIR/tokenwise-usage-summary.workflow.json"

cat >"$FAKE_BIN/n8n" <<'EOF'
#!/bin/sh
printf '%s\n' "$*" >>"$MOMIHELM_TEST_CALLS_FILE"
EOF

cat >"$FAKE_BIN/wget" <<'EOF'
#!/bin/sh
exit "${MOMIHELM_TEST_N8N_LIVE:-1}"
EOF

chmod +x "$FAKE_BIN/n8n" "$FAKE_BIN/wget"

run_bootstrap() {
    PATH="$FAKE_BIN:$PATH" \
        MOMIHELM_WORKFLOW_DIR="$WORKFLOW_DIR" \
        MOMIHELM_WORKFLOW_STATE_FILE="$STATE_FILE" \
        MOMIHELM_N8N_HEALTH_URL="http://n8n.test/healthz" \
        MOMIHELM_TEST_CALLS_FILE="$CALLS_FILE" \
        MOMIHELM_TEST_N8N_LIVE="$1" \
        "$SCRIPT_DIR/bootstrap.sh"
}

assert_call_count() {
    expected=$1
    actual=0
    if [ -f "$CALLS_FILE" ]; then
        actual=$(wc -l <"$CALLS_FILE" | tr -d ' ')
    fi
    if [ "$actual" -ne "$expected" ]; then
        echo "Expected $expected n8n calls, found $actual." >&2
        exit 1
    fi
}

# A first import is safe only while n8n is stopped.
run_bootstrap 1
assert_call_count 4
test -s "$STATE_FILE"

# Re-running with unchanged workflows must not touch a live n8n database.
: >"$CALLS_FILE"
run_bootstrap 0
assert_call_count 0

# A changed workflow must fail before import while n8n is live.
printf '%s\n' '{"id":"gateway","version":2}' >"$WORKFLOW_DIR/tokenwise-skeleton.workflow.json"
if run_bootstrap 0; then
    echo "Expected a changed live workflow import to be rejected." >&2
    exit 1
fi
assert_call_count 0

# The same change is imported after n8n has stopped.
run_bootstrap 1
assert_call_count 4

echo "MomiHelm workflow bootstrap regression test passed."
