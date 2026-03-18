#!/bin/bash
# Nightly Claude Code runner for email campaign automation
#
# Design: Sequential, incremental, save-often.
# Each Claude session does ONE small chunk (3-5 contacts or fixes).
# After each session: save to disk, git commit, check progress.
# Move to next segment only when current one hits its target.
# If Claude exits or crashes, work from that session is already saved.

set -euo pipefail

# --- Config ---
REPO_DIR="$HOME/email-campaign"
CAMPAIGN_DIR="$REPO_DIR"
NIGHTLY_DIR="$CAMPAIGN_DIR/nightly"
STATE_FILE="$NIGHTLY_DIR/state.json"
LOG_DIR="$NIGHTLY_DIR/logs"
PROMPT_FILE="$NIGHTLY_DIR/NIGHTLY_PROMPT.md"
MAX_RUNTIME_SECONDS=14400  # 4 hours total window
MAX_TURNS=40               # turns per Claude session
MIN_NEW_PER_SEGMENT=10     # new contacts needed before moving on
BATCH_SIZE=5               # contacts to find per session

# Load env (API keys from web app + shell profile)
source "$HOME/.bashrc" 2>/dev/null || true
[ -f "$NIGHTLY_DIR/.env" ] && source "$NIGHTLY_DIR/.env"
export PATH="$PATH:/usr/local/bin:/usr/bin"

# --- Setup ---
mkdir -p "$LOG_DIR"
RUN_ID=$(date +%Y%m%d_%H%M%S)
RUN_LOG="$LOG_DIR/run_${RUN_ID}.log"
START_TIME=$(date +%s)
today=$(date +%Y-%m-%d)

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$RUN_LOG"
}

time_remaining() {
    echo $(( MAX_RUNTIME_SECONDS - ($(date +%s) - START_TIME) ))
}

# --- Pre-flight checks ---
log "=== Nightly run starting (ID: $RUN_ID) ==="

if ! command -v claude &>/dev/null; then
    log "ERROR: claude CLI not found. Run setup_server.sh first."
    exit 1
fi

cd "$REPO_DIR"
git pull origin main --ff-only 2>&1 | tee -a "$RUN_LOG" || log "WARN: git pull failed, continuing with local"

# --- Initialize state file if missing ---
if [ ! -f "$STATE_FILE" ]; then
    cat > "$STATE_FILE" << 'EOF'
{
  "last_run": null,
  "total_runs": 0,
  "segments_done_today": [],
  "sessions_run": 0,
  "bounced_emails_fixed": [],
  "new_contacts_added": [],
  "emails_written": 0,
  "errors": []
}
EOF
    log "Initialized fresh state file"
fi

# --- Segment definitions ---
# Fixed segments (always run) + dynamic segments from profile.json
SEGMENTS=(
    "fix_bounced:nightly:null_emails.md:5"
)

