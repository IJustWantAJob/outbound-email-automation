"""Tests for the markdown parser and contact importer."""

import json
import os
import sys
import pytest

# Ensure the app package is importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from importer.markdown_parser import (
    parse_campaign_markdown,
    enrich_contacts,
    parse_enrichment_contacts,
    parse_enrichment_emails_v2,
    parse_personalization_hooks,
    parse_followups,
    parse_validated_emails,
    _normalize_company,
)
from importer.contact_importer import import_contacts
from models import Campaign, Contact, Email

# Path to the real campaign markdown file
CAMPAIGN_MD = os.path.join(
    os.path.dirname(__file__),
    '..', '..', 'example_outreach_campaign.md',
)
CAMPAIGN_MD = os.path.abspath(CAMPAIGN_MD)

CONTACTS_MD = os.path.join(
    os.path.dirname(__file__),
    '..', '..', 'example_contacts.md',
)
CONTACTS_MD = os.path.abspath(CONTACTS_MD)

EMAILS_V2_MD = os.path.join(
    os.path.dirname(__file__),
    '..', '..', 'example_emails_v2.md',
)
EMAILS_V2_MD = os.path.abspath(EMAILS_V2_MD)

HOOKS_MD = os.path.join(
    os.path.dirname(__file__),
    '..', '..', 'example_hooks.md',
)
HOOKS_MD = os.path.abspath(HOOKS_MD)

FOLLOWUPS_MD = os.path.join(
    os.path.dirname(__file__),
    '..', '..', 'example_followups.md',
)
FOLLOWUPS_MD = os.path.abspath(FOLLOWUPS_MD)

VALIDATED_MD = os.path.join(
    os.path.dirname(__file__),
    '..', '..', 'example_validated_emails.md',
)
VALIDATED_MD = os.path.abspath(VALIDATED_MD)

REAL_FILE_EXISTS = os.path.exists(CAMPAIGN_MD)
HOOKS_FILE_EXISTS = os.path.exists(HOOKS_MD)
FOLLOWUPS_FILE_EXISTS = os.path.exists(FOLLOWUPS_MD)
VALIDATED_FILE_EXISTS = os.path.exists(VALIDATED_MD)


# ---------------------------------------------------------------------------
# Fixture: a small markdown snippet for unit tests
# ---------------------------------------------------------------------------

SAMPLE_READY_CONTACT = """## SECTION 2: ALL 50 EMAILS + FOLLOW-UPS (Ready to Send)

---

### #1 -- Acme Hosting -- Wave 2
**To:** athompson@acmehosting.com
**Status:** READY TO SEND
**Email Confidence:** MEDIUM (75% pattern)
**Response Likelihood:** 4/5

**Initial Email:**
Subject: Cooling in a converted building?

Hi Alice,

I'm researching predictive maintenance for commercial equipment. Would you have 15 minutes to discuss how your team handles equipment monitoring?

**Follow-Up #1 (Day 3-4):**
Subject: Re: Cooling in a converted building?

Hi Alice, just bumping this. I've been reading about how converted facilities often run into airflow issues.

**Follow-Up #2 (Day 7-8):**
Subject: Re: Cooling in a converted building?

Hi Alice, last note from me. One quick question I'd love your take on even over email.

---

## SECTION 3: LINKEDIN SALES NAVIGATOR PLAYBOOK
"""

SAMPLE_NEEDS_LINKEDIN = """## SECTION 2: ALL 50 EMAILS + FOLLOW-UPS (Ready to Send)

---

### #10 -- Summit Mechanical / Legence -- Wave 5 (NEEDS LINKEDIN)
**To:** [FIND ON LINKEDIN: Director of Engineering or Director of Data Center Services at Summit Mechanical]
**Status:** NEEDS LINKEDIN CONTACT
**Email Confidence:** N/A until contact found (pattern: {first_initial}{last}@summitmech.com, 61%)
**Response Likelihood:** TBD

**Initial Email:**
Subject: DC cooling failures -- what do you see?

Hi [First Name],

I'm researching predictive maintenance for commercial equipment, and I'm curious what failures service companies like Summit Mechanical encounter most often.

**Follow-Up #1 (Day 3-4):**
[Write after finding contact -- use same tone as other follow-ups]

**Follow-Up #2 (Day 7-8):**
[Write after finding contact]

---

## SECTION 3: LINKEDIN SALES NAVIGATOR PLAYBOOK
"""

