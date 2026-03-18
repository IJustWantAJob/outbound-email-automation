"""Render nightly prompt templates by substituting sender profile data.

Uses simple string replacement (not Jinja2) because the prompt files
contain markdown code blocks, JSON examples, and curly braces that
would conflict with Jinja2 syntax.
"""

import json
import os


def render_nightly_prompt(profile_dict, template_path=None):
    """Read NIGHTLY_PROMPT.md template and substitute profile fields.

    Args:
        profile_dict: dict from profile_to_dict() or loaded from profile.json
        template_path: path to the template file (default: nightly/NIGHTLY_PROMPT.md)

    Returns:
        Rendered prompt string with all placeholders replaced.
    """
    if template_path is None:
        template_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'nightly', 'NIGHTLY_PROMPT.md',
        )

    with open(template_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Build the sender profile block
    sender_lines = []
    sender_lines.append(f"- Name: {profile_dict.get('sender_name', '')}")
    if profile_dict.get('university'):
        sender_lines.append(f"- School: {profile_dict['university']}")
    if profile_dict.get('sender_background'):
        sender_lines.append(f"- Background: {profile_dict['sender_background']}")
    sender_lines.append(f"- Company: {profile_dict.get('company_name', '')}, {profile_dict.get('sender_title', '')}")
    if profile_dict.get('accelerator'):
        sender_lines.append(f"- Accelerator: {profile_dict['accelerator']}")
    if profile_dict.get('linkedin_url'):
        sender_lines.append(f"- LinkedIn: {profile_dict['linkedin_url']}")
    if profile_dict.get('sender_email'):
        sender_lines.append(f"- Email: {profile_dict['sender_email']}")
    if profile_dict.get('key_metrics'):
        sender_lines.append(f"- Key metrics: {profile_dict['key_metrics']}")
    sender_block = '\n'.join(sender_lines)

    # Build the target segments block
    segments = profile_dict.get('target_segments') or []
    if isinstance(segments, str):
        segments = json.loads(segments)
    segments_lines = []
    for i, seg in enumerate(sorted(segments, key=lambda s: s.get('priority', 99)), 1):
        desc = seg.get('description', '')
        segments_lines.append(f"{i}. **{seg['name']}** -- {desc}")
    segments_block = '\n'.join(segments_lines) if segments_lines else '1. (No segments configured -- add them in Settings > Profile)'

    # Build the pricing block
    pricing = profile_dict.get('pricing_notes', '')
    pricing_block = pricing if pricing else '(Not configured)'

    # Build the campaign paths block — tells Claude exactly where files are
    paths_lines = [
        '### Global files:',
        '- `nightly/NIGHTLY_PROMPT.md` -- Rules and email format',
        '- `nightly/state.json` -- Progress tracker (read/write)',
        '- `nightly/profile.json` -- Sender profile (read only)',
        '- `CAMPAIGN_PLAYBOOK.md` -- Format reference',
        '',
        '### Per-segment campaign files:',
    ]
    for seg in sorted(segments, key=lambda s: s.get('priority', 99)):
        slug = seg['name'].lower().replace(' ', '_').replace('/', '_')
        paths_lines.append(f'')
        paths_lines.append(f'**{seg["name"]}** (priority {seg.get("priority", "?")}):\n')
        paths_lines.append(f'- `campaigns/{slug}/README.md` -- Segment ICP')
        paths_lines.append(f'- `campaigns/{slug}/{slug}_outreach_campaign.md` -- MASTER FILE (parser reads this)')
        paths_lines.append(f'- `campaigns/{slug}/contacts.md` -- Contact research')
        paths_lines.append(f'- `campaigns/{slug}/target_companies.md` -- Company research')
        paths_lines.append(f'- `campaigns/{slug}/nightly_additions_{{DATE}}.md` -- Nightly agent appends here')
    if not segments:
        paths_lines.append('(No segments configured -- add them in Settings > Profile)')
    campaign_paths_block = '\n'.join(paths_lines)

    # Simple replacements
    replacements = {
        '{{COMPANY_NAME}}': profile_dict.get('company_name', ''),
        '{{COMPANY_DESCRIPTION}}': profile_dict.get('company_description', ''),
        '{{INDUSTRY}}': profile_dict.get('industry', ''),
        '{{PRODUCT_DESCRIPTION}}': profile_dict.get('product_description', ''),
        '{{SENDER_PROFILE}}': sender_block,
        '{{TARGET_SEGMENTS}}': segments_block,
        '{{CAMPAIGN_PATHS}}': campaign_paths_block,
        '{{TARGET_CUSTOMER_DESCRIPTION}}': profile_dict.get('target_customer_description', ''),
        '{{GEOGRAPHY}}': profile_dict.get('geography', ''),
        '{{TONE_VOICE}}': profile_dict.get('tone_voice', 'Curious, respectful, not salesy'),
        '{{PRICING_NOTES}}': pricing_block,
        '{{SENDER_NAME}}': profile_dict.get('sender_name', ''),
        '{{SENDER_EMAIL}}': profile_dict.get('sender_email', ''),
    }

    for placeholder, value in replacements.items():
        content = content.replace(placeholder, value or '')

    return content