# Load dynamic segments from profile.json if it exists
PROFILE_FILE="$NIGHTLY_DIR/profile.json"
if [ -f "$PROFILE_FILE" ]; then
    while IFS= read -r seg_line; do
        [ -n "$seg_line" ] && SEGMENTS+=("$seg_line")
    done < <(python3 -c "
import json
profile = json.load(open('$PROFILE_FILE'))
for seg in sorted(profile.get('target_segments', []), key=lambda s: s.get('priority', 99)):
    slug = seg['name'].lower().replace(' ', '_').replace('/', '_')
    folder = 'campaigns/' + slug
    master = slug + '_outreach_campaign.md'
    target = seg.get('target_contacts', 10)
    print(f'{slug}:{folder}:{master}:{target}')
" 2>/dev/null || true)
    log "Loaded segments from profile.json"
else
    log "WARN: No profile.json found. Only running fix_bounced and audit. Set up your profile in the web app."
fi

# Always end with audit
SEGMENTS+=("audit_emails:nightly:audit_pass.md:1")

# --- Build a validation prompt ---
build_validate_prompt() {
    local segment_name="$1"
    local folder="$2"
    local master_file="$3"

    echo "You are a nightly automated agent for email campaigns.
You were launched with: claude --dangerously-skip-permissions

DATE: $today | RUN: $RUN_ID | TASK: VALIDATE emails for '$segment_name'

Read $PROMPT_FILE for the Email Validation Checklist and rules.

YOUR ONLY JOB: Validate and fix every email in the '$segment_name' campaign.

Use a SUBAGENT to do the actual validation work:

  SUBAGENT: 'Validate $segment_name emails'
    - Read $CAMPAIGN_DIR/$folder/$master_file
    - Read any nightly_additions_*.md files in $CAMPAIGN_DIR/$folder/
    - For EVERY email, check and fix:
      1. Sender identity matches NIGHTLY_PROMPT.md profile. Fix if wrong.
      2. NO dollar amounts, pricing, cost comparisons, 'low-cost', 'affordable'. REMOVE if found.
      3. NO sign-off footers. REMOVE if found (email signature handles this).
      4. NO em dashes, double dashes, hyphens as dashes. Replace with commas/periods.
      5. Tone is discovery/research, not sales pitch.
      6. Initial email is 2-3 sentences max. Follow-ups shorter.
      7. Subject under 60 chars, no ALL CAPS, no exclamation marks.
    - Fix problems DIRECTLY in the files. Save after each file.
    - Write a summary of fixes to $NIGHTLY_DIR/logs/validation_${segment_name}_${today}.md

After the subagent returns, read its summary and update state.json validation_fixes array.
If everything is clean, note 'All emails validated, no issues found.'"
}

# --- Count how many new contacts were added today for a segment ---
count_segment_progress() {
    local segment_name="$1"
    python3 -c "
import json
state = json.load(open('$STATE_FILE'))
count = sum(1 for c in state.get('new_contacts_added', [])
            if c.get('segment') == '$segment_name' and c.get('date') == '$today')
# Also count bounced fixes for fix_bounced segment
if '$segment_name' == 'fix_bounced':
    count = len([f for f in state.get('bounced_emails_fixed', [])
                 if isinstance(f, dict) and f.get('date') == '$today'])
    if count == 0:
        # backwards compat: count string entries too
        count = len(state.get('bounced_emails_fixed', []))
print(count)
" 2>/dev/null || echo "0"
}

# --- Check if segment is done for today ---
is_segment_done() {
    local segment_name="$1"
    python3 -c "
import json, sys
state = json.load(open('$STATE_FILE'))
done = state.get('segments_done_today', [])
sys.exit(0 if '$segment_name' in done else 1)
" 2>/dev/null
}

# --- Run one Claude session ---
run_session() {
    local segment_name="$1"
    local prompt="$2"
    local session_num="$3"
    local remaining
    remaining=$(time_remaining)

    TASK_LOG="$LOG_DIR/task_${RUN_ID}_${segment_name}_${session_num}.log"
    TASK_START=$(date +%s)

    log "  Session $session_num for '$segment_name' starting (${remaining}s left in window)"

    claude --dangerously-skip-permissions \
        -p "$prompt" \
        --model claude-sonnet-4-20250514 \
        --max-turns "$MAX_TURNS" \
        --output-format text \
        2>&1 | tee "$TASK_LOG" || true

    TASK_ELAPSED=$(( $(date +%s) - TASK_START ))

    # Detect rate limit
    if [ "$TASK_ELAPSED" -lt 15 ]; then
        if grep -qi "out of.*usage\|rate.limit\|quota\|resets\|capacity" "$TASK_LOG" 2>/dev/null; then
            log "  RATE LIMITED. Stopping entire run."
            python3 -c "
import json
from datetime import datetime, timezone
state = json.load(open('$STATE_FILE'))
state['errors'].append('$today: Rate limited during $segment_name session $session_num')
state['last_run'] = datetime.now(timezone.utc).isoformat()
json.dump(state, open('$STATE_FILE', 'w'), indent=2)
"
            return 1  # signal to stop
        fi
        log "  WARN: Session finished in ${TASK_ELAPSED}s (very fast). Check $TASK_LOG"
    fi

    log "  Session $session_num done (${TASK_ELAPSED}s)"

    # Git commit after each session
    cd "$REPO_DIR"
    if [ -n "$(git status --porcelain campaigns/ nightly/ exports/ 2>/dev/null)" ]; then
        git add -A campaigns/ nightly/ exports/
        git commit -m "nightly: ${segment_name} batch ${session_num} ($today)

Co-Authored-By: Claude Sonnet 4 <noreply@anthropic.com>" 2>&1 >> "$RUN_LOG" || log "  WARN: git commit failed"
    fi

    # Update session count
    python3 -c "
import json
from datetime import datetime, timezone
state = json.load(open('$STATE_FILE'))
state['sessions_run'] = state.get('sessions_run', 0) + 1
state['last_run'] = datetime.now(timezone.utc).isoformat()
json.dump(state, open('$STATE_FILE', 'w'), indent=2)
"

    return 0
}

# --- Build the prompt for a segment session ---
build_prompt() {
    local segment_name="$1"
    local folder="$2"
    local master_file="$3"
    local progress="$4"
    local target="$5"

    local base="You are a nightly automated agent for email campaigns.
You were launched with: claude --dangerously-skip-permissions

DATE: $today | RUN: $RUN_ID | SEGMENT: $segment_name
PROGRESS: $progress / $target contacts done for this segment today.

Read $PROMPT_FILE for full context about the company, email format, and rules.
Read $STATE_FILE to see what's already been done.

CRITICAL RULES:
1. SAVE AFTER EVERY SINGLE CONTACT. Write to disk after each one.
2. Do a SMALL batch: find $BATCH_SIZE contacts/fixes, then stop.
3. Update $STATE_FILE new_contacts_added array after each contact.
4. Do NOT do more than $BATCH_SIZE. Quality over quantity.
5. Git add and commit your changes before exiting."

    case "$segment_name" in
        fix_bounced)
            echo "$base

TASK: Fix bounced emails using SUBAGENTS for research.
Read $CAMPAIGN_DIR/null_emails.md for the bounced contacts list.
Read $STATE_FILE to see which are already fixed (bounced_emails_fixed array).
Pick the next $BATCH_SIZE bounced contacts that haven't been fixed yet.

USE SUBAGENTS (the Agent tool) for the actual research. For each bounced contact:

  SUBAGENT: 'Research [Name] at [Company]'
    - Web search for their current company and email
    - Check if they left (the 'no longer with' cases)
    - Try email patterns: first.last@, flast@, firstl@, first@
    - Check company website team/about pages
    - Write findings to $NIGHTLY_DIR/logs/bounced_fixes_${today}.md (append)

After EACH subagent returns, immediately:
1. Read its findings from the file
2. Update state.json bounced_emails_fixed array
3. Move to the next contact

Run subagents ONE AT A TIME (sequential). Save after each one."
            ;;
        audit_emails)
            echo "$base