SAMPLE_DROPPED = """## SECTION 2: ALL 50 EMAILS + FOLLOW-UPS (Ready to Send)

---

### #13 -- Metro Engineering -- DROPPED (Merged with #48)

This email has been dropped. Carlos Rivera (Email #48) is the better Metro Engineering contact at Director level.

---

## SECTION 3: LINKEDIN SALES NAVIGATOR PLAYBOOK
"""

SAMPLE_MULTI = """## SECTION 2: ALL 50 EMAILS + FOLLOW-UPS (Ready to Send)

---

### #1 -- Acme Hosting -- Wave 2
**To:** athompson@acmehosting.com
**Status:** READY TO SEND
**Email Confidence:** MEDIUM (75% pattern)
**Response Likelihood:** 4/5

**Initial Email:**
Subject: Cooling in a converted building?

Hi Alice,

Body text here.

**Follow-Up #1 (Day 3-4):**
Subject: Re: Cooling in a converted building?

Hi Alice, bumping this.

**Follow-Up #2 (Day 7-8):**
Subject: Re: Cooling in a converted building?

Hi Alice, last note.

---

### #10 -- Summit Mechanical / Legence -- Wave 5 (NEEDS LINKEDIN)
**To:** [FIND ON LINKEDIN: Director of Engineering at Summit Mechanical]
**Status:** NEEDS LINKEDIN CONTACT
**Email Confidence:** N/A until contact found (pattern: {first_initial}{last}@summitmech.com, 61%)
**Response Likelihood:** TBD

**Initial Email:**
Subject: DC cooling failures -- what do you see?

Hi [First Name],

Body text about Summit Mechanical.

**Follow-Up #1 (Day 3-4):**
[Write after finding contact -- use same tone as other follow-ups]

**Follow-Up #2 (Day 7-8):**
[Write after finding contact]

---

### #13 -- Metro Engineering -- DROPPED (Merged with #48)

This email has been dropped.

---

## SECTION 3: LINKEDIN SALES NAVIGATOR PLAYBOOK
"""


@pytest.fixture
def sample_ready_file(tmp_path):
    """Write sample READY contact to a temp file."""
    p = tmp_path / "test_ready.md"
    p.write_text(SAMPLE_READY_CONTACT, encoding='utf-8')
    return str(p)


@pytest.fixture
def sample_linkedin_file(tmp_path):
    """Write sample NEEDS LINKEDIN contact to a temp file."""
    p = tmp_path / "test_linkedin.md"
    p.write_text(SAMPLE_NEEDS_LINKEDIN, encoding='utf-8')
    return str(p)


@pytest.fixture
def sample_dropped_file(tmp_path):
    """Write sample DROPPED contact to a temp file."""
    p = tmp_path / "test_dropped.md"
    p.write_text(SAMPLE_DROPPED, encoding='utf-8')
    return str(p)


@pytest.fixture
def sample_multi_file(tmp_path):
    """Write sample with multiple contact types to a temp file."""
    p = tmp_path / "test_multi.md"
    p.write_text(SAMPLE_MULTI, encoding='utf-8')
    return str(p)


# ===========================================================================
# PARSER TESTS
# ===========================================================================


class TestParseReadyContact:
    """test_parse_ready_contact: Parse a single READY TO SEND contact."""

    def test_basic_fields(self, sample_ready_file):
        contacts = parse_campaign_markdown(sample_ready_file)
        assert len(contacts) == 1
        c = contacts[0]
        assert c['external_id'] == 1
        assert c['company'] == 'Acme Hosting'
        assert c['wave'] == 2
        assert c['email'] == 'athompson@acmehosting.com'
        assert c['status_raw'] == 'READY TO SEND'
        assert c['email_confidence'] == 'MEDIUM'
        assert c['response_likelihood'] == 4
        assert c['needs_linkedin'] is False
        assert c['is_dropped'] is False

    def test_initial_email(self, sample_ready_file):
        contacts = parse_campaign_markdown(sample_ready_file)
        c = contacts[0]
        assert c['initial_subject'] == 'Cooling in a converted building?'
        assert 'Hi Alice,' in c['initial_body']
        assert 'predictive maintenance' in c['initial_body']

    def test_followups(self, sample_ready_file):
        contacts = parse_campaign_markdown(sample_ready_file)
        c = contacts[0]
        assert c['followup1_subject'] == 'Re: Cooling in a converted building?'
        assert 'bumping this' in c['followup1_body']
        assert c['followup2_subject'] == 'Re: Cooling in a converted building?'
        assert 'last note' in c['followup2_body']


