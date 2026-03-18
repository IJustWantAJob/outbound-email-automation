#!/usr/bin/env python3
"""Build a nightly expansion prompt from the sender profile.

Usage:
    python3 build_prompt.py --segment "HVAC Service Companies" --batch 1 --date 2026-03-15 --batch-size 5
    python3 build_prompt.py --list-segments
    python3 build_prompt.py --show-paths            # Show all file paths Claude should know

Reads profile.json from the same directory (exported by the web app).
"""

import argparse
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_PATH = os.path.join(SCRIPT_DIR, 'profile.json')


def load_profile():
    if not os.path.exists(PROFILE_PATH):
        print("ERROR: profile.json not found. Complete the profile setup in the web app first.", file=sys.stderr)
        sys.exit(1)
    with open(PROFILE_PATH, 'r') as f:
        return json.load(f)


def slugify(name):
    return name.lower().replace(' ', '_').replace('/', '_').replace('-', '_')


def list_segments(profile):
    segments = profile.get('target_segments') or []
    if not segments:
        print("No segments configured. Add them in Settings > Profile.", file=sys.stderr)
        sys.exit(1)
    for seg in sorted(segments, key=lambda s: s.get('priority', 99)):
        slug = slugify(seg['name'])
        print(f"  {slug:30s} (priority {seg.get('priority', '?')}) -- {seg.get('description', '')}")


def show_paths(profile):
    """Print every file path that the nightly Claude agent needs to know."""
    segments = profile.get('target_segments') or []
    print("=== FILE PATH MAP FOR NIGHTLY AGENT ===\n")
    print("## Global Files")
    print(f"  nightly/NIGHTLY_PROMPT.md          -- Agent rules and email format")
    print(f"  nightly/state.json                  -- Progress tracker (read/write)")
    print(f"  nightly/profile.json                -- Sender profile (read only)")
    print(f"  null_emails.md                      -- Bounced contacts list")
    print(f"  CAMPAIGN_PLAYBOOK.md                -- Format reference")
    print()
    print("## Per-Segment Campaign Files")
    for seg in sorted(segments, key=lambda s: s.get('priority', 99)):
        slug = slugify(seg['name'])
        print(f"\n  ### {seg['name']} (priority {seg.get('priority', '?')})")
        print(f"  campaigns/{slug}/README.md                          -- Segment ICP and overview")
        print(f"  campaigns/{slug}/{slug}_outreach_campaign.md        -- MASTER FILE (append emails here)")
        print(f"  campaigns/{slug}/contacts.md                        -- Contact research")
        print(f"  campaigns/{slug}/target_companies.md                -- Company research")
        print(f"  campaigns/{slug}/nightly_additions_{{DATE}}.md       -- Nightly agent writes here")
    print()
    print("## Temporary Files (create then delete)")
    print(f"  campaigns/temp_dedup_list.txt       -- Dedup check output")
    print(f"  campaigns/temp_new_contacts.txt      -- Research output")
    print()
    print("## Exports")
    print(f"  exports/{{campaign}}.json             -- JSON for app import")


