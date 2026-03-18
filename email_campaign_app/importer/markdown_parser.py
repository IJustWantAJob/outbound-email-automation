"""Markdown campaign file parser.

Parses the structured markdown campaign files (campaign.md,
hooks.md, followups.md, validated_emails.md)
to extract contacts, email templates, personalization hooks, and
follow-up sequences into database records.
"""

import json
import re


def parse_campaign_markdown(filepath):
    """Parse a campaign markdown file and return a list of contact dicts.

    Each dict contains:
        external_id (int): The # number from the header
        company (str): Company name
        wave (int): Wave number 1-5
        email (str): Email address (empty string for NEEDS LINKEDIN)
        status_raw (str): The **Status:** field value
        email_confidence (str): HIGH, MEDIUM, or empty string
        response_likelihood (int): 1-5, or 0 for TBD
        needs_linkedin (bool): True if NEEDS LINKEDIN in header
        is_dropped (bool): True if DROPPED in header
        initial_subject (str): Subject line of the initial email
        initial_body (str): Full body text of the initial email
        followup1_subject (str): Subject of follow-up 1 (empty for placeholders)
        followup1_body (str): Body of follow-up 1 (empty for placeholders)
        followup2_subject (str): Subject of follow-up 2 (empty for placeholders)
        followup2_body (str): Body of follow-up 2 (empty for placeholders)

    Args:
        filepath: Path to campaign markdown file

    Returns:
        List of dicts, one per contact.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Extract only Section 2 (all 50 emails)
    section2_match = re.search(
        r'## SECTION 2: ALL 50 EMAILS \+ FOLLOW-UPS.*?\n---\n',
        content,
        re.DOTALL,
    )
    if not section2_match:
        raise ValueError("Could not find Section 2 in the markdown file")

    # Get everything from Section 2 header to Section 3
    section2_start = section2_match.end()
    section3_match = re.search(
        r'\n## SECTION 3:',
        content[section2_start:],
    )
    if section3_match:
        section2_text = content[section2_start:section2_start + section3_match.start()]
    else:
        section2_text = content[section2_start:]

    # Split on contact headers: ### #N -- ...
    # We split on the pattern but keep the delimiter
    sections = re.split(r'(?=^### #\d+\s)', section2_text, flags=re.MULTILINE)
    sections = [s.strip() for s in sections if s.strip()]

    contacts = []
    for section in sections:
        parsed = _parse_contact_section(section)
        if parsed:
            contacts.append(parsed)

    return contacts


def _parse_contact_section(text):
    """Parse a single contact section and return a dict."""
    # Extract header line: ### #N -- Company -- Wave X (optional flags)
    header_match = re.match(
        r'### #(\d+)\s+--\s+(.+?)(?:\s+--\s+(.+))?$',
        text,
        re.MULTILINE,
    )
    if not header_match:
        return None

    external_id = int(header_match.group(1))
    company = header_match.group(2).strip()
    header_rest = header_match.group(3) or ''

    # Check if DROPPED
    is_dropped = 'DROPPED' in header_rest.upper()

    # Check if NEEDS LINKEDIN
    needs_linkedin = 'NEEDS LINKEDIN' in header_rest.upper()

    # Extract wave number
    wave_match = re.search(r'Wave\s+(\d+)', header_rest, re.IGNORECASE)
    wave = int(wave_match.group(1)) if wave_match else 0

    # For DROPPED contacts, return minimal data
    if is_dropped:
        return {
            'external_id': external_id,
            'company': company,
            'wave': wave,
            'email': '',
            'status_raw': 'DROPPED',
            'email_confidence': '',
            'response_likelihood': 0,
            'needs_linkedin': needs_linkedin,
            'is_dropped': True,
            'initial_subject': '',
            'initial_body': '',
            'followup1_subject': '',
            'followup1_body': '',
            'followup2_subject': '',
            'followup2_body': '',
        }

    # Extract email (To: field)
    to_match = re.search(r'\*\*To:\*\*\s*(.+)', text)
    email = ''
    if to_match:
        to_value = to_match.group(1).strip()
        # Check if it's a real email or a placeholder
        email_addr_match = re.search(
            r'[\w.+-]+@[\w.-]+\.\w+', to_value
        )
        if email_addr_match:
            email = email_addr_match.group(0)

    # Extract status
    status_match = re.search(r'\*\*Status:\*\*\s*(.+)', text)
    status_raw = status_match.group(1).strip() if status_match else ''

    # Extract email confidence
    confidence_match = re.search(r'\*\*Email Confidence:\*\*\s*(.+)', text)
    email_confidence = ''
    if confidence_match:
        conf_value = confidence_match.group(1).strip()
        # Extract just HIGH, MEDIUM, or LOW
        conf_level_match = re.match(r'(HIGH|MEDIUM|LOW)', conf_value, re.IGNORECASE)
        if conf_level_match:
            email_confidence = conf_level_match.group(1).upper()
        elif 'N/A' in conf_value:
            email_confidence = ''

    # Extract response likelihood
    likelihood_match = re.search(r'\*\*Response Likelihood:\*\*\s*(.+)', text)
    response_likelihood = 0
    if likelihood_match:
        lk_value = likelihood_match.group(1).strip()
        num_match = re.match(r'(\d+)/5', lk_value)
        if num_match:
            response_likelihood = int(num_match.group(1))

    # Extract initial email
    initial_subject, initial_body = _extract_email_section(
        text, r'\*\*Initial Email:\*\*'
    )

    # Extract follow-up #1
    followup1_subject, followup1_body = _extract_followup_section(
        text, r'\*\*Follow-Up #1\s*\(Day \d+-?\d*\):\*\*'
    )

    # Extract follow-up #2
    followup2_subject, followup2_body = _extract_followup_section(
        text, r'\*\*Follow-Up #2\s*\(Day \d+-?\d*\):\*\*'
    )

    return {
        'external_id': external_id,
        'company': company,
        'wave': wave,
        'email': email,
        'status_raw': status_raw,
        'email_confidence': email_confidence,
        'response_likelihood': response_likelihood,
        'needs_linkedin': needs_linkedin,
        'is_dropped': is_dropped,
        'initial_subject': initial_subject,
        'initial_body': initial_body,
        'followup1_subject': followup1_subject,
        'followup1_body': followup1_body,
        'followup2_subject': followup2_subject,
        'followup2_body': followup2_body,
    }


def _extract_email_section(text, header_pattern):
    """Extract subject and body from an email section (Initial Email).

    Returns (subject, body) tuple.
    """
    match = re.search(header_pattern, text)
    if not match:
        return '', ''

    # Get everything after the header until the next section marker
    after_header = text[match.end():]

    # The next section is a follow-up or end of block
    end_match = re.search(
        r'\*\*Follow-Up #\d',
        after_header,
    )
    if end_match:
        section_text = after_header[:end_match.start()]
    else:
        section_text = after_header

    return _parse_subject_and_body(section_text)


def _extract_followup_section(text, header_pattern):
    """Extract subject and body from a follow-up section.

    Returns (subject, body) tuple. Returns ('', '') for placeholder follow-ups.
    """
    match = re.search(header_pattern, text)
    if not match:
        return '', ''

    after_header = text[match.end():]

    # Find the end of this follow-up section
    # It ends at the next follow-up, or at --- separator, or end of text
    end_match = re.search(
        r'\*\*Follow-Up #\d|^---$',
        after_header,
        re.MULTILINE,
    )
    if end_match:
        section_text = after_header[:end_match.start()]
    else:
        # Strip trailing --- separators
        section_text = re.sub(r'\n---\s*$', '', after_header)

    # Check if this is a placeholder follow-up
    stripped = section_text.strip()
    if _is_placeholder_followup(stripped):
        return '', ''

    return _parse_subject_and_body(section_text)


def _is_placeholder_followup(text):
    """Check if follow-up text is a placeholder (not yet written)."""
    placeholder_patterns = [
        r'^\[Write after finding contact',
        r'^\[Write after',
        r'^Write after finding',
    ]
    for pattern in placeholder_patterns:
        if re.match(pattern, text, re.IGNORECASE):
            return True
    return False


def _parse_subject_and_body(text):
    """Parse subject line and body from a section of email text.

    Returns (subject, body) tuple.
    """
    # Find the Subject: line
    subject_match = re.search(r'^Subject:\s*(.+)$', text, re.MULTILINE)
    if not subject_match:
        return '', ''

    subject = subject_match.group(1).strip()

    # Body is everything after the Subject: line
    body_start = subject_match.end()
    body = text[body_start:].strip()

    # Clean up the body - remove trailing whitespace on each line
    body_lines = [line.rstrip() for line in body.split('\n')]
    body = '\n'.join(body_lines).strip()

    return subject, body


def parse_enrichment_contacts(filepath):
    """Parse contacts.md to extract name-title mappings by company.

    Returns a dict keyed by (company_name_lower, contact_name_lower) -> {
        'name': str,
        'title': str,
    }
    Also returns a secondary dict keyed by email_lower -> same dict.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    name_title_by_company = {}
    name_title_by_email = {}

    # Find all contact entries
    # Pattern: ### N. Company Name (Location) or ### Nb. Company Name -- Alternate
    sections = re.split(r'(?=^### \d)', content, flags=re.MULTILINE)

    for section in sections:
        if not section.strip():
            continue

        # Extract contact name
        name_match = re.search(
            r'\*\*Contact:\*\*\s*(.+)', section
        )
        if not name_match:
            continue
        name = name_match.group(1).strip()
        # Skip generic contacts
        if name.lower().startswith('general'):
            continue

        # Extract title
        title_match = re.search(r'\*\*Title:\*\*\s*(.+)', section)
        title = title_match.group(1).strip() if title_match else ''

        # Extract company from header
        header_match = re.match(
            r'### \d+b?\.\s+(.+?)(?:\s*\(|$|\n)',
            section,
        )
        company = header_match.group(1).strip() if header_match else ''
        # Clean company name - remove "-- Alternate"
        company = re.sub(r'\s*--\s*Alternate.*$', '', company)

        entry = {'name': name, 'title': title}

        if company:
            key = (company.lower(), name.lower())
            name_title_by_company[key] = entry

        # Also try to extract email from the section
        email_match = re.search(
            r'\*\*Email:\*\*\s*([\w.+-]+@[\w.-]+\.\w+)',
            section,
        )
        if email_match:
            email_key = email_match.group(1).lower()
            name_title_by_email[email_key] = entry

    return name_title_by_company, name_title_by_email