class TestParseNeedsLinkedinContact:
    """test_parse_needs_linkedin_contact: Parse a NEEDS LINKEDIN contact."""

    def test_linkedin_flags(self, sample_linkedin_file):
        contacts = parse_campaign_markdown(sample_linkedin_file)
        assert len(contacts) == 1
        c = contacts[0]
        assert c['needs_linkedin'] is True
        assert c['email'] == ''
        assert c['external_id'] == 10
        assert c['company'] == 'Summit Mechanical / Legence'
        assert c['wave'] == 5

    def test_status_and_confidence(self, sample_linkedin_file):
        contacts = parse_campaign_markdown(sample_linkedin_file)
        c = contacts[0]
        assert c['status_raw'] == 'NEEDS LINKEDIN CONTACT'
        assert c['email_confidence'] == ''  # N/A
        assert c['response_likelihood'] == 0  # TBD

    def test_initial_email_present(self, sample_linkedin_file):
        contacts = parse_campaign_markdown(sample_linkedin_file)
        c = contacts[0]
        assert c['initial_subject'] == 'DC cooling failures -- what do you see?'
        assert '[First Name]' in c['initial_body']


class TestParseDroppedContact:
    """test_parse_dropped_contact: Parse DROPPED contact #13."""

    def test_dropped_flags(self, sample_dropped_file):
        contacts = parse_campaign_markdown(sample_dropped_file)
        assert len(contacts) == 1
        c = contacts[0]
        assert c['is_dropped'] is True
        assert c['external_id'] == 13
        assert c['company'] == 'Metro Engineering'
        assert c['email'] == ''
        assert c['initial_subject'] == ''
        assert c['initial_body'] == ''


class TestParseAllContactsCount:
    """test_parse_all_contacts_count: Parse the real file, verify 50 contacts."""

    @pytest.mark.skipif(
        not REAL_FILE_EXISTS,
        reason="Real campaign markdown file not found"
    )
    def test_total_count(self):
        contacts = parse_campaign_markdown(CAMPAIGN_MD)
        assert len(contacts) == 50


class TestParseWaveExtraction:
    """test_parse_wave_extraction: Verify waves 1-5 are extracted correctly."""

    @pytest.mark.skipif(
        not REAL_FILE_EXISTS,
        reason="Real campaign markdown file not found"
    )
    def test_waves(self):
        contacts = parse_campaign_markdown(CAMPAIGN_MD)
        waves = {c['wave'] for c in contacts if not c['is_dropped']}
        # Waves 1 through 5 should be present
        assert waves == {1, 2, 3, 4, 5}

    def test_wave_from_fixture(self, sample_ready_file):
        contacts = parse_campaign_markdown(sample_ready_file)
        assert contacts[0]['wave'] == 2

    def test_wave_5_for_linkedin(self, sample_linkedin_file):
        contacts = parse_campaign_markdown(sample_linkedin_file)
        assert contacts[0]['wave'] == 5


class TestParseEmailConfidenceExtraction:
    """test_parse_email_confidence_extraction: Verify HIGH, MEDIUM, N/A."""

    @pytest.mark.skipif(
        not REAL_FILE_EXISTS,
        reason="Real campaign markdown file not found"
    )
    def test_confidence_levels(self):
        contacts = parse_campaign_markdown(CAMPAIGN_MD)
        confidences = {c['email_confidence'] for c in contacts}
        assert 'HIGH' in confidences
        assert 'MEDIUM' in confidences
        # N/A should be mapped to ''
        assert '' in confidences

    def test_medium_confidence(self, sample_ready_file):
        contacts = parse_campaign_markdown(sample_ready_file)
        assert contacts[0]['email_confidence'] == 'MEDIUM'

    def test_na_confidence(self, sample_linkedin_file):
        contacts = parse_campaign_markdown(sample_linkedin_file)
        assert contacts[0]['email_confidence'] == ''


