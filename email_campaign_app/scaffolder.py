"""Campaign scaffolder — creates folder structure and skeleton files from profile.

When the user saves their profile, this module:
1. Creates a campaigns/ folder per target segment
2. Writes README.md, skeleton master campaign file, and contacts.md stubs
3. Updates export_json.py's campaign registry (writes campaigns_meta.json)
4. Writes nightly/profile.json so shell scripts can read it

This gives the nightly Claude agent exact paths to read and write.
"""

import json
import os

# Resolve the repo root (two levels up from email_campaign_app/)
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
CAMPAIGNS_DIR = os.path.join(REPO_ROOT, 'campaigns')
NIGHTLY_DIR = os.path.join(REPO_ROOT, 'nightly')
EXPORTS_DIR = os.path.join(REPO_ROOT, 'exports')


def slugify(name):
    """Convert a segment name to a filesystem-safe slug."""
    return name.lower().replace(' ', '_').replace('/', '_').replace('-', '_')


def scaffold_campaigns(profile_dict):
    """Create campaign folder structure for every target segment.

    Args:
        profile_dict: dict with all profile fields (from profile_to_dict)

    Returns:
        dict mapping segment slug -> list of created file paths
    """
    segments = profile_dict.get('target_segments') or []
    if isinstance(segments, str):
        segments = json.loads(segments)

    created = {}
    for seg in segments:
        slug = slugify(seg['name'])
        created[slug] = _scaffold_segment(slug, seg, profile_dict)

    # Write the campaigns meta registry for export_json.py
    _write_campaigns_meta(segments, profile_dict)

    # Write profile.json for nightly scripts
    _write_nightly_profile(profile_dict)

    return created