TASK: Audit and fix email formatting across all campaigns.
Use SUBAGENTS to process each campaign file in parallel (they're independent).

For each campaign master file, spawn a SUBAGENT:
  SUBAGENT: 'Audit [campaign] emails'
    - Read the campaign master file
    - For every email, check and fix:
      1. Remove em dashes, hyphens-as-dashes, double dashes
      2. Remove sign-off footers (email signature handles this)
      3. Fix sender identity to match NIGHTLY_PROMPT.md profile
      4. REMOVE any pricing, dollar amounts, cost comparisons, 'low-cost', 'affordable'
      5. Check subject lines under 60 chars
      6. Verify discovery/research tone, not sales pitch
    - Write fixes directly to the file
    - Write a summary to $NIGHTLY_DIR/logs/audit_[campaign]_${today}.md

After all subagents complete, compile summaries into $NIGHTLY_DIR/logs/audit_${today}.md"
            ;;
        *)
            echo "$base

TASK: Find $BATCH_SIZE NEW contacts for the '$segment_name' segment.
You are the ORCHESTRATOR. Use SUBAGENTS for the heavy work.

STEP 1 -- DEDUP CHECK (subagent):
  Spawn a subagent: 'Check existing contacts for dedup'
    - Read ALL files in $CAMPAIGN_DIR/$folder/
    - Read ALL other campaign folders (grep for company names)
    - Extract every company name and email domain already in use
    - Write the dedup list to $CAMPAIGN_DIR/$folder/temp_dedup_list.txt
    - This is research only, do NOT edit any files

STEP 2 -- FIND COMPANIES (subagent):
  Spawn a subagent: 'Find $BATCH_SIZE new ${segment_name} companies'
    - Read the dedup list from Step 1 to know what to avoid
    - Web search for $BATCH_SIZE NEW companies matching this segment
    - For each company: find company name, a decision-maker (name + title), and their email
    - Try multiple email search strategies: company website, LinkedIn, email patterns
    - Write results to $CAMPAIGN_DIR/$folder/temp_new_contacts.txt
    - Format: one contact per block with Name, Company, Title, Email, Source
    - This is research only, do NOT edit campaign files