class TestParseInitialEmailExtraction:
    """test_parse_initial_email_extraction: Verify subject and body captured."""

    def test_subject_extracted(self, sample_ready_file):
        contacts = parse_campaign_markdown(sample_ready_file)
        c = contacts[0]
        assert c['initial_subject'] == 'Cooling in a converted building?'

    def test_body_extracted(self, sample_ready_file):
        contacts = parse_campaign_markdown(sample_ready_file)
        c = contacts[0]
        assert len(c['initial_body']) > 20
        assert c['initial_body'].startswith('Hi Alice,')

    @pytest.mark.skipif(
        not REAL_FILE_EXISTS,
        reason="Real campaign markdown file not found"
    )
    def test_all_ready_contacts_have_subjects(self):
        contacts = parse_campaign_markdown(CAMPAIGN_MD)
        for c in contacts:
            if not c['is_dropped']:
                assert c['initial_subject'], (
                    f"Contact #{c['external_id']} missing initial subject"
                )


class TestParseFollowupExtraction:
    """test_parse_followup_extraction: Verify both follow-ups captured."""

    def test_followup1(self, sample_ready_file):
        contacts = parse_campaign_markdown(sample_ready_file)
        c = contacts[0]
        assert c['followup1_subject'] == 'Re: Cooling in a converted building?'
        assert len(c['followup1_body']) > 10

    def test_followup2(self, sample_ready_file):
        contacts = parse_campaign_markdown(sample_ready_file)
        c = contacts[0]
        assert c['followup2_subject'] == 'Re: Cooling in a converted building?'
        assert len(c['followup2_body']) > 10

    @pytest.mark.skipif(
        not REAL_FILE_EXISTS,
        reason="Real campaign markdown file not found"
    )
    def test_ready_contacts_have_followups(self):
        """All READY TO SEND contacts should have follow-up subjects."""
        contacts = parse_campaign_markdown(CAMPAIGN_MD)
        for c in contacts:
            if not c['is_dropped'] and not c['needs_linkedin']:
                assert c['followup1_subject'], (
                    f"Contact #{c['external_id']} missing followup1 subject"
                )
                assert c['followup2_subject'], (
                    f"Contact #{c['external_id']} missing followup2 subject"
                )


class TestParsePlaceholderFollowups:
    """test_parse_placeholder_followups: NEEDS LINKEDIN contacts have empty follow-ups."""

    def test_empty_followups(self, sample_linkedin_file):
        contacts = parse_campaign_markdown(sample_linkedin_file)
        c = contacts[0]
        assert c['followup1_subject'] == ''
        assert c['followup1_body'] == ''
        assert c['followup2_subject'] == ''
        assert c['followup2_body'] == ''

    @pytest.mark.skipif(
        not REAL_FILE_EXISTS,
        reason="Real campaign markdown file not found"
    )
    def test_all_linkedin_contacts_have_empty_followups(self):
        contacts = parse_campaign_markdown(CAMPAIGN_MD)
        for c in contacts:
            if c['needs_linkedin']:
                assert c['followup1_subject'] == '', (
                    f"Contact #{c['external_id']} should have empty followup1 subject"
                )
                assert c['followup1_body'] == '', (
                    f"Contact #{c['external_id']} should have empty followup1 body"
                )


# ===========================================================================
# IMPORTER TESTS
# ===========================================================================


class TestImportCreatesContacts:
    """test_import_creates_contacts: Verify correct number of Contact records."""

    def test_creates_contacts(self, db, sample_multi_file):
        contacts = parse_campaign_markdown(sample_multi_file)
        num_created, num_emails, num_skipped = import_contacts(contacts)
        # 3 contacts total: #1 (ready), #10 (linkedin), #13 (dropped/skipped)
        assert num_created == 2  # #1 and #10
        assert Contact.query.count() == 2

    def test_contact_fields(self, db, sample_ready_file):
        contacts = parse_campaign_markdown(sample_ready_file)
        num_created, _, _ = import_contacts(contacts)
        assert num_created == 1
        c = Contact.query.first()
        assert c.external_id == '1'
        assert c.company == 'Acme Hosting'
        assert c.email == 'athompson@acmehosting.com'
        assert c.wave == 2