def build_expansion_prompt(profile, segment_name, batch_num, today, batch_size):
    """Build a segment-specific expansion prompt with exact file paths."""
    segments = profile.get('target_segments') or []
    segment = None
    segment_slug = slugify(segment_name)
    for seg in segments:
        slug = slugify(seg['name'])
        if slug == segment_slug or seg['name'].lower() == segment_name.lower():
            segment = seg
            break

    if not segment:
        print(f"ERROR: Segment '{segment_name}' not found in profile.", file=sys.stderr)
        print("Available segments:", file=sys.stderr)
        list_segments(profile)
        sys.exit(1)

    seg_name = segment['name']
    seg_desc = segment.get('description', '')
    slug = slugify(seg_name)
    company = profile.get('company_name', '')
    industry = profile.get('industry', '')
    geography = profile.get('geography', '')
    product = profile.get('product_description', '')
    sender = profile.get('sender_name', '')
    tone = profile.get('tone_voice', 'Curious, respectful, not salesy')
    university = profile.get('university', '')

    sender_intro = f"{sender}"
    if university:
        sender_intro += f", student at {university}"
    if profile.get('sender_title'):
        sender_intro += f", {profile['sender_title']} at {company}"

    # Build the list of ALL campaign folders for dedup
    all_campaign_paths = []
    for s in segments:
        s_slug = slugify(s['name'])
        all_campaign_paths.append(f"campaigns/{s_slug}/{s_slug}_outreach_campaign.md")
        all_campaign_paths.append(f"campaigns/{s_slug}/nightly_additions_*.md")
        all_campaign_paths.append(f"campaigns/{s_slug}/contacts.md")
    all_paths_str = '\n'.join(f"    - {p}" for p in all_campaign_paths)

    prompt = f"""You are a nightly automated agent for email campaigns.
You were launched with: claude --dangerously-skip-permissions

DATE: {today} | TASK: Find {batch_size} NEW contacts for "{seg_name}" (batch {batch_num})

## EXACT FILE PATHS (READ THIS FIRST)

You MUST use these exact paths. Do not guess or make up paths.

### Files to READ:
- `nightly/NIGHTLY_PROMPT.md` -- Full email rules, validation checklist, format spec
- `nightly/state.json` -- What's already been done today
- `nightly/profile.json` -- Sender profile (company, segments, tone)

### Campaign files to READ for dedup:
{all_paths_str}

### Files to WRITE:
- `campaigns/{slug}/nightly_additions_{today}.md` -- APPEND new contacts + emails here
- `campaigns/{slug}/contacts.md` -- APPEND new contact research here
- `nightly/state.json` -- UPDATE with new_contacts_added after each contact

### Temporary files (CREATE then DELETE):
- `campaigns/temp_dedup_list.txt` -- Dedup subagent writes here
- `campaigns/temp_new_contacts.txt` -- Research subagent writes here

### Files NEVER to modify:
- `nightly/profile.json` (read-only, managed by the web app)
- `nightly/NIGHTLY_PROMPT.md` (read-only, template)
- `campaigns/example_campaign/*` (reference only)

---

## COMPANY CONTEXT
**Company:** {company}
**Industry:** {industry}
**Product:** {product}
**Geography:** {geography}
**Sender:** {sender_intro}
**Tone:** {tone}

## SEGMENT: {seg_name}
**ICP:** {seg_desc}
**Campaign folder:** `campaigns/{slug}/`
**Master file:** `campaigns/{slug}/{slug}_outreach_campaign.md`

## YOUR MISSION
Find {batch_size} NEW companies/contacts matching the "{seg_name}" segment that we have NOT already contacted.

## STEP 1 — DEDUP (subagent, research only)

Spawn a subagent: "Dedup check for {seg_name}"

The subagent must:
1. Read ALL campaign master files and nightly_additions files listed above
2. Extract EVERY company name and email domain already used
3. Write the full list to `campaigns/temp_dedup_list.txt`
4. Include the count: "Total existing contacts: N"

DO NOT skip this step. Duplicates waste sends and annoy prospects.

## STEP 2 — RESEARCH (subagent, research only)

Spawn a subagent: "Find {batch_size} new {seg_name} contacts"

The subagent must read `campaigns/temp_dedup_list.txt` first, then search for NEW companies.

### Search strategies (try in order):

**A. Geographic expansion:**
- Web search: "{seg_desc}" + cities in {geography}
- Web search: "commercial {industry}" + specific city names
- Industry-specific directory searches

**B. Industry directories:**
- Search relevant trade associations and member directories for {industry}
- Search review sites for established commercial companies in {industry}
- Check professional licensing boards

**C. LinkedIn and professional networks:**
- Search for decision-makers matching: {seg_desc}
- Look for companies posting about {industry} topics

### For each company found, write to `campaigns/temp_new_contacts.txt`:
```
---
Company: [name]
City: [city, state]
Size: [small/medium/large]
Contact: [full name]
Title: [title]
Email: [email]
Email Confidence: [HIGH/MEDIUM/LOW]
LinkedIn: [url or "not found"]
Hook: [one sentence personalization]
Source: [where you found them]
---
```

### ICP Filters:
- MUST match: {seg_desc}
- PREFER companies with 10+ employees
- AVOID companies already in the dedup list

## STEP 3 — WRITE EMAILS (you, the orchestrator)

Read `campaigns/temp_new_contacts.txt`. For EACH contact:

1. Write a personalized initial email (2-3 sentences):
   - Reference their specific company and the personalization hook
   - Introduce yourself as: {sender_intro}
   - Ask for 15 minutes of their time
   - Tone: {tone}

2. Write Follow-up 1 (send 3 days later):
   - Add a NEW angle, don't repeat the initial
   - 1-2 sentences

3. Write Follow-up 2 (send 7 days later):
   - Final ask, 1 sentence
   - Offer email reply as alternative

4. Use this EXACT markdown format:
```
### #N -- Company Name -- Wave 1

- **Email:** person@company.com
- **Status:** [CONFIDENCE] confidence, Response likelihood: X/5

**Subject:** [under 60 chars, no caps, no exclamation]

**Body:**
Hi FirstName,

[2-3 sentences]

**Follow-up 1 Subject:** [subject]
**Follow-up 1:**
[1-2 sentences]

**Follow-up 2 Subject:** [subject]
**Follow-up 2:**
[1 sentence]
```

5. APPEND to `campaigns/{slug}/nightly_additions_{today}.md`
6. Also APPEND the contact research to `campaigns/{slug}/contacts.md`
7. UPDATE `nightly/state.json`: add to new_contacts_added array:
   {{"name": "...", "company": "...", "email": "...", "segment": "{slug}", "date": "{today}"}}
8. SAVE AFTER EACH CONTACT — do not batch in memory

### EMAIL RULES (VIOLATING THESE WASTES THE CONTACT):
- NEVER mention pricing, dollar amounts, "low-cost", "affordable"
- Sender identity: {sender_intro}
- NEVER include sign-off — email signature handles it
- NEVER use em dashes or double dashes — use commas or periods
- Subject lines under 60 chars, no ALL CAPS, no exclamation marks
- Tone: {tone}

## STEP 4 — CLEANUP
- DELETE `campaigns/temp_dedup_list.txt`
- DELETE `campaigns/temp_new_contacts.txt`
- Git add and commit: "nightly: {slug} expand +N contacts (batch {batch_num})"
"""
    return prompt


def main():
    parser = argparse.ArgumentParser(description='Build nightly expansion prompt from profile')
    parser.add_argument('--segment', '-s', help='Segment name or slug')
    parser.add_argument('--batch', '-b', type=int, default=1, help='Batch number')
    parser.add_argument('--date', '-d', default='today', help='Date string')
    parser.add_argument('--batch-size', type=int, default=5, help='Contacts to find')
    parser.add_argument('--list-segments', action='store_true', help='List available segments')
    parser.add_argument('--show-paths', action='store_true', help='Show all file paths')
    args = parser.parse_args()

    profile = load_profile()

    if args.list_segments:
        list_segments(profile)
        return

    if args.show_paths:
        show_paths(profile)
        return

    if not args.segment:
        print("ERROR: --segment is required. Use --list-segments to see options.", file=sys.stderr)
        sys.exit(1)

    prompt = build_expansion_prompt(
        profile, args.segment, args.batch, args.date, args.batch_size
    )
    print(prompt)


if __name__ == '__main__':
    main()