STEP 3 -- WRITE EMAILS (you, the orchestrator):
  Read temp_new_contacts.txt from Step 2.
  For EACH contact found:
    1. Write personalized initial email + 2 follow-ups following the format in $PROMPT_FILE
    2. Append to $CAMPAIGN_DIR/$folder/nightly_additions_${today}.md
    3. Update $STATE_FILE: add to new_contacts_added array with {name, company, email, segment, date}
    4. SAVE THE FILE after each contact

  EMAIL RULES (MUST FOLLOW):
  - Sender identity must match the profile in NIGHTLY_PROMPT.md
  - NEVER mention pricing, dollar amounts, 'low-cost', 'affordable', or cost comparisons
  - NO sign-off footers. Email signature handles it.
  - NO em dashes or double dashes
  - Discovery/research tone, not sales

STEP 4 -- CLEANUP:
  Delete temp_dedup_list.txt and temp_new_contacts.txt
  Git add and commit your changes

Run Steps 1-2 as subagents. Step 3 you do yourself (small, controlled writes).
If a subagent fails, log the error and move on."
            ;;
    esac
}

# ===========================================
# MAIN LOOP: work through segments sequentially
# ===========================================

total_sessions=0

for segment_def in "${SEGMENTS[@]}"; do
    IFS=':' read -r seg_name seg_folder seg_file seg_target <<< "$segment_def"

    # Skip if already done today
    if is_segment_done "$seg_name"; then
        log "Segment '$seg_name' done for today. Skipping."
        continue
    fi

    log "=== Working on segment: $seg_name (target: $seg_target) ==="

    session_num=0
    while true; do
        # Check time
        remaining=$(time_remaining)
        if [ "$remaining" -lt 300 ]; then
            log "Less than 5 min remaining. Stopping."
            break 2  # break out of both loops
        fi

        # Check progress
        progress=$(count_segment_progress "$seg_name")
        log "  Progress: $progress / $seg_target"

        if [ "$progress" -ge "$seg_target" ]; then
            log "  Segment '$seg_name' target reached ($progress >= $seg_target)."

            # --- VALIDATION PASS: check all emails for this segment ---
            if [ "$seg_name" != "fix_bounced" ] && [ "$seg_name" != "audit_emails" ]; then
                remaining=$(time_remaining)
                if [ "$remaining" -gt 300 ]; then
                    log "  Running validation pass on '$seg_name' emails..."
                    total_sessions=$((total_sessions + 1))
                    validate_prompt=$(build_validate_prompt "$seg_name" "$seg_folder" "$seg_file")
                    if ! run_session "${seg_name}_validate" "$validate_prompt" "v1"; then
                        break 2
                    fi
                fi
            fi

            python3 -c "
import json
state = json.load(open('$STATE_FILE'))
if '$seg_name' not in state.get('segments_done_today', []):
    state.setdefault('segments_done_today', []).append('$seg_name')
json.dump(state, open('$STATE_FILE', 'w'), indent=2)
"
            log "  Moving to next segment."
            break
        fi

        session_num=$((session_num + 1))
        total_sessions=$((total_sessions + 1))

        # Safety: max 40 sessions per run (includes validation passes)
        if [ "$total_sessions" -gt 40 ]; then
            log "Hit 40 session safety limit. Stopping."
            break 2
        fi

        # Build prompt and run
        prompt=$(build_prompt "$seg_name" "$seg_folder" "$seg_file" "$progress" "$seg_target")
        if ! run_session "$seg_name" "$prompt" "$session_num"; then
            # Rate limited -- stop everything
            break 2
        fi

        # --- MINI VALIDATION: after every batch, validate what was just written ---
        remaining=$(time_remaining)
        if [ "$remaining" -gt 300 ] && [ "$seg_name" != "fix_bounced" ] && [ "$seg_name" != "audit_emails" ]; then
            log "  Running validation on batch $session_num..."
            total_sessions=$((total_sessions + 1))
            validate_prompt=$(build_validate_prompt "$seg_name" "$seg_folder" "$seg_file")
            if ! run_session "${seg_name}_validate" "$validate_prompt" "v${session_num}"; then
                break 2
            fi
        fi
    done
done

# --- Final push ---
cd "$REPO_DIR"
if [ -n "$(git log origin/main..HEAD --oneline 2>/dev/null)" ]; then
    log "Pushing all changes to remote..."
    git push origin main 2>&1 | tee -a "$RUN_LOG" || log "WARN: git push failed"
fi

elapsed=$(( $(date +%s) - START_TIME ))
log "=== Nightly run complete. Sessions: $total_sessions. Elapsed: ${elapsed}s ==="