class TestImportCreatesEmails:
    """test_import_creates_emails: Verify 3 Email records per non-dropped contact."""

    def test_three_emails_per_contact(self, db, sample_ready_file):
        contacts = parse_campaign_markdown(sample_ready_file)
        num_created, num_emails, _ = import_contacts(contacts)
        assert num_created == 1
        assert num_emails == 3
        assert Email.query.count() == 3

    def test_email_types(self, db, sample_ready_file):
        contacts = parse_campaign_markdown(sample_ready_file)
        import_contacts(contacts)
        emails = Email.query.all()
        types = {e.email_type for e in emails}
        assert types == {'initial', 'followup1', 'followup2'}

    def test_multi_contact_emails(self, db, sample_multi_file):
        contacts = parse_campaign_markdown(sample_multi_file)
        _, num_emails, _ = import_contacts(contacts)
        # 2 non-dropped contacts x 3 emails each = 6
        assert num_emails == 6
        assert Email.query.count() == 6


class TestImportSkipsDropped:
    """test_import_skips_dropped: Verify #13 is not imported."""

    def test_skips_dropped(self, db, sample_dropped_file):
        contacts = parse_campaign_markdown(sample_dropped_file)
        num_created, num_emails, num_skipped = import_contacts(contacts)
        assert num_created == 0
        assert num_emails == 0
        assert num_skipped == 1
        assert Contact.query.count() == 0

    def test_dropped_in_multi(self, db, sample_multi_file):
        contacts = parse_campaign_markdown(sample_multi_file)
        _, _, num_skipped = import_contacts(contacts)
        assert num_skipped == 1  # Only #13 is skipped


class TestImportSetsNeedsLinkedin:
    """test_import_sets_needs_linkedin: Verify needs_linkedin_verification flag."""

    def test_linkedin_flag(self, db, sample_linkedin_file):
        contacts = parse_campaign_markdown(sample_linkedin_file)
        import_contacts(contacts)
        c = Contact.query.first()
        assert c.needs_linkedin_verification is True
        assert c.email == ''

    def test_ready_not_linkedin(self, db, sample_ready_file):
        contacts = parse_campaign_markdown(sample_ready_file)
        import_contacts(contacts)
        c = Contact.query.first()
        assert c.needs_linkedin_verification is False


class TestImportCreatesCampaign:
    """test_import_creates_campaign: Verify a Campaign is created if none provided."""

    def test_creates_campaign(self, db, sample_ready_file):
        contacts = parse_campaign_markdown(sample_ready_file)
        import_contacts(contacts)
        campaigns = Campaign.query.all()
        assert len(campaigns) == 1
        assert campaigns[0].name == 'Imported Campaign'
        assert campaigns[0].status == 'draft'

    def test_uses_existing_campaign(self, db, sample_ready_file):
        campaign = Campaign(name='Existing Campaign', status='active')
        db.session.add(campaign)
        db.session.flush()
        contacts = parse_campaign_markdown(sample_ready_file)
        import_contacts(contacts, campaign_id=campaign.id)
        # Should still be just 1 campaign
        assert Campaign.query.count() == 1
        c = Contact.query.first()
        assert c.campaign_id == campaign.id


class TestImportIdempotent:
    """test_import_idempotent: Running import twice doesn't create duplicates."""

    def test_no_duplicates(self, db, sample_multi_file):
        contacts = parse_campaign_markdown(sample_multi_file)
        c1, e1, s1 = import_contacts(contacts)
        assert c1 == 2
        assert e1 == 6

        # Import again with the same data — should create a new campaign
        # but since we pass the same campaign, contacts should be skipped
        campaign = Campaign.query.first()
        c2, e2, s2 = import_contacts(contacts, campaign_id=campaign.id)
        assert c2 == 0
        assert e2 == 0
        assert s2 == 3  # 2 already exist + 1 dropped

        # Total should still be 2 contacts, 6 emails
        assert Contact.query.count() == 2
        assert Email.query.count() == 6

    def test_idempotent_single(self, db, sample_ready_file):
        contacts = parse_campaign_markdown(sample_ready_file)
        import_contacts(contacts)
        campaign = Campaign.query.first()
        c2, e2, s2 = import_contacts(contacts, campaign_id=campaign.id)
        assert c2 == 0
        assert s2 == 1
        assert Contact.query.count() == 1


# ===========================================================================
# NEW PARSER TESTS: personalization hooks, followups, validated emails
# ===========================================================================

# --- Fixture: sample personalization hooks markdown ---

