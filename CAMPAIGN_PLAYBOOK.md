# Campaign Playbook — Agent Guide

Master guide for building, exporting, and importing email campaigns. Covers the full lifecycle from research through sending.

---

## 1. Campaign Registry

| Campaign | Folder | Status | Contacts | Ready to Send |
|----------|--------|--------|----------|---------------|
| Example Campaign | `campaigns/example_campaign/` | **Example** | 3 | 3 |

Add your campaigns to this registry as you create them. Each campaign folder should have a `README.md` with segment description, ICP, existing research pointers, volume targets, and what needs to happen.

---

## 3. How to Research a New Segment

Follow these steps to build a campaign from a stub folder to a sendable campaign.

### Step 1: Read the campaign README

Each stub folder has a `README.md` with existing research pointers. Read these source files FIRST to avoid duplicating work.

### Step 2: Build the prospect list

Use the subagent pipeline (see `AGENT_WORKFLOW.md`):

1. **SA1 — Company Research:** Search for companies matching the ICP. Target 2-3x the final contact count (e.g., 60 companies for 30 contacts). Write to `campaigns/<name>/target_companies.md`.
2. **SA2 — Contact Discovery:** Find decision-maker names, titles, LinkedIn profiles for each company. Write to `campaigns/<name>/contacts.md`.
3. **SA3 — Email Validation:** Find email patterns, validate with Hunter.io/NeverBounce. Write to `campaigns/<name>/validated_emails.md`.
4. **SA4 — Personalization Hooks:** Research recent news, projects, conference appearances, mutual connections for each contact. Write to `campaigns/<name>/personalization_hooks.md`.

### Step 3: Write the emails

5. **SA5 — Email Writing:** Write personalized initial emails (2-3 sentences each). Use the outreach script in the README as a base. Write to `campaigns/<name>/emails.md`.
6. **SA6 — Follow-ups:** Write 2 follow-up emails per contact (Day 3-4 and Day 7-8). Write to `campaigns/<name>/followups.md`.

### Step 4: Validate

7. **SA7 — Fact Check:** Verify every specific claim in the emails. Fix errors before sending.
8. **SA8 — Contact Audit:** Verify seniority fit — don't email CEOs at 10,000-employee companies.

### Step 5: Compile and export

Compile into a master file following the format of `campaigns/example_campaign/example_outreach_campaign.md`, then export to JSON (see Section 5).

---

## 4. How to Write Emails

### Format spec (must match the parser)

The markdown parser (`email_campaign_app/importer/markdown_parser.py`) expects this exact format:

```markdown
### #1 -- Company Name -- Wave 1

- **Email:** person@company.com
- **Status:** HIGH confidence, Response likelihood: 4/5

**Subject:** Your subject line here

**Body:**
Hi FirstName,

Your 2-3 sentence email body. Keep it short and specific.

**Follow-up 1 Subject:** Follow-up subject
**Follow-up 1:**
Short follow-up body.

**Follow-up 2 Subject:** Follow-up 2 subject
**Follow-up 2:**
Short follow-up body.
```

### Key rules

- **Contact headers:** `### #N -- Company -- Wave N` (the `#N` is the external_id)
- **Subject/Body markers:** Must start with `**Subject:**` and `**Body:**` on their own lines
- **Follow-up markers:** `**Follow-up 1 Subject:**` and `**Follow-up 1:**` (note: no "Body" in the follow-up marker)
- **Wave assignment:** Contacts are grouped by wave (1-5). Wave 1 = highest response likelihood.
- **Dropped contacts:** Add `DROPPED` to the header: `### #N -- Company -- Wave X -- DROPPED`
- **LinkedIn needed:** Add `NEEDS LINKEDIN` to the header

### Subject line guidelines

- Under 60 characters
- No ALL CAPS, no exclamation marks
- Reference their company or a specific project
- Examples: "Quick question about [Company]'s cooling setup", "Student research on [specific topic]"

### Body guidelines

- 2-3 sentences maximum for initial emails
- Curious, respectful tone, not salesy
- Include a specific ask: "Would you have 15 minutes this week?"
- Reference something specific about their company (from personalization hooks)

### Follow-up rules

