#!/bin/bash
# Unit tests for the nightly runner system
# Run locally: bash nightly/test_nightly.sh
# Run on server: bash email_campaign/nightly/test_nightly.sh

set -euo pipefail

PASS=0
FAIL=0
TESTS=()

test_result() {
    local name="$1" result="$2" detail="${3:-}"
    if [ "$result" = "PASS" ]; then
        echo "  [PASS] $name"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] $name${detail:+ -- $detail}"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== Nightly Runner Test Suite ==="
echo ""

# Detect if we're on the server or local
if [ -d "$HOME/email-campaign/email_campaign/nightly" ]; then
    NIGHTLY_DIR="$HOME/email-campaign/email_campaign/nightly"
    REPO_DIR="$HOME/email-campaign"
elif [ -d "nightly" ]; then
    NIGHTLY_DIR="$(pwd)/nightly"
    REPO_DIR="$(cd .. && pwd)"
elif [ -d "../nightly" ]; then
    NIGHTLY_DIR="$(cd ../nightly && pwd)"
    REPO_DIR="$(cd ../.. && pwd)"
else
    echo "ERROR: Cannot find nightly directory. Run from email_campaign/ or repo root."
    exit 1
fi

CAMPAIGN_DIR="$REPO_DIR/email_campaign"

echo "--- File Structure Tests ---"

# Test 1: All required files exist
for f in runner.sh NIGHTLY_PROMPT.md state.json campaign_audit.md deploy.sh setup_server.sh; do
    if [ -f "$NIGHTLY_DIR/$f" ]; then
        test_result "File exists: $f" "PASS"
    else
        test_result "File exists: $f" "FAIL" "missing"
    fi
done

# Test 2: runner.sh is executable
if [ -x "$NIGHTLY_DIR/runner.sh" ]; then
    test_result "runner.sh is executable" "PASS"
else
    test_result "runner.sh is executable" "FAIL"
fi

# Test 3: deploy.sh is executable
if [ -x "$NIGHTLY_DIR/deploy.sh" ]; then
    test_result "deploy.sh is executable" "PASS"
else
    test_result "deploy.sh is executable" "FAIL"
fi

echo ""
echo "--- Bash Syntax Tests ---"

# Test 4: runner.sh has valid syntax
if bash -n "$NIGHTLY_DIR/runner.sh" 2>/dev/null; then
    test_result "runner.sh syntax valid" "PASS"
else
    test_result "runner.sh syntax valid" "FAIL" "syntax error"
fi

# Test 5: deploy.sh has valid syntax
if bash -n "$NIGHTLY_DIR/deploy.sh" 2>/dev/null; then
    test_result "deploy.sh syntax valid" "PASS"
else
    test_result "deploy.sh syntax valid" "FAIL" "syntax error"
fi

# Test 6: setup_server.sh has valid syntax
if bash -n "$NIGHTLY_DIR/setup_server.sh" 2>/dev/null; then
    test_result "setup_server.sh syntax valid" "PASS"
else
    test_result "setup_server.sh syntax valid" "FAIL" "syntax error"
fi

echo ""
echo "--- State File Tests ---"

# Test 7: state.json is valid JSON
if python3 -c "import json; json.load(open('$NIGHTLY_DIR/state.json'))" 2>/dev/null; then
    test_result "state.json is valid JSON" "PASS"
else
    test_result "state.json is valid JSON" "FAIL" "parse error"
fi

# Test 8: state.json has required fields
if python3 -c "
import json, sys
state = json.load(open('$NIGHTLY_DIR/state.json'))
required = ['last_run', 'total_runs', 'tasks_completed', 'tasks_in_progress',
            'bounced_emails_fixed', 'new_contacts_added', 'campaigns_expanded',
            'emails_written', 'errors']
missing = [k for k in required if k not in state]
if missing:
    print(f'Missing: {missing}', file=sys.stderr)
    sys.exit(1)
" 2>/dev/null; then
    test_result "state.json has all required fields" "PASS"
else
    test_result "state.json has all required fields" "FAIL"
fi

# Test 9: State dedup logic works (simulated)
TEMP_STATE=$(mktemp)
cat > "$TEMP_STATE" << 'EOF'
{
  "tasks_completed": [
    {"task": "fix_bounced_emails", "date": "2026-03-06"},
    {"task": "expand_segment_1", "date": "2026-03-05"}
  ]
}
EOF

# Should find fix_bounced_emails for today
if python3 -c "
import json, sys
state = json.load(open('$TEMP_STATE'))
completed = state.get('tasks_completed', [])
today_tasks = [t for t in completed if t.get('date') == '2026-03-06' and t.get('task') == 'fix_bounced_emails']
sys.exit(0 if today_tasks else 1)
" 2>/dev/null; then
    test_result "Task dedup: finds today's completed task" "PASS"
else
    test_result "Task dedup: finds today's completed task" "FAIL"
fi

# Should NOT find expand_segment_1 for today (it was yesterday)
if python3 -c "
import json, sys
state = json.load(open('$TEMP_STATE'))
completed = state.get('tasks_completed', [])
today_tasks = [t for t in completed if t.get('date') == '2026-03-06' and t.get('task') == 'expand_segment_1']
sys.exit(0 if today_tasks else 1)
" 2>/dev/null; then
    test_result "Task dedup: skips yesterday's task correctly" "FAIL" "should not match"
else
    test_result "Task dedup: skips yesterday's task correctly" "PASS"