SAMPLE_HOOKS = """# Data Center Company Personalization Hooks

---

## Tier 1: Bay Area Colocation

---

### 1. Acme Hosting (Santa Clara)
**Recent News:** FiberLink deployed a new PoP at Acme Hosting.
**Contact Hook:** CEO Alice Thompson leads the company.
**Academic Connection:** None found.
**Cooling Angle:** Boutique operator with unique cooling challenges.
**Unique Detail:** 20+ years of experience.
**Suggested Opening Line:** "I saw Acme Hosting just connected to FiberLink's network backbone."

---

### 2. GreenLeaf Data Centers (San Jose)
**Recent News:** GreenLeaf Data secured new debt financing in 2025.
**Contact Hook:** Tom Wilson, VP of Data Center Operations.
**Academic Connection:** None found.
**Cooling Angle:** GreenLeaf Data lowered PUE to 1.3.
**Unique Detail:** Energy efficiency certifications.
**Suggested Opening Line:** "Tom, I watched the summary of your industry conference panel."

---
"""

SAMPLE_FOLLOWUPS = """# Example Outreach — Follow-Up Email Sequences

---

### #1 — Acme Hosting — Alice Thompson
**Original subject:** Cooling in a converted building?

**Follow-Up #1 (Day 3-4):**
Subject: Re: Cooling in a converted building?

Hi Alice, just bumping this. Better follow-up from followups file.

**Follow-Up #2 (Day 7-8):**
Subject: Re: Cooling in a converted building?

Hi Alice, last note from me. Better second follow-up.

---

### #10 — Summit Mechanical / Legence — [FIND ON LINKEDIN]

**[HOLD — FIND CONTACT FIRST]**

---

### #13 — Metro Engineering (merged with #48) — Carlos Rivera

**[HOLD — DROPPED, merged with #48. Send #48 instead.]**

---
"""

SAMPLE_VALIDATED = """# Example Industry Contacts — Validated Email List

---

## TIER 1 -- Small/Mid Companies

| # | Company | Contact | Title | Email | Confidence | Method |
|---|---------|---------|-------|-------|------------|--------|
| 1 | Acme Hosting | Alice Thompson | CEO | athompson@acmehosting.com | MEDIUM | PATTERN |
| 2 | Acme Hosting | Mark Davis | CTO | mdavis@acmehosting.com | MEDIUM | PATTERN |
| 3 | GreenLeaf Data | Tom Wilson | VP DC Ops & Engineering | twilson@greenleafdata.com | MEDIUM | PATTERN |

---

## TIER 2 -- High Priority

| # | Company | Contact | Title | Email | Confidence | Method |
|---|---------|---------|-------|-------|------------|--------|
| 16 | Neptune Hosting | David Chen | CEO | dchen@neptunehosting.com | HIGH | PATTERN |

---
"""


@pytest.fixture
def sample_hooks_file(tmp_path):
    p = tmp_path / "test_hooks.md"
    p.write_text(SAMPLE_HOOKS, encoding='utf-8')
    return str(p)


@pytest.fixture
def sample_followups_file(tmp_path):
    p = tmp_path / "test_followups.md"
    p.write_text(SAMPLE_FOLLOWUPS, encoding='utf-8')
    return str(p)


@pytest.fixture
def sample_validated_file(tmp_path):
    p = tmp_path / "test_validated.md"
    p.write_text(SAMPLE_VALIDATED, encoding='utf-8')
    return str(p)


class TestParsePersonalizationHooks:
    """Tests for parse_personalization_hooks()."""

    def test_parses_hooks(self, sample_hooks_file):
        hooks = parse_personalization_hooks(sample_hooks_file)
        assert len(hooks) >= 2
        # Acme Hosting should be findable by normalized name
        oc = hooks.get('acme hosting') or hooks.get(_normalize_company('Acme Hosting'))
        assert oc is not None
        assert 'FiberLink' in oc['recent_news']
        assert 'Alice Thompson' in oc['contact_hook']
        assert oc['cooling_angle'] != ''

    def test_opening_line_unquoted(self, sample_hooks_file):
        hooks = parse_personalization_hooks(sample_hooks_file)
        oc = hooks.get('acme hosting') or hooks.get(_normalize_company('Acme Hosting'))
        assert oc is not None
        assert not oc['suggested_opening_line'].startswith('"')

    def test_greenleaf_present(self, sample_hooks_file):
        hooks = parse_personalization_hooks(sample_hooks_file)
        ev = hooks.get('greenleaf data centers') or hooks.get(_normalize_company('GreenLeaf Data Centers'))
        assert ev is not None
        assert 'PUE' in ev['cooling_angle']

    @pytest.mark.skipif(
        not HOOKS_FILE_EXISTS,
        reason="Real hooks file not found"
    )
    def test_real_file_count(self):
        hooks = parse_personalization_hooks(HOOKS_MD)
        # Should parse at least 20 companies
        assert len(hooks) >= 20