- Follow-up 1: Send 3-4 days after initial. Add a NEW angle (don't just repeat).
- Follow-up 2: Send 7-8 days after initial. Final ask, brief, offer alternative (email reply if no call).
- Both should be shorter than the initial email.

---

## 5. How to Export and Import

### Export markdown to JSON

```bash
cd email_campaign
python3 email_campaign_app/importer/export_json.py -o campaign_export.json
```

This reads the campaign markdown files and produces a JSON file.

For a new campaign, either:
- **Reuse the parser:** Write your markdown in the same format as the example campaign. Update `export_json.py` to point to your campaign folder.
- **Write a new parser:** Add a parse function to `markdown_parser.py` that returns the same dict structure (see Section 7).

### JSON output format

```json
{
  "campaign": {
    "name": "Campaign Name",
    "description": "...",
    "send_start_hour": 8,
    "send_end_hour": 17,
    "max_emails_per_day": 15,
    "min_interval_minutes": 15,
    "followup1_delay_days": 3,
    "followup2_delay_days": 7,
    "timezone": "America/Los_Angeles"
  },
  "contacts": [
    {
      "external_id": "1",
      "name": "John Smith",
      "company": "Acme Corp",
      "title": "VP Engineering",
      "email": "john@acme.com",
      "email_confidence": "HIGH",
      "response_likelihood": 4,
      "wave": 1,
      "emails": [
        {"email_type": "initial", "subject": "...", "body": "..."},
        {"email_type": "followup1", "subject": "...", "body": "..."},
        {"email_type": "followup2", "subject": "...", "body": "..."}
      ]
    }
  ]
}
```

### Import into the app

Two methods:
- **Web UI:** Your campaign app → Contacts → Import → Upload JSON
- **API:** `POST /api/contacts/import-json` with the JSON body

Both create the Campaign + Contacts + Emails in one transaction.

### Activate

1. Campaigns page → click campaign → set status to `active`
2. Scheduler auto-generates daily queue at 7 AM Pacific
3. Or manually: Queue page → select campaign → "Generate Today's Queue"

---

## 6. Cross-Campaign Dedup

**Run this check BEFORE every import.** The app does NOT prevent the same email address from appearing in multiple campaigns.

```python
# In a Python shell with the app context:
from models import Contact
new_emails = ["john@acme.com", "jane@bigco.com"]  # your new campaign's emails
existing = Contact.query.filter(Contact.email.in_(new_emails)).all()
for c in existing:
    print(f"  DUPLICATE: {c.email} already in campaign '{c.campaign.name}' (id={c.campaign_id})")
```

If duplicates exist, decide:
- **Skip them** — remove from the new campaign
- **Include them** — they'll get emails from both campaigns (usually a bad idea)

### Known overlaps between segments

Track overlaps here as you discover them:

| Contact / Company | Appears in | Decision |
|-------------------|-----------|----------|
| *(add your overlaps here)* | | |

---

## 7. Markdown Format Reference

Minimal example that the parser can handle:

```markdown
### #1 -- Acme Corp -- Wave 1

- **Email:** john@acme.com
- **Status:** HIGH confidence, Response likelihood: 4/5

**Subject:** Quick question about Acme's monitoring setup

**Body:**
Hi John,

I'm researching predictive maintenance for commercial equipment.
Would you have 15 minutes to chat about how Acme handles equipment monitoring?

**Follow-up 1 Subject:** Following up — Acme monitoring question
**Follow-up 1:**
Hi John, just bumping this. Happy to work around your schedule.

**Follow-up 2 Subject:** One last try — 15 min on equipment monitoring?
**Follow-up 2:**
Hi John, last follow-up. If a call doesn't work, I'd welcome any thoughts by email.
```

---

## 8. Parser Extension Notes

To add support for a new markdown format:

1. Add a new parse function to `email_campaign_app/importer/markdown_parser.py`
2. It must return a list of dicts, each with at minimum:
   - `external_id` (str) — unique within the campaign
   - `name` (str)
   - `company` (str)
   - `email` (str)
   - `wave` (int)
   - `initial_subject`, `initial_body` (str)
   - `followup1_subject`, `followup1_body` (str)
   - `followup2_subject`, `followup2_body` (str)
3. Optional fields: `title`, `email_confidence`, `response_likelihood`, `needs_linkedin`, `is_dropped`, `personalization_hooks`, `ask_type`, `status_raw`
4. Create a new export script (or add a `--campaign` flag to `export_json.py`) that calls your parse function and outputs the standard JSON format
5. The `enrich_contacts()` function in `markdown_parser.py` handles merging data from supplementary files (contacts, hooks, followups, validated emails). You can reuse it if your supplementary files follow the same format, or write your own enrichment.

### Contact model fields (database)

For reference, the full `Contact` model accepts these fields:
- `external_id`, `name`, `company`, `title`, `email`, `email_confidence` (HIGH/MEDIUM/LOW)
- `response_likelihood` (1-5), `wave`, `ask_type`, `status`, `personalization_hooks` (JSON string)
- `notes`, `linkedin_url`, `needs_linkedin` (bool)

### Contact statuses (lifecycle)

`pending` → `initial_sent` → `followup1_sent` → `followup2_sent` → `completed`

Side statuses: `replied`, `bounced`, `opted_out`

The scheduler checks status to decide what to send next. Follow-ups auto-cancel if a reply is detected.
