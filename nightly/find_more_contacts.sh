#!/bin/bash
# ===========================================================================
# find_more_contacts.sh — Profile-driven contact expansion
#
# Usage:
#   ./find_more_contacts.sh                         # Run all segments
#   ./find_more_contacts.sh segment_name            # One segment only
#   ./find_more_contacts.sh segment_name 20         # Specific target count
#   ./find_more_contacts.sh --list                  # List available segments
#
# Reads nightly/profile.json (exported by the web app) to determine
# which segments to expand and how to build prompts.
# ===========================================================================

set -euo pipefail

REPO_DIR="$HOME/email-campaign"
CAMPAIGN_DIR="$REPO_DIR"
NIGHTLY_DIR="$CAMPAIGN_DIR/nightly"
STATE_FILE="$NIGHTLY_DIR/state.json"
LOG_DIR="$NIGHTLY_DIR/logs"
PROFILE_FILE="$NIGHTLY_DIR/profile.json"
BUILD_PROMPT="$NIGHTLY_DIR/build_prompt.py"

SEGMENT="${1:-all}"
TARGET="${2:-10}"
BATCH_SIZE=5
MAX_TURNS=50
RUN_ID=$(date +%Y%m%d_%H%M%S)
today=$(date +%Y-%m-%d)

mkdir -p "$LOG_DIR"
RUN_LOG="$LOG_DIR/find_contacts_${RUN_ID}.log"

# Load API keys (exported by web app)
[ -f "$NIGHTLY_DIR/.env" ] && source "$NIGHTLY_DIR/.env"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$RUN_LOG"; }

# Pre-flight checks
if [ ! -f "$PROFILE_FILE" ]; then
    echo "ERROR: profile.json not found at $PROFILE_FILE"
    echo "Complete the profile setup in the web app first (Settings > Profile)."
    exit 1
fi

if [ ! -f "$BUILD_PROMPT" ]; then
    echo "ERROR: build_prompt.py not found at $BUILD_PROMPT"
    exit 1
fi

cd "$REPO_DIR"
git pull origin main --ff-only 2>&1 | tee -a "$RUN_LOG" || log "WARN: git pull failed"

# List segments mode
if [ "$SEGMENT" = "--list" ]; then
    echo "Available segments (from profile.json):"
    python3 "$BUILD_PROMPT" --list-segments
    exit 0
fi

# ===========================================================================
# RUNNER LOGIC
# ===========================================================================

run_segment() {
    local segment="$1"
    local target="$2"
    local found=0
    local batch=0

    log "=== Starting $segment expansion (target: $target contacts) ==="

    while [ "$found" -lt "$target" ]; do
        batch=$((batch + 1))
        remaining=$((target - found))
        this_batch=$BATCH_SIZE
        [ "$remaining" -lt "$this_batch" ] && this_batch=$remaining

        log "  Batch $batch: finding $this_batch contacts ($found/$target done)"

        # Build the prompt dynamically from profile
        local prompt
        prompt=$(python3 "$BUILD_PROMPT" \
            --segment "$segment" \
            --batch "$batch" \
            --date "$today" \
            --batch-size "$this_batch")

        local task_log="$LOG_DIR/find_${segment}_${RUN_ID}_batch${batch}.log"

        claude --dangerously-skip-permissions \
            -p "$prompt" \
            --model claude-sonnet-4-20250514 \
            --max-turns "$MAX_TURNS" \
            --output-format text \
            2>&1 | tee "$task_log" || true

        found=$((found + this_batch))
        log "  Batch $batch complete. Approximate total: $found"

        # Git commit
        cd "$REPO_DIR"
        if [ -n "$(git status --porcelain campaigns/ nightly/ 2>/dev/null)" ]; then
            git add -A campaigns/ nightly/
            git commit -m "find_contacts: ${segment} expand batch ${batch} ($today)

Co-Authored-By: Claude Sonnet 4 <noreply@anthropic.com>" 2>&1 >> "$RUN_LOG" || log "WARN: git commit failed"
        fi
    done

    log "=== $segment expansion complete ($found contacts targeted) ==="
}

# --- Main ---
if [ "$SEGMENT" = "all" ]; then
    # Run all segments from profile.json
    log "Running all segments from profile.json"
    while IFS= read -r seg_slug; do
        [ -z "$seg_slug" ] && continue
        run_segment "$seg_slug" "$TARGET"
    done < <(python3 -c "
import json
profile = json.load(open('$PROFILE_FILE'))
for seg in sorted(profile.get('target_segments', []), key=lambda s: s.get('priority', 99)):
    slug = seg['name'].lower().replace(' ', '_').replace('/', '_')
    print(slug)
")
else
    run_segment "$SEGMENT" "$TARGET"
fi

# Push
cd "$REPO_DIR"
if [ -n "$(git log origin/main..HEAD --oneline 2>/dev/null)" ]; then
    log "Pushing to remote..."
    git push origin main 2>&1 | tee -a "$RUN_LOG" || log "WARN: push failed"
fi

log "=== Done ==="