class TestParseFollowups:
    """Tests for parse_followups()."""

    def test_parses_ready_followup(self, sample_followups_file):
        fus = parse_followups(sample_followups_file)
        assert 1 in fus
        fu = fus[1]
        assert fu['is_hold'] is False
        assert fu['followup1_subject'] == 'Re: Cooling in a converted building?'
        assert 'Better follow-up' in fu['followup1_body']
        assert fu['followup2_subject'] == 'Re: Cooling in a converted building?'
        assert 'Better second follow-up' in fu['followup2_body']

    def test_parses_hold_contact(self, sample_followups_file):
        fus = parse_followups(sample_followups_file)
        assert 10 in fus
        fu = fus[10]
        assert fu['is_hold'] is True
        assert fu['followup1_subject'] == ''
        assert fu['followup1_body'] == ''

    def test_parses_dropped_hold(self, sample_followups_file):
        fus = parse_followups(sample_followups_file)
        assert 13 in fus
        assert fus[13]['is_hold'] is True

    @pytest.mark.skipif(
        not FOLLOWUPS_FILE_EXISTS,
        reason="Real followups file not found"
    )
    def test_real_file_count(self):
        fus = parse_followups(FOLLOWUPS_MD)
        # Should have entries for all 50 contacts
        assert len(fus) >= 40


class TestParseValidatedEmails:
    """Tests for parse_validated_emails()."""

    def test_parses_emails(self, sample_validated_file):
        validated = parse_validated_emails(sample_validated_file)
        assert 'athompson@acmehosting.com' in validated
        v = validated['athompson@acmehosting.com']
        assert v['name'] == 'Alice Thompson'
        assert v['title'] == 'CEO'
        assert v['confidence'] == 'MEDIUM'

    def test_multiple_entries(self, sample_validated_file):
        validated = parse_validated_emails(sample_validated_file)
        assert len(validated) == 4

    def test_high_confidence(self, sample_validated_file):
        validated = parse_validated_emails(sample_validated_file)
        assert validated['dchen@neptunehosting.com']['confidence'] == 'HIGH'

    @pytest.mark.skipif(
        not VALIDATED_FILE_EXISTS,
        reason="Real validated emails file not found"
    )
    def test_real_file_count(self):
        validated = parse_validated_emails(VALIDATED_MD)
        # Should have at least 40 email entries
        assert len(validated) >= 40


class TestCompanyNormalization:
    """Tests for _normalize_company()."""

    def test_aliases(self):
        # With the simplified COMPANY_ALIASES dict, these now pass through as lowercase
        assert _normalize_company('Horizon Networks') == 'horizon networks'
        assert _normalize_company('Summit Mechanical') == 'summit mechanical'
        assert _normalize_company('Metro Engineering') == 'metro engineering'

    def test_passthrough(self):
        assert _normalize_company('Acme Hosting') == 'acme hosting'
        assert _normalize_company('ByteCenter') == 'bytecenter'

    def test_empty(self):
        assert _normalize_company('') == ''
        assert _normalize_company(None) == ''


class TestEnrichWithNewSources:
    """Tests for enrich_contacts() with hooks, followups, and validated data."""

    def test_hooks_merged(self, sample_ready_file, sample_hooks_file):
        contacts = parse_campaign_markdown(sample_ready_file)
        enriched = enrich_contacts(contacts, hooks_filepath=sample_hooks_file)
        c = enriched[0]
        assert c['personalization_hooks'] != ''
        hooks = json.loads(c['personalization_hooks'])
        assert 'FiberLink' in hooks['recent_news']

    def test_followups_replaced(self, sample_ready_file, sample_followups_file):
        contacts = parse_campaign_markdown(sample_ready_file)
        enriched = enrich_contacts(contacts, followups_filepath=sample_followups_file)
        c = enriched[0]
        # Follow-ups should be replaced with followups file content
        assert 'Better follow-up' in c['followup1_body']
        assert 'Better second follow-up' in c['followup2_body']

    def test_validated_updates_confidence(self, sample_ready_file, sample_validated_file):
        contacts = parse_campaign_markdown(sample_ready_file)
        enriched = enrich_contacts(contacts, validated_filepath=sample_validated_file)
        c = enriched[0]
        # Validated data has MEDIUM for athompson@acmehosting.com (same as original)
        assert c['email_confidence'] == 'MEDIUM'

    def test_hold_followups_not_replaced(self, sample_linkedin_file, sample_followups_file):
        contacts = parse_campaign_markdown(sample_linkedin_file)
        enriched = enrich_contacts(contacts, followups_filepath=sample_followups_file)
        c = enriched[0]
        # HOLD contacts should keep original empty follow-ups
        assert c['followup1_subject'] == ''
        assert c['followup1_body'] == ''


