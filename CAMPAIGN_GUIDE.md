# Adding Campaigns — Quick Checklist

For the full guide, see **`CAMPAIGN_PLAYBOOK.md`**.

---

## Checklist

1. Read the campaign stub README in `campaigns/<name>/README.md`
2. Research prospects using the subagent pipeline (see playbook Section 3)
3. Write emails in the parser-compatible markdown format (see playbook Section 7)
4. Export to JSON: `python3 email_campaign_app/importer/export_json.py -o campaign_export.json`
5. **Run cross-campaign dedup check** (see playbook Section 6) — REQUIRED
6. Import via web UI or API: `POST /api/contacts/import-json`
7. Activate campaign and verify queue generation

## Key files

| File | Purpose |
|------|---------|
| `CAMPAIGN_PLAYBOOK.md` | Full guide — research, writing, format spec, export, dedup |
| `campaigns/example_campaign/` | Reference campaign (3 example contacts, fully built) |
| `email_campaign_app/importer/markdown_parser.py` | Markdown parsing functions |
| `email_campaign_app/importer/export_json.py` | Markdown → JSON export |
| `email_campaign_app/models.py` | Database models (Campaign, Contact, Email) |