def parse_enrichment_emails_v2(filepath):
    """Parse emails_v2.md Quick Reference Table for ask types and names.

    Returns a dict keyed by external_id (int) -> {
        'name': str,
        'ask_type': str,
    }
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    result = {}

    # Parse the Quick Reference Table
    # Format: | # | Company | Contact | Email | Ask Type | Status |
    table_match = re.search(
        r'## Quick Reference Table\n\n\|.*?\n\|[-| ]+\n((?:\|.*\n)*)',
        content,
    )
    if not table_match:
        return result

    table_body = table_match.group(1)
    for line in table_body.strip().split('\n'):
        cols = [c.strip() for c in line.split('|')]
        # cols[0] is empty (before first |), cols[-1] is empty (after last |)
        if len(cols) < 7:
            continue
        try:
            ext_id = int(cols[1].strip())
        except (ValueError, IndexError):
            continue

        contact_name = cols[3].strip()
        ask_type = cols[5].strip()

        # Clean contact name - skip placeholders
        if contact_name.startswith('[FIND') or contact_name.startswith('['):
            contact_name = ''

        result[ext_id] = {
            'name': contact_name,
            'ask_type': ask_type,
        }

    return result


# ---------------------------------------------------------------------------
# Company name normalization — handles mismatches between source files
# ---------------------------------------------------------------------------

# Add aliases for companies whose name varies between files.
# Example: {'short name': 'Full Name As In Master File'}
COMPANY_ALIASES = {}


def _normalize_company(name):
    """Normalize a company name for matching across different source files."""
    if not name:
        return ''
    lower = name.lower().strip()
    if COMPANY_ALIASES:
        return COMPANY_ALIASES.get(lower, lower)
    return lower


def parse_personalization_hooks(filepath):
    """Parse personalization hooks markdown and return a dict keyed by normalized company name.

    Each value is a dict with:
        recent_news, contact_hook, academic_connection,
        cooling_angle, unique_detail, suggested_opening_line

    Args:
        filepath: Path to hooks markdown file

    Returns:
        Dict mapping normalized company name (lowercase) -> hooks dict.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    result = {}

    # Split on company headers: ### N. Company Name (Location)
    sections = re.split(r'(?=^### \d+\.)', content, flags=re.MULTILINE)

    for section in sections:
        section = section.strip()
        if not section:
            continue

        # Extract company name from header
        header_match = re.match(
            r'### \d+\.\s+(.+?)(?:\s*\(|$|\n)',
            section,
        )
        if not header_match:
            continue

        company_raw = header_match.group(1).strip()
        company_key = _normalize_company(company_raw)

        hooks = {}
        field_patterns = [
            ('recent_news', r'\*\*Recent News:\*\*\s*(.+?)(?=\n\*\*|\Z)'),
            ('contact_hook', r'\*\*Contact Hook:\*\*\s*(.+?)(?=\n\*\*|\Z)'),
            ('academic_connection', r'\*\*Academic Connection:\*\*\s*(.+?)(?=\n\*\*|\Z)'),
            ('cooling_angle', r'\*\*Cooling Angle:\*\*\s*(.+?)(?=\n\*\*|\Z)'),
            ('unique_detail', r'\*\*Unique Detail:\*\*\s*(.+?)(?=\n\*\*|\Z)'),
            ('suggested_opening_line', r'\*\*Suggested Opening Line:\*\*\s*(.+?)(?=\n---|\Z)'),
        ]

        for field_name, pattern in field_patterns:
            match = re.search(pattern, section, re.DOTALL)
            if match:
                hooks[field_name] = match.group(1).strip()
            else:
                hooks[field_name] = ''

        # Strip surrounding quotes from suggested opening line
        opening = hooks.get('suggested_opening_line', '')
        if opening.startswith('"') and opening.endswith('"'):
            opening = opening[1:-1]
        hooks['suggested_opening_line'] = opening

        result[company_key] = hooks

        # Also store under the raw company name (lowercased) if different
        raw_lower = company_raw.lower().strip()
        if raw_lower != company_key:
            result[raw_lower] = hooks

    return result