# ===========================================================================
# JSON IMPORT API TESTS
# ===========================================================================


class TestImportJsonEndpoint:
    """Tests for POST /api/contacts/import-json."""

    def _make_payload(self, num_contacts=2):
        contacts = []
        for i in range(1, num_contacts + 1):
            contacts.append({
                'external_id': str(i),
                'name': f'Contact {i}',
                'company': f'Company {i}',
                'email': f'contact{i}@company{i}.com',
                'email_confidence': 'HIGH',
                'wave': 1,
                'personalization_hooks': json.dumps({'recent_news': f'News {i}'}),
                'emails': [
                    {'email_type': 'initial', 'subject': f'Subject {i}', 'body': f'Body {i}'},
                    {'email_type': 'followup1', 'subject': f'FU1 {i}', 'body': f'FU1 body {i}'},
                    {'email_type': 'followup2', 'subject': f'FU2 {i}', 'body': f'FU2 body {i}'},
                ],
            })
        return {
            'campaign': {'name': 'Test Campaign', 'description': 'Test'},
            'contacts': contacts,
        }

    def test_creates_records(self, db, client):
        payload = self._make_payload(2)
        resp = client.post('/api/contacts/import-json',
                           json=payload,
                           content_type='application/json')
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['contacts_created'] == 2
        assert data['emails_created'] == 6
        assert data['skipped'] == 0
        assert Campaign.query.count() == 1
        assert Contact.query.count() == 2
        assert Email.query.count() == 6

    def test_idempotent(self, db, client):
        payload = self._make_payload(1)
        resp1 = client.post('/api/contacts/import-json', json=payload)
        assert resp1.status_code == 201
        campaign_id = resp1.get_json()['campaign_id']

        # Import again with same campaign
        payload['campaign_id'] = campaign_id
        resp2 = client.post('/api/contacts/import-json', json=payload)
        assert resp2.status_code == 201
        data = resp2.get_json()
        assert data['contacts_created'] == 0
        assert data['skipped'] == 1

    def test_personalization_hooks_stored(self, db, client):
        payload = self._make_payload(1)
        client.post('/api/contacts/import-json', json=payload)
        contact = Contact.query.first()
        assert contact.personalization_hooks is not None
        hooks = json.loads(contact.personalization_hooks)
        assert hooks['recent_news'] == 'News 1'

    def test_empty_payload(self, db, client):
        resp = client.post('/api/contacts/import-json',
                           json={'contacts': []})
        assert resp.status_code == 400

    def test_no_data(self, db, client):
        resp = client.post('/api/contacts/import-json',
                           content_type='application/json')
        assert resp.status_code == 400

    def test_uses_existing_campaign(self, db, client):
        # Create a campaign first
        campaign = Campaign(name='Existing', status='draft')
        db.session.add(campaign)
        db.session.commit()

        payload = self._make_payload(1)
        payload['campaign_id'] = campaign.id
        resp = client.post('/api/contacts/import-json', json=payload)
        assert resp.status_code == 201
        assert resp.get_json()['campaign_id'] == campaign.id
        assert Campaign.query.count() == 1


class TestImportSetsPersonalizationHooks:
    """Verify that contact_importer sets personalization_hooks from enriched data."""

    def test_hooks_stored(self, db, sample_ready_file, sample_hooks_file):
        contacts = parse_campaign_markdown(sample_ready_file)
        enriched = enrich_contacts(contacts, hooks_filepath=sample_hooks_file)
        import_contacts(enriched)
        c = Contact.query.first()
        assert c.personalization_hooks is not None
        hooks = json.loads(c.personalization_hooks)
        assert 'recent_news' in hooks