fi

rm -f "$TEMP_STATE"

echo ""
echo "--- Prompt File Tests ---"

# Test 11: NIGHTLY_PROMPT.md has key sections
for section in "Who Are You" "Email Formatting Rules" "Campaign File Format" "Task Definitions" "fix_bounced_emails" "expand" "Cross-Campaign Dedup" "Email Validation Checklist" "SENDER_PROFILE" "TARGET_SEGMENTS"; do
    if grep -q "$section" "$NIGHTLY_DIR/NIGHTLY_PROMPT.md" 2>/dev/null; then
        test_result "Prompt has section: $section" "PASS"
    else
        test_result "Prompt has section: $section" "FAIL" "missing"
    fi
done

# Test 12: Prompt has sender profile section
if grep -q "Sender profile" "$NIGHTLY_DIR/NIGHTLY_PROMPT.md" && grep -q 'Your Name' "$NIGHTLY_DIR/NIGHTLY_PROMPT.md"; then
    test_result "Prompt: has sender profile template" "PASS"
else
    test_result "Prompt: has sender profile template" "FAIL"
fi

# Test 13: Prompt says NEVER mention pricing in emails
if grep -q "NEVER mention pricing" "$NIGHTLY_DIR/NIGHTLY_PROMPT.md"; then
    test_result "Prompt: no-pricing rule present" "PASS"
else
    test_result "Prompt: no-pricing rule present" "FAIL"
fi

echo ""
echo "--- Campaign File Tests ---"

# Test 14: All 6 campaign master files exist
CAMPAIGNS=(
    "example_campaign/example_outreach_campaign.md"
)
for c in "${CAMPAIGNS[@]}"; do
    if [ -f "$CAMPAIGN_DIR/campaigns/$c" ]; then
        test_result "Campaign exists: $c" "PASS"
    else
        test_result "Campaign exists: $c" "FAIL" "missing"
    fi
done

# Test 15: state.json exists in nightly directory
if [ -f "$NIGHTLY_DIR/state.json" ]; then
    test_result "state.json exists in nightly/" "PASS"
else
    test_result "state.json exists in nightly/" "FAIL"
fi

echo ""
echo "--- Runner Logic Tests ---"

# Test 16: runner.sh has required segment names
for seg in fix_bounced example audit_emails; do
    if grep -q "$seg" "$NIGHTLY_DIR/runner.sh"; then
        test_result "Runner has segment: $seg" "PASS"
    else
        test_result "Runner has segment: $seg" "FAIL" "missing from SEGMENTS array"
    fi
done

# Test 17: runner.sh uses dangerously-skip-permissions
if grep -q "dangerously-skip-permissions" "$NIGHTLY_DIR/runner.sh"; then
    test_result "Runner uses --dangerously-skip-permissions" "PASS"
else
    test_result "Runner uses --dangerously-skip-permissions" "FAIL"
fi

# Test 18: runner.sh uses --max-turns and has rate limit detection
if grep -q "max-turns" "$NIGHTLY_DIR/runner.sh" && grep -q "RATE LIMITED" "$NIGHTLY_DIR/runner.sh"; then
    test_result "Runner: --max-turns + rate limit detection" "PASS"
else
    test_result "Runner: --max-turns + rate limit detection" "FAIL"
fi

# Test 19: runner.sh has git commit after tasks
if grep -q "git commit" "$NIGHTLY_DIR/runner.sh"; then
    test_result "Runner commits after tasks" "PASS"
else
    test_result "Runner commits after tasks" "FAIL"
fi

# Test 20: runner.sh has git push at end
if grep -q "git push" "$NIGHTLY_DIR/runner.sh"; then
    test_result "Runner pushes at end" "PASS"
else
    test_result "Runner pushes at end" "FAIL"
fi

echo ""
echo "--- Server Dependency Tests ---"

# Test 21-23: Check if we're on the server and tools are available
if [ "$(hostname)" != "$(hostname -s 2>/dev/null)" ] || [ -f /etc/aws_instance_id ] || grep -q "ubuntu" /etc/passwd 2>/dev/null; then
    for cmd in git python3 node; do
        if command -v $cmd &>/dev/null; then
            version=$($cmd --version 2>&1 | head -1)
            test_result "Server has $cmd: $version" "PASS"
        else
            test_result "Server has $cmd" "FAIL" "not installed"
        fi
    done

    if command -v claude &>/dev/null; then
        version=$(claude --version 2>/dev/null || echo "unknown")
        test_result "Server has claude: $version" "PASS"
    else
        test_result "Server has claude CLI" "FAIL" "not installed"
    fi
else
    echo "  [SKIP] Server dependency tests (not running on server)"
fi

echo ""
echo "--- Time Budget Simulation ---"

# Test 24: time_remaining calculation
START_TIME=$(date +%s)
MAX_RUNTIME_SECONDS=14400
sleep 1
elapsed=$(( $(date +%s) - START_TIME ))
remaining=$(( MAX_RUNTIME_SECONDS - elapsed ))
if [ "$remaining" -gt 14390 ] && [ "$remaining" -lt 14400 ]; then
    test_result "Time remaining calc: ${remaining}s (expected ~14399)" "PASS"
else
    test_result "Time remaining calc: ${remaining}s" "FAIL" "expected ~14399"
fi

echo ""
echo "==========================================="
echo "  Results: $PASS passed, $FAIL failed"
echo "==========================================="

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