def parse_followups(filepath):
    """Parse followups markdown and return a dict keyed by external_id (int).

    Each value is a dict with:
        followup1_subject, followup1_body, followup2_subject, followup2_body,
        is_hold (bool)

    HOLD contacts (needing LinkedIn research or dropped/merged) get is_hold=True
    and empty follow-up fields.

    Args:
        filepath: Path to followups markdown file

    Returns:
        Dict mapping external_id (int) -> followup dict.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    result = {}

    # Split on contact headers: ### #N — Company — Contact
    sections = re.split(r'(?=^### #\d+\s)', content, flags=re.MULTILINE)

    for section in sections:
        section = section.strip()
        if not section:
            continue

        # Extract external_id
        id_match = re.match(r'### #(\d+)\s', section)
        if not id_match:
            continue
        ext_id = int(id_match.group(1))

        # Check if this is a HOLD contact
        is_hold = bool(re.search(r'\[HOLD', section))

        if is_hold:
            result[ext_id] = {
                'followup1_subject': '',
                'followup1_body': '',
                'followup2_subject': '',
                'followup2_body': '',
                'is_hold': True,
            }
            continue

        # Extract Follow-Up #1
        fu1_subject, fu1_body = '', ''
        fu1_match = re.search(
            r'\*\*Follow-Up #1\s*\(Day \d+-?\d*\):\*\*\s*\n(.*?)(?=\*\*Follow-Up #2|\Z)',
            section,
            re.DOTALL,
        )
        if fu1_match:
            fu1_text = fu1_match.group(1)
            fu1_subject, fu1_body = _parse_subject_and_body(fu1_text)

        # Extract Follow-Up #2
        fu2_subject, fu2_body = '', ''
        fu2_match = re.search(
            r'\*\*Follow-Up #2\s*\(Day \d+-?\d*\):\*\*\s*\n(.*?)(?=\n---|\Z)',
            section,
            re.DOTALL,
        )
        if fu2_match:
            fu2_text = fu2_match.group(1)
            fu2_subject, fu2_body = _parse_subject_and_body(fu2_text)

        result[ext_id] = {
            'followup1_subject': fu1_subject,
            'followup1_body': fu1_body,
            'followup2_subject': fu2_subject,
            'followup2_body': fu2_body,
            'is_hold': False,
        }

    return result


def parse_validated_emails(filepath):
    """Parse validated emails markdown and return a dict keyed by email address (lowercase).

    Each value is a dict with:
        name, title, confidence, method

    The file uses different numbering so we match by email address.

    Args:
        filepath: Path to validated emails markdown file

    Returns:
        Dict mapping email_lower -> validation dict.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    result = {}

    # Find all table rows: | # | Company | Contact | Title | Email | Confidence | Method |
    # Tables appear in multiple tier sections
    row_pattern = re.compile(
        r'^\|\s*(\d+)\s*\|'     # # column
        r'\s*(.+?)\s*\|'        # Company
        r'\s*(.+?)\s*\|'        # Contact
        r'\s*(.+?)\s*\|'        # Title
        r'\s*(.+?)\s*\|'        # Email
        r'\s*(.+?)\s*\|'        # Confidence
        r'\s*(.+?)\s*\|',       # Method
        re.MULTILINE,
    )

    for match in row_pattern.finditer(content):
        email_raw = match.group(5).strip()
        # Skip non-email entries (contact forms, placeholders)
        if not re.match(r'[\w.+-]+@[\w.-]+\.\w+', email_raw):
            continue

        email_lower = email_raw.lower()
        confidence = match.group(6).strip().upper()
        # Normalize confidence to HIGH/MEDIUM/LOW
        if confidence not in ('HIGH', 'MEDIUM', 'LOW'):
            confidence = ''

        result[email_lower] = {
            'name': match.group(3).strip(),
            'title': match.group(4).strip(),
            'confidence': confidence,
            'method': match.group(7).strip(),
        }

    return result