def _scaffold_segment(slug, segment, profile):
    """Create folder + skeleton files for one segment."""
    seg_dir = os.path.join(CAMPAIGNS_DIR, slug)
    os.makedirs(seg_dir, exist_ok=True)

    files_created = []
    company = profile.get('company_name', '')
    industry = profile.get('industry', '')
    geography = profile.get('geography', '')
    product = profile.get('product_description', '')
    sender = profile.get('sender_name', '')
    tone = profile.get('tone_voice', 'Curious, respectful, not salesy')

    seg_name = segment['name']
    seg_desc = segment.get('description', '')
    seg_priority = segment.get('priority', 1)

    # 1. README.md
    readme_path = os.path.join(seg_dir, 'README.md')
    if not os.path.exists(readme_path):
        readme = f"""# {seg_name} -- Outreach Campaign

## Segment Overview
- **Segment:** {seg_name}
- **Priority:** {seg_priority}
- **ICP:** {seg_desc}
- **Company:** {company}
- **Industry:** {industry}
- **Geography:** {geography}
- **Product:** {product}

## File Map

| File | Purpose |
|------|---------|
| `{slug}_outreach_campaign.md` | Master campaign file (parser reads this) |
| `README.md` | This file -- segment overview and ICP |
| `contacts.md` | Contact research (names, titles, emails, LinkedIn) |
| `target_companies.md` | Company research (why each was selected) |
| `nightly_additions_*.md` | Contacts added by nightly automation |

## Email Tone
{tone}

## Status
- [ ] Company research complete
- [ ] Contacts discovered
- [ ] Emails written
- [ ] Follow-ups written
- [ ] Exported to JSON
- [ ] Imported into app
"""
        with open(readme_path, 'w') as f:
            f.write(readme)
        files_created.append(readme_path)

    # 2. Master campaign file (skeleton)
    master_path = os.path.join(seg_dir, f'{slug}_outreach_campaign.md')
    if not os.path.exists(master_path):
        master = f"""# {seg_name} Outreach Campaign
## Ready to Execute

---

## Campaign Summary

| Metric | Count |
|--------|-------|
| **Total target companies** | 0 |
| **Emails written (initial + follow-ups)** | 0 |
| **Wave 1 (HIGH confidence, best fit)** | 0 |

---

## HOW TO USE THIS DOCUMENT

This is your campaign file. The nightly agent appends new contacts here.
The markdown parser reads SECTION 2 to extract emails for the sending app.

1. **Section 1** -- Sending calendar (auto-generated once contacts exist)
2. **Section 2** -- All emails + follow-ups in parser-compatible format
3. **Section 3** -- Email confidence table

---

## SECTION 1: SENDING CALENDAR

(Will be populated as contacts are added)

---

## SECTION 2: ALL EMAILS + FOLLOW-UPS

(The nightly agent will add contacts below in this format:)

<!--
### #1 -- Company Name -- Wave 1

- **Email:** person@company.com
- **Status:** HIGH confidence, Response likelihood: 4/5

**Subject:** Your subject line here

**Body:**
Hi FirstName,

Your 2-3 sentence email body here.

**Follow-up 1 Subject:** Follow-up subject
**Follow-up 1:**
Short follow-up body.

**Follow-up 2 Subject:** Final follow-up subject
**Follow-up 2:**
Short final follow-up body.
-->

---

## SECTION 3: EMAIL CONFIDENCE TABLE

| # | Company | Contact | Email | Confidence | Response |
|---|---------|---------|-------|------------|----------|

"""
        with open(master_path, 'w') as f:
            f.write(master)
        files_created.append(master_path)

    # 3. contacts.md (skeleton)
    contacts_path = os.path.join(seg_dir, 'contacts.md')
    if not os.path.exists(contacts_path):
        contacts = f"""# {seg_name} -- Contact List

**Segment:** {seg_name}
**ICP:** {seg_desc}
**Total contacts:** 0

---

## Contacts

(Contacts will be added here by the nightly agent or manually.)

<!--
### #1 -- Company Name
- **Contact:** Full Name
- **Title:** Their Title
- **Email:** person@company.com (HIGH/MEDIUM/LOW)
- **LinkedIn:** https://linkedin.com/in/...
- **Source:** How you found them
- **Notes:** Background info
- **Personalization hooks:** Recent news, projects, etc.
-->
"""
        with open(contacts_path, 'w') as f:
            f.write(contacts)
        files_created.append(contacts_path)

    # 4. target_companies.md (skeleton)
    companies_path = os.path.join(seg_dir, 'target_companies.md')
    if not os.path.exists(companies_path):
        companies = f"""# {seg_name} -- Target Companies

**Segment:** {seg_name}
**ICP:** {seg_desc}
**Geography:** {geography}

---

## Selection Criteria

Companies that match:
- {seg_desc}
- Located in: {geography}
- Industry: {industry}

---

## Companies

(Companies will be researched and added here.)

<!--
### 1. Company Name
- **Location:** City, State
- **Size:** N employees / $NM revenue
- **Services:** What they do
- **Why target:** Why they're a good fit
- **Website:** example.com
-->
"""
        with open(companies_path, 'w') as f:
            f.write(companies)
        files_created.append(companies_path)

    return files_created


def _write_campaigns_meta(segments, profile):
    """Write campaigns_meta.json so export_json.py can discover campaigns dynamically."""
    meta = {
        'example_campaign': {
            'name': 'Example Outreach Campaign',
            'description': 'Example outreach campaign with fictional data',
            'campaign_file': 'example_outreach_campaign.md',
            'parser': 'generic',
            'max_emails_per_day': 15,
        },
    }

    for seg in segments:
        slug = slugify(seg['name'])
        meta[slug] = {
            'name': f"{seg['name']} Campaign",
            'description': seg.get('description', ''),
            'campaign_file': f'{slug}_outreach_campaign.md',
            'parser': 'generic',
            'max_emails_per_day': 15,
        }

    meta_path = os.path.join(CAMPAIGNS_DIR, 'campaigns_meta.json')
    with open(meta_path, 'w') as f:
        json.dump(meta, f, indent=2)


def _write_nightly_profile(profile_dict):
    """Write profile.json to the nightly directory for shell scripts."""
    os.makedirs(NIGHTLY_DIR, exist_ok=True)
    profile_path = os.path.join(NIGHTLY_DIR, 'profile.json')
    with open(profile_path, 'w') as f:
        json.dump(profile_dict, f, indent=2)