# ---------------------------------------------------------------------------
# Generic campaign parser (works with any campaign segment)
# ---------------------------------------------------------------------------

def parse_generic_campaign(filepath):
    """Parse any campaign markdown file using the standard format.

    Handles the format from CAMPAIGN_PLAYBOOK.md:
        ### #N -- Company -- Wave N
        - **Contact:** Name, Title
        - **Email:** person@company.com (HIGH/MEDIUM/LOW)
        - **Status:** HIGH confidence, Response likelihood: N/5
        **Subject:** ...
        **Body:** ...
        **Follow-up 1 Subject:** ...
        **Follow-up 1:** ...
        **Follow-up 2 Subject:** ...
        **Follow-up 2:** ...

    Returns list of dicts in the same format as parse_campaign_markdown().
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Find Section 2 with flexible header matching
    section2_match = re.search(
        r'^## SECTION 2:.*?EMAILS.*?\n---\n',
        content,
        re.DOTALL | re.MULTILINE,
    )
    if not section2_match:
        # Try without --- separator
        section2_match = re.search(
            r'^## SECTION 2:.*?EMAILS.*?\n',
            content,
            re.MULTILINE,
        )
    if not section2_match:
        raise ValueError(
            f"Could not find Section 2 (emails) in {filepath}. "
            "Expected '## SECTION 2: ... EMAILS ...'"
        )

    section2_start = section2_match.end()

    # Find end of Section 2 (Section 3, Section 4, or EOF)
    section_end_match = re.search(
        r'\n## SECTION [3-9]:',
        content[section2_start:],
    )
    if section_end_match:
        section2_text = content[section2_start:section2_start + section_end_match.start()]
    else:
        section2_text = content[section2_start:]

    # Split on contact headers: ### #N -- ...
    sections = re.split(r'(?=^### #\d+\s)', section2_text, flags=re.MULTILINE)
    sections = [s.strip() for s in sections if s.strip()]

    contacts = []
    for section in sections:
        parsed = _parse_generic_contact(section)
        if parsed:
            contacts.append(parsed)

    return contacts


def _parse_generic_contact(text):
    """Parse a single contact section in the generic format."""
    # Header: ### #N -- Company -- Wave X [optional flags]
    header_match = re.match(
        r'### #(\d+)\s+--\s+(.+?)(?:\s+--\s+(.+))?$',
        text,
        re.MULTILINE,
    )
    if not header_match:
        return None

    external_id = int(header_match.group(1))
    company = header_match.group(2).strip()
    header_rest = header_match.group(3) or ''

    is_dropped = 'DROPPED' in header_rest.upper()
    needs_linkedin = 'NEEDS LINKEDIN' in header_rest.upper()

    wave_match = re.search(r'Wave\s+(\d+)', header_rest, re.IGNORECASE)
    wave = int(wave_match.group(1)) if wave_match else 0

    if is_dropped:
        return {
            'external_id': external_id, 'company': company, 'wave': wave,
            'email': '', 'name': '', 'title': '',
            'status_raw': 'DROPPED', 'email_confidence': '',
            'response_likelihood': 0, 'needs_linkedin': needs_linkedin,
            'is_dropped': True,
            'initial_subject': '', 'initial_body': '',
            'followup1_subject': '', 'followup1_body': '',
            'followup2_subject': '', 'followup2_body': '',
        }

    # Extract contact name and title from **Contact:** line
    name = ''
    title = ''
    contact_match = re.search(r'\*\*Contact:\*\*\s*(.+)', text)
    if contact_match:
        contact_str = contact_match.group(1).strip()
        # Format: "Name, Title" or just "Name"
        if ', ' in contact_str:
            parts = contact_str.split(', ', 1)
            name = parts[0].strip()
            title = parts[1].strip()
        else:
            name = contact_str

    # Extract email from **Email:** line (format: addr@example.com (CONFIDENCE))
    email = ''
    email_confidence = ''
    email_line_match = re.search(r'\*\*Email:\*\*\s*(.+)', text)
    if email_line_match:
        email_str = email_line_match.group(1).strip()
        addr_match = re.search(r'([\w.+-]+@[\w.-]+\.\w+)', email_str)
        if addr_match:
            email = addr_match.group(1).lower()
        conf_match = re.search(r'\((HIGH|MEDIUM|LOW)\)', email_str, re.IGNORECASE)
        if conf_match:
            email_confidence = conf_match.group(1).upper()

    # Also check **To:** for DC-style contacts
    if not email:
        to_match = re.search(r'\*\*To:\*\*\s*(.+)', text)
        if to_match:
            addr_match = re.search(r'([\w.+-]+@[\w.-]+\.\w+)', to_match.group(1))
            if addr_match:
                email = addr_match.group(1).lower()

    # Extract status
    status_match = re.search(r'\*\*Status:\*\*\s*(.+)', text)
    status_raw = status_match.group(1).strip() if status_match else ''

    # Extract confidence from status if not from email line
    if not email_confidence and status_raw:
        conf_match = re.match(r'(HIGH|MEDIUM|LOW)', status_raw, re.IGNORECASE)
        if conf_match:
            email_confidence = conf_match.group(1).upper()

    # Extract response likelihood
    response_likelihood = 0
    lk_match = re.search(r'Response likelihood:\s*(\d)/5', text, re.IGNORECASE)
    if lk_match:
        response_likelihood = int(lk_match.group(1))

    # Extract initial email: **Subject:** and **Body:**
    initial_subject = ''
    initial_body = ''
    subj_match = re.search(r'^\*\*Subject:\*\*\s*(.+)$', text, re.MULTILINE)
    if subj_match:
        initial_subject = subj_match.group(1).strip()

    body_match = re.search(r'^\*\*Body:\*\*\s*\n', text, re.MULTILINE)
    if body_match:
        body_start = body_match.end()
        # Body ends at follow-up marker or --- separator or end
        body_end_match = re.search(
            r'^\*\*Follow-up \d|^---$',
            text[body_start:],
            re.MULTILINE,
        )
        if body_end_match:
            initial_body = text[body_start:body_start + body_end_match.start()].strip()
        else:
            initial_body = text[body_start:].strip()

    # Also handle DC-style **Initial Email:** format
    if not initial_subject and not initial_body:
        ie_match = re.search(r'\*\*Initial Email:\*\*', text)
        if ie_match:
            after = text[ie_match.end():]
            end_match = re.search(r'\*\*Follow-Up #\d', after)
            section_text = after[:end_match.start()] if end_match else after
            initial_subject, initial_body = _parse_subject_and_body(section_text)

    # Extract follow-up 1
    followup1_subject, followup1_body = _extract_generic_followup(text, 1)
    # Extract follow-up 2
    followup2_subject, followup2_body = _extract_generic_followup(text, 2)

    # Fall back to name from greeting if not found
    if not name and initial_body:
        greeting_match = re.match(r'^Hi\s+(.+?)[\s,]', initial_body)
        if greeting_match:
            first_name = greeting_match.group(1).strip()
            if first_name not in ('[First Name]', '[Name]'):
                name = first_name

    return {
        'external_id': external_id, 'company': company, 'wave': wave,
        'email': email, 'name': name, 'title': title,
        'status_raw': status_raw, 'email_confidence': email_confidence,
        'response_likelihood': response_likelihood,
        'needs_linkedin': needs_linkedin, 'is_dropped': False,
        'initial_subject': initial_subject, 'initial_body': initial_body,
        'followup1_subject': followup1_subject, 'followup1_body': followup1_body,
        'followup2_subject': followup2_subject, 'followup2_body': followup2_body,
    }


def _extract_generic_followup(text, num):
    """Extract follow-up N from generic format.

    Handles both:
      **Follow-up N Subject:** ...\\n**Follow-up N:**\\n...
      **Follow-Up #N (Day X-Y):**\\n...  (DC format)
    """
    # Try generic format first: **Follow-up N Subject:** and **Follow-up N:**
    subj_pattern = rf'^\*\*Follow-up {num} Subject:\*\*\s*(.+)$'
    subj_match = re.search(subj_pattern, text, re.MULTILINE | re.IGNORECASE)

    body_pattern = rf'^\*\*Follow-up {num}:\*\*\s*\n'
    body_match = re.search(body_pattern, text, re.MULTILINE | re.IGNORECASE)

    subject = subj_match.group(1).strip() if subj_match else ''
    body = ''

    if body_match:
        body_start = body_match.end()
        # Body ends at next follow-up marker, --- separator, or end
        next_num = num + 1
        end_patterns = [
            rf'^\*\*Follow-up {next_num}',
            r'^---$',
            r'^\*\*Follow-Up #',
        ]
        end_match = re.search(
            '|'.join(end_patterns),
            text[body_start:],
            re.MULTILINE | re.IGNORECASE,
        )
        if end_match:
            body = text[body_start:body_start + end_match.start()].strip()
        else:
            body = text[body_start:].strip()
            # Strip trailing --- separator
            body = re.sub(r'\n---\s*$', '', body).strip()

    # If no generic format found, try DC format
    if not subject and not body:
        dc_pattern = rf'\*\*Follow-Up #{num}\s*\(Day \d+-?\d*\):\*\*'
        dc_match = re.search(dc_pattern, text)
        if dc_match:
            after = text[dc_match.end():]
            next_dc = rf'\*\*Follow-Up #{num + 1}'
            end_match = re.search(
                rf'{next_dc}|^---$',
                after,
                re.MULTILINE,
            )
            section_text = after[:end_match.start()] if end_match else after
            section_text = re.sub(r'\n---\s*$', '', section_text)
            if not _is_placeholder_followup(section_text.strip()):
                subject, body = _parse_subject_and_body(section_text)

    return subject, body


def enrich_contacts(parsed_contacts, contacts_filepath=None, emails_v2_filepath=None,
                     hooks_filepath=None, followups_filepath=None,
                     validated_filepath=None):
    """Enrich parsed contacts with name, title, ask_type, personalization hooks,
    better follow-ups, and validated email confidence from supplementary files.

    Args:
        parsed_contacts: List of dicts from parse_campaign_markdown()
        contacts_filepath: Path to contacts markdown file (optional)
        emails_v2_filepath: Path to emails_v2 markdown file (optional)
        hooks_filepath: Path to personalization hooks markdown file (optional)
        followups_filepath: Path to followups markdown file (optional)
        validated_filepath: Path to validated emails markdown file (optional)

    Returns:
        The same list with added keys: 'name', 'title', 'ask_type',
        'personalization_hooks' (JSON string)
    """
    # Load enrichment data
    by_company = {}
    by_email = {}
    if contacts_filepath:
        try:
            by_company, by_email = parse_enrichment_contacts(contacts_filepath)
        except (FileNotFoundError, OSError):
            pass

    v2_data = {}
    if emails_v2_filepath:
        try:
            v2_data = parse_enrichment_emails_v2(emails_v2_filepath)
        except (FileNotFoundError, OSError):
            pass

    hooks_data = {}
    if hooks_filepath:
        try:
            hooks_data = parse_personalization_hooks(hooks_filepath)
        except (FileNotFoundError, OSError):
            pass

    followups_data = {}
    if followups_filepath:
        try:
            followups_data = parse_followups(followups_filepath)
        except (FileNotFoundError, OSError):
            pass

    validated_data = {}
    if validated_filepath:
        try:
            validated_data = parse_validated_emails(validated_filepath)
        except (FileNotFoundError, OSError):
            pass

    for contact in parsed_contacts:
        ext_id = contact['external_id']
        email = contact.get('email', '')

        # Start with defaults
        name = ''
        title = ''
        ask_type = ''

        # Try to get name from v2 data (most reliable, matched by #)
        if ext_id in v2_data:
            v2 = v2_data[ext_id]
            if v2['name']:
                name = v2['name']
            ask_type = v2.get('ask_type', '')

        # Try to get name from email greeting in initial body
        if not name and contact.get('initial_body'):
            greeting_match = re.match(
                r'^Hi\s+(.+?)[\s,]',
                contact['initial_body'],
            )
            if greeting_match:
                first_name = greeting_match.group(1).strip()
                if first_name != '[First Name]':
                    name = first_name

        # Try to get title from contacts file by email
        if email and email.lower() in by_email:
            enrichment = by_email[email.lower()]
            if not name:
                name = enrichment['name']
            if not title:
                title = enrichment['title']

        # --- Merge validated email data (by email address) ---
        if email and email.lower() in validated_data:
            vd = validated_data[email.lower()]
            # Update confidence if validated data has it
            if vd.get('confidence'):
                contact['email_confidence'] = vd['confidence']
            # Fill in title if missing
            if not title and vd.get('title'):
                title = vd['title']
            # Fill in name if missing
            if not name and vd.get('name'):
                name = vd['name']

        # --- Merge personalization hooks (by company name) ---
        company_key = _normalize_company(contact.get('company', ''))
        hooks = hooks_data.get(company_key, None)
        if hooks:
            contact['personalization_hooks'] = json.dumps(hooks)
        else:
            contact['personalization_hooks'] = ''

        # --- Replace follow-ups with followups file content when available ---
        if ext_id in followups_data:
            fu = followups_data[ext_id]
            if not fu.get('is_hold', False):
                # Only replace if the followups file has actual content
                if fu['followup1_subject']:
                    contact['followup1_subject'] = fu['followup1_subject']
                    contact['followup1_body'] = fu['followup1_body']
                if fu['followup2_subject']:
                    contact['followup2_subject'] = fu['followup2_subject']
                    contact['followup2_body'] = fu['followup2_body']

        contact['name'] = name
        contact['title'] = title
        contact['ask_type'] = ask_type

    return parsed_contacts
