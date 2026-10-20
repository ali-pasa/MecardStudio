import re
import json
import base64
import copy
import time
from html import escape
from bs4 import BeautifulSoup
from django.conf import settings
from .ai_provider import get_provider_config, generate_text


# Maps required_fields (from CardCategory) to the placeholder token
# that should appear in the generated template's HTML.
FIELD_TOKEN_MAP = {
    "photo": "{{photo_url}}",
    "full_name": "{{full_name}}",
    "id_number": "{{id_number}}",
    "department": "{{department}}",
    "qr_code": "{{qr_code_url}}",
    "valid_until": "{{valid_until}}",
    "job_title": "{{job_title}}",
    "phone": "{{phone}}",
    "email": "{{email}}",
    "visitor_name": "{{visitor_name}}",
    "host_name": "{{host_name}}",
    "visit_date": "{{visit_date}}",
    "member_name": "{{member_name}}",
    "membership_id": "{{membership_id}}",
    "tier": "{{tier}}",
    "patient_name": "{{patient_name}}",
    "patient_id": "{{patient_id}}",
    "blood_group": "{{blood_group}}",
    "emergency_contact": "{{emergency_contact}}",
    "policy_holder_name": "{{policy_holder_name}}",
    "policy_number": "{{policy_number}}",
    "provider_name": "{{provider_name}}",
    "medical_notes": "{{medical_notes}}",
    "vehicle_number": "{{vehicle_number}}",
    "owner_name": "{{owner_name}}",
    "company_name": "{{company_name}}",
}

DEFAULT_CARD_FIELDS = ("photo", "qr_code", "company_name", "phone", "email", "job_title")
PERSON_IDENTITY_FIELDS = (
    "full_name", "member_name", "visitor_name", "patient_name",
    "policy_holder_name", "owner_name", "employee_name",
)


def card_fields_for_category(category):
    """Return category fields plus the standard identity-card fields."""
    fields = list(category.required_fields or [])
    if not any(field in PERSON_IDENTITY_FIELDS for field in fields):
        fields.append("full_name")
    return list(dict.fromkeys([*fields, *DEFAULT_CARD_FIELDS]))


def card_placeholder(field):
    return FIELD_TOKEN_MAP.get(field, f"{{{{{field}}}}}")

PREVIEW_PHOTO_DATA_URI = "data:image/svg+xml;base64," + base64.b64encode(
    b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 250">
      <defs><linearGradient id="bg" x2="0" y2="1">
        <stop stop-color="#e9f1f6"/><stop offset="1" stop-color="#cbd9e4"/>
      </linearGradient></defs>
      <rect width="200" height="250" fill="url(#bg)"/>
      <circle cx="100" cy="83" r="39" fill="#f1c9a8"/>
      <path d="M61 82c1-54 77-67 80-1-15-14-25-20-42-21-9 13-21 20-38 22" fill="#253b50"/>
      <path d="M27 250c4-62 31-99 73-99s69 37 73 99" fill="#315b79"/>
      <path d="M78 153h44l-8 30-14 13-14-13z" fill="#fff"/>
    </svg>"""
).decode("ascii")

PREVIEW_QR_DATA_URI = "data:image/svg+xml;base64," + base64.b64encode(
    b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 21 21">
      <rect width="21" height="21" fill="#fff"/>
      <path fill="#172b3b" d="M1 1h7v7H1zm2 2v3h3V3zm10-2h7v7h-7zm2 2v3h3V3zM1 13h7v7H1zm2 2v3h3v-3z
      M10 1h2v2h-2zm0 4h2v3h-2zm-2 5h3v2H8zm5 0h2v2h-2zm4 0h3v2h-3zm-7 3h2v2h-2zm4 0h2v2h-2zm4 0h2v2h-2zm-8 3h2v3h-2zm4 1h2v2h-2zm4 0h3v2h-3z"/>
    </svg>"""
).decode("ascii")

DEMO_DATA = {
    "full_name": "Jane Doe",
    "department": "Engineering",
    "id_number": "EMP-2024-0451",
    "valid_until": "31 Dec 2027",
    "photo_url": PREVIEW_PHOTO_DATA_URI,
    "qr_code_url": PREVIEW_QR_DATA_URI,
    "job_title": "Senior Product Designer",
    "phone": "+1 (555) 012-3456",
    "email": "jane.doe@example.com",
    "visitor_name": "Alex Morgan",
    "host_name": "Sam Carter",
    "visit_date": "12 Sep 2026",
    "member_name": "Jane Doe",
    "membership_id": "MEM-88213",
    "tier": "Gold",
    "patient_name": "Jane Doe",
    "patient_id": "PT-004521",
    "blood_group": "O+",
    "emergency_contact": "+1 (555) 987-6543",
    "policy_holder_name": "Jane Doe",
    "policy_number": "POL-2024-77821",
    "provider_name": "SecureLife Insurance",
    "medical_notes": "No known allergies",
    "vehicle_number": "KA-01-AB-1234",
    "owner_name": "Jane Doe",
    "company_name": "Company Name",
}

CARD_DESIGN_DIRECTIONS = (
    {
        "key": "editorial",
        "label": "Editorial split",
        "instruction": "Create an editorial split composition: large portrait/photo column, strong typography, and a compact information rail.",
    },
    {
        "key": "dark",
        "label": "Dark premium",
        "instruction": "Create a premium dark-mode card with a deep ink surface, restrained metallic accent, and a bold name focal point.",
    },
    {
        "key": "color-block",
        "label": "Bold color blocks",
        "instruction": "Create an energetic geometric composition with distinct brand-color blocks, an angled color panel, and a clear light information area.",
    },
    {
        "key": "minimal",
        "label": "Minimal Swiss",
        "instruction": "Create a minimal Swiss-style layout with generous negative space, strict alignment, hairline rules, and one precise brand-color accent.",
    },
    {
        "key": "portrait",
        "label": "Portrait-led",
        "instruction": "Create a portrait-led identity card with an oversized photo area, a compact brand masthead, and neatly grouped credentials.",
    },
    {
        "key": "tech",
        "label": "Modern technical",
        "instruction": "Create a modern technical pass with a dark header band, structured data grid, subtle grid/detail motif, and a dedicated QR tile.",
    },
    {
        "key": "membership",
        "label": "Membership",
        "instruction": "Create a refined membership-card composition with a prominent tier or role badge, elegant serif/sans pairing, and a premium finish.",
    },
    {
        "key": "asymmetric",
        "label": "Asymmetric contemporary",
        "instruction": "Create an asymmetrical contemporary layout using offset columns, a large brand shape, and carefully balanced information.",
    },
)

CARD_ORIENTATION_ASPECT_RATIOS = {
    "horizontal": "1.6:1",
    "vertical": "1:1.6",
}


def category_for_card_orientation(category, orientation=None):
    if not isinstance(orientation, str):
        return category
    aspect_ratio = CARD_ORIENTATION_ASPECT_RATIOS.get(orientation)
    if not aspect_ratio:
        return category
    oriented_category = copy.copy(category)
    oriented_category.default_aspect_ratio = aspect_ratio
    return oriented_category


def build_template_prompt(
    company,
    brand,
    category,
    user_prompt=None,
    has_reference_image=False,
    design_direction=None,
):
    required_tokens = ", ".join(
        card_placeholder(field) for field in card_fields_for_category(category)
    )
    orientation_layout = (
        """PORTRAIT LAYOUT REQUIREMENTS:
- Use a true vertical ID/pass composition, not a landscape layout squeezed into
  a tall canvas.
- Reserve about 8% of the height for the brand/category header, 32% for a
  compact portrait and cardholder identity, 38% for a clearly grouped details
  panel, and the remaining height for a designed footer with the QR code.
- Place the cardholder name directly under or beside the portrait and make it
  the largest text. Do not use the company name as the main heading.
- Give the details panel a subtle contrasting surface and use a two-column
  grid when there are at least four detail fields.
- Anchor the footer to the bottom edge with a brand-color band. Keep all
  content inside the card bounds.
"""
        if category.default_aspect_ratio == CARD_ORIENTATION_ASPECT_RATIOS["vertical"]
        else """LANDSCAPE LAYOUT REQUIREMENTS:
- Use a true horizontal card composition with a compact portrait on one side
  and the cardholder identity/details grouped in the remaining space.
- Use the full width efficiently; keep the company as a small brand mark and
  the cardholder name as the primary heading.
"""
    )

    base_context = f"""You are a senior product designer at a top-tier design studio
(think: the visual quality of Stripe, Linear, or Apple's internal badge systems).
Generate a complete, self-contained HTML file with a polished, fully styled
card design (inline <style> only, no external CSS/JS except Google Fonts) for
a reusable "{category.name}" TEMPLATE.

CRITICAL — OUTPUT ONLY THE CARD ITSELF, NOT A FULL PAGE:
- The <body> must contain ONLY the card element, with NOTHING else around it.
- Do NOT center the card on a full-viewport page. Do NOT set body min-height:
  100vh, do NOT add a background color/gradient behind the card that fills
  the whole page, and do NOT add any outer page padding.
- body margin must be 0. The card element's own width/height (matching the
  aspect ratio below) should define the ENTIRE visible page size — as if
  this HTML file IS the card, not a webpage that happens to display a card.
- Always include a non-empty <style> block with the complete visual design.
  Do not return plain headings, paragraphs, or unstyled content; every field
  must be placed inside the designed card layout.
- Use one clearly defined card root element with explicit width and height,
  box-sizing: border-box, background, border-radius, and overflow: hidden.
  Scope visual styles to that card root and its children; do not style a full
  page or rely on browser defaults.
- This card will be rendered inside a small embedded iframe/thumbnail, so
  any extra page chrome (dark background, centering, margins) will show up
  as ugly empty space or force scrolling. Keep the output exactly the size
  of the card and nothing more.

IMPORTANT — THIS IS A TEMPLATE, NOT A FILLED-IN CARD:
Do not invent sample data (no fake names, fake ID numbers, fake dates).
For every field below, insert the EXACT placeholder token shown —
these will be programmatically replaced with real data later.

FIELDS TO PLACE IN THE DESIGN (as literal placeholder tokens):
{required_tokens}
These include the required category fields plus the standard ID-card fields:
portrait, QR code, company name, phone, email, and designation/job title.
Always include all of them, even when they are not listed as category-specific.
Also include a relevant person-name token from this list when applicable:
{{{{full_name}}}}, {{{{member_name}}}}, {{{{visitor_name}}}}, {{{{patient_name}}}},
{{{{policy_holder_name}}}}, or {{{{owner_name}}}}.

DESIGN QUALITY BAR — this must NOT look like a generic AI-generated card.
Specifically:
- Use a deliberate visual hierarchy: one clear focal point (usually the
  name/photo), supporting details clearly secondary in size/weight/color
- Use real spacing discipline — consistent padding/margins on an 8px grid,
  never cramped or randomly uneven
- Use subtle depth: soft shadows, thin borders, or a faint gradient — not
  flat single-color blocks, but also not overdone/gaudy
- Typography: import a real Google Font via <link> (e.g. Inter, Manrope,
  Space Grotesk, or similar) rather than relying on default system fonts;
  establish a clear type scale (name is largest, labels are smallest/muted)
- Respect the brand colors as ACCENTS and structure, not by painting the
  whole card in one color — use a neutral base (white, near-black, or a
  soft tint of the brand color) with the brand color used deliberately for
  emphasis (a stripe, a badge, an icon background, a border)
- Use the supplied primary, secondary, and accent colors as exact CSS values.
  Do not replace the extracted brand palette with generic blue/orange.
- The QR code area must look intentional: a clean white or contrasting
  tile with padding, not an afterthought
- Include a small notification bell icon in the card header. Draw it with an
  inline SVG or CSS shape; do not use emoji.
- Place compact Share and Save controls together at the very end of the card
  in a clear footer action row. They are visual card controls.
- Assume this card will be viewed on a phone screen at typical badge size —
  keep text legible, no more than 2 accent colors + neutrals
- Keep the composition visually balanced and use the available card area:
  all required fields must be visible without scrolling, clipped content, or
  large empty regions. Never push the name/details to the bottom with
  margin-top:auto or justify-content:space-between.
- Keep a portrait compact (about 20–28% of the card width and no more than
  32% of its height). Use object-fit:cover and a fixed portrait frame; do not
  stretch an image to fill the entire card.
- For a vertical card, use a compact top-to-bottom hierarchy: brand/header,
  portrait and name, then a tight two-column details grid and QR tile. Keep
  these elements grouped with consistent spacing.
- For a horizontal card, use a compact side-by-side composition with the
  portrait at one side and name/details grouped in the remaining space.
- Do not leave a large empty photo or color panel; if a portrait is present,
  its frame must stay compact and the required information must remain the
  primary focus.
- The cardholder is the hero, not the company: use the most relevant person
  placeholder as the large name (for example {{full_name}}, {{member_name}},
  {{visitor_name}}, or {{patient_name}}). Use {{company_name}} only for the
  logo/issuer line; never repeat the company as the cardholder's name.
- Fill the card canvas with a deliberate composition from top to bottom.
  Required content should occupy the central area and a designed footer or
  lower information band should finish the card. Do not leave the lower half
  empty after placing everything at the top.

CARD DIMENSIONS:
- Aspect ratio: {category.default_aspect_ratio or "1.6:1"}
- Set the card element's actual pixel width/height to match this ratio
  (e.g. 480px x 300px for 1.6:1 or 480px x 768px for 1:1.6) — this defines
  the whole page's size
- Leave a clearly styled area for the QR code placeholder token
- Layout should look like a real, physical ID/pass/badge — reference how
  actual corporate badges, event passes, or premium membership cards look
{orientation_layout}

DESIGN CONCEPT FOR THIS GENERATION:
{design_direction or "Choose a distinctive, high-quality composition; avoid a generic centered list."}

FIXED BRAND DATA (use these as real, actual values — NOT placeholders):
- Company name: {company.company_name or "Company Name"}
- Logo URL: {brand.logo_url if brand and brand.logo_url else "none — use a clean text logo instead"}
- Primary color: {brand.primary_color if brand and brand.primary_color else "#1f6f8b"}
- Secondary color: {brand.secondary_color if brand and brand.secondary_color else "#172b3b"}
- Accent color: {brand.accent_color if brand and brand.accent_color else "#f4b942"}
"""

    if has_reference_image:
        base_context += """
A REFERENCE IMAGE is attached. Treat its card design as the primary design
specification, ahead of generic style guidance and preset design directions.
Match the card's composition, relative sizing and placement, typography,
shapes, borders, spacing, and color palette closely. Keep the supplied
company identity and required data, but do not replace the reference palette
with the brand defaults. If the image shows multiple card designs, use only
the requested design for this variant (specified below); do not combine them.
Recreate the card itself edge-to-edge. Do not reproduce surrounding page
chrome, phone/device frames, screenshot margins, or unrelated text. Keep all
required fields readable and fit within the requested card dimensions.
"""

    if user_prompt:
        base_context += f"\n\nUSER'S SPECIFIC DESIGN REQUEST: {user_prompt}\nIncorporate this into the design, prioritizing it alongside the reference image guidance if both are present.\n"

    base_context += """
OUTPUT RULES:
- Return ONLY the HTML code — no explanation, no markdown code fences
- The document must include <html>, <head>, a non-empty inline <style> block,
  and <body> containing the designed card
- Include a Google Fonts <link> tag if using a non-system font
- Keep every {{placeholder}} token EXACTLY as given, character for character
- The result should look like it came from a real design team, not a template generator
- Remember: body contains ONLY the card, sized to the card's own dimensions
"""
    return base_context


def _call_provider_with_retry(prompt, image_data_uri=None):
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            return generate_text(prompt, image_data_uri=image_data_uri)
        except Exception as e:
            message = str(e)
            is_rate_limited = getattr(e, "status_code", None) == 429 or "429" in message
            if is_rate_limited and attempt < 2:
                retry_after = None
                response = getattr(e, "response", None)
                headers = getattr(response, "headers", None) or {}
                try:
                    retry_after = float(headers.get("retry-after"))
                except (TypeError, ValueError):
                    match = re.search(
                        r"retryDelay['\"]?\s*:\s*['\"]([\d.]+)s",
                        message,
                    )
                    if match:
                        retry_after = float(match.group(1))
                retry_after = max(retry_after or 16, 1)
                # Retry brief RPM throttles inline, but don't hold the web
                # request for hours when a daily quota has been exhausted.
                if retry_after <= 60:
                    time.sleep(retry_after)
                    continue
                raise

            is_503 = "503" in message or "UNAVAILABLE" in message
            if is_503 and attempt < max_attempts:
                time.sleep(2 * attempt)  # 2s, then 4s backoff
                continue
            raise


def render_mock_card_template(company, brand, category, design_direction=None) -> str:
    """Return distinct, branded local concepts when the AI service is unavailable."""
    design = next(
        (item for item in CARD_DESIGN_DIRECTIONS if item["key"] == design_direction),
        CARD_DESIGN_DIRECTIONS[0],
    )
    primary = getattr(brand, "primary_color", None) or "#1f6f8b"
    secondary = getattr(brand, "secondary_color", None) or "#172b3b"
    accent = getattr(brand, "accent_color", None) or "#f4b942"
    logo_url = getattr(brand, "logo_url", None)

    card_fields = card_fields_for_category(category)
    identity_field = next(
        (field for field in PERSON_IDENTITY_FIELDS if field in card_fields),
        "full_name",
    )
    identity_token = card_placeholder(identity_field)
    field_markup = "".join(
        f'<div class="detail"><span>{escape(field.replace("_", " ").title())}</span>'
        f'<strong>{card_placeholder(field)}</strong></div>'
        for field in card_fields
        if field not in ("photo", "qr_code", identity_field)
    )
    photo = '<div class="portrait"><img src="{{photo_url}}" alt="Portrait"></div>'
    qr_code = '<div class="qr"><img src="{{qr_code_url}}" alt="QR code"></div>'
    logo_markup = (
        f'<img class="logo" src="{escape(logo_url, quote=True)}" alt="">'
        if logo_url else '<span class="logo-word">{{company_name}}</span>'
    )
    bell_icon = (
        '<span class="notification-bell" aria-label="Notifications">'
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 9a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/></svg>'
        '</span>'
    )
    card_actions = (
        '<div class="card-actions">'
        '<button type="button" aria-label="Share card"><span class="share-icon">↗</span>Share</button>'
        '<button type="button" aria-label="Save card"><span class="save-icon">▣</span>Save</button>'
        '</div>'
    )
    company_subtitle = escape(company.tagline or "Authorized identity")
    width = 480
    height = 300
    try:
        ratio_width, ratio_height = (
            float(part) for part in (category.default_aspect_ratio or "1.6:1").split(":")
        )
        if ratio_width > 0 and ratio_height > 0:
            height = round(width * ratio_height / ratio_width)
    except (TypeError, ValueError):
        pass

    style = f"""
      * {{ box-sizing: border-box; }}
      html, body {{ width: {width}px; height: {height}px; margin: 0; overflow: hidden; }}
      body {{ font-family: Inter, ui-sans-serif, system-ui, sans-serif; }}
      .card {{
        --brand: {primary}; --ink: {secondary}; --accent: {accent};
        position: relative; display: flex; width: 100%; height: 100%;
        overflow: hidden; padding: 24px; color: var(--ink);
        background: #f8fafc; border-radius: 18px;
        box-shadow: 0 12px 30px rgba(15, 35, 50, .16);
      }}
      .content {{ position: relative; z-index: 1; display: flex; min-width: 0; flex: 1; flex-direction: column; }}
      .topline {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; }}
      .logo {{ display: block; max-width: 96px; max-height: 28px; object-fit: contain; }}
      .logo-word {{ color: var(--brand); font-size: 12px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }}
      .category {{ color: var(--brand); font-size: 9px; font-weight: 800; letter-spacing: .16em; text-transform: uppercase; }}
      .header-actions {{ display: flex; align-items: center; gap: 10px; }}
      .notification-bell {{ display: grid; width: 26px; height: 26px; place-items: center; border: 1px solid currentColor; border-radius: 50%; color: var(--brand); }}
      .notification-bell svg {{ width: 15px; height: 15px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }}
      .card-actions {{ display: flex; align-self: flex-end; gap: 7px; margin-top: auto; padding-top: 10px; }}
      .card-actions button {{ display: inline-flex; align-items: center; gap: 5px; padding: 6px 10px; border: 1px solid rgba(127,145,160,.35); border-radius: 8px; color: var(--ink); background: rgba(255,255,255,.82); font: 700 9px Inter, sans-serif; }}
      .card-actions span {{ font-size: 12px; line-height: 1; }}
      h1 {{ margin: 12px 0 4px; color: var(--ink); font-size: 26px; line-height: 1.05; letter-spacing: -.045em; }}
      .company {{ margin: 0 0 10px; color: #687887; font-size: 11px; }}
      .details {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px 14px; }}
      .detail {{ min-width: 0; display: flex; flex-direction: column; gap: 3px; }}
      .detail span {{ color: #71808d; font-size: 8px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; }}
      .detail strong {{ overflow: hidden; color: var(--ink); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }}
      .portrait {{ width: 100px; height: 132px; flex: 0 0 auto; overflow: hidden; border-radius: 12px; background: #e3eaf0; }}
      .portrait img {{ width: 100%; height: 100%; object-fit: cover; }}
      .qr {{ display: grid; width: 58px; height: 58px; flex: 0 0 auto; place-items: center; padding: 5px; border-radius: 8px; background: white; }}
      .qr img {{ width: 100%; height: 100%; object-fit: contain; }}
      .editorial {{ gap: 22px; border-left: 8px solid var(--brand); background: linear-gradient(110deg,#fff 0 69%,#e9f0f5 69%); }}
      .editorial .portrait {{ order: 2; width: 112px; height: 100%; margin: -24px -24px -24px 0; border-radius: 0; }}
      .editorial .content {{ padding-right: 2px; }}
      .dark {{ color: #f6f8fa; background: radial-gradient(circle at 90% 10%,var(--brand),var(--ink) 54%); }}
      .dark h1,.dark .detail strong {{ color: #fff; }} .dark .company,.dark .detail span {{ color: #d0dae2; }}
      .dark .logo-word,.dark .category {{ color: var(--accent); }}
      .color-block {{ background: linear-gradient(135deg,var(--brand) 0 34%,#f8fafc 34%); }}
      .color-block .content {{ padding-left: 8px; }} .color-block h1 {{ color: var(--ink); }}
      .minimal {{ padding: 30px; border: 1px solid #dce3e9; background: #fff; }}
      .minimal .topline {{ padding-bottom: 12px; border-bottom: 1px solid #dce3e9; }}
      .minimal h1 {{ font-family: Georgia,serif; font-weight: 500; }}
      .portrait-led {{ gap: 18px; background: #fff; }}
      .portrait-led .portrait {{ width: 142px; height: calc(100% + 48px); margin: -24px 0 -24px -24px; border-radius: 0; }}
      .portrait-led .content {{ padding: 0 0 0 4px; }}
      .tech {{ background: linear-gradient(145deg,var(--ink) 0 29%,#f4f7fa 29%); }}
      .tech .topline {{ color: #fff; }} .tech .logo-word,.tech .category {{ color: var(--accent); }}
      .tech .content {{ gap: 8px; }} .tech h1 {{ margin: 10px 0 0; }}
      .membership {{ flex-direction: column; color: #fff; background: linear-gradient(125deg,var(--ink),var(--brand)); }}
      .membership h1,.membership .detail strong {{ color: #fff; }}
      .membership .company,.membership .detail span {{ color: rgba(255,255,255,.78); }}
      .membership .logo-word,.membership .category {{ color: var(--accent); }}
      .membership .content {{ gap: 8px; }} .membership h1 {{ margin: auto 0 0; font-family: Georgia,serif; }}
      .asymmetric {{ gap: 18px; background: #fff; }}
      .asymmetric::before {{ position:absolute; top:-70px; right:-55px; width:210px; height:210px; border-radius:50%; background:var(--brand); opacity:.13; content:""; }}
      .asymmetric .content {{ padding-top: 10px; }} .asymmetric h1 {{ max-width: 220px; }}
      .asymmetric .qr {{ align-self: flex-end; }}
      .card.vertical {{
        display: flex; flex-direction: column; align-items: stretch; gap: 0;
        padding: 22px 24px 0; border-radius: 20px;
        background:
          radial-gradient(circle at 94% 22%, color-mix(in srgb, var(--brand) 12%, transparent), transparent 26%),
          linear-gradient(180deg, #fff 0%, #f8fafc 100%);
      }}
      .card.vertical .vertical-topline {{
        display: flex; flex: 0 0 auto; min-height: 38px;
        align-items: center; justify-content: space-between; gap: 12px;
        padding-bottom: 12px; border-bottom: 1px solid rgba(23,43,59,.1);
      }}
      .card.vertical .logo {{ max-width: 118px; max-height: 34px; }}
      .card.vertical .category {{ max-width: 190px; text-align: right; }}
      .card.vertical .header-actions {{ margin-left: auto; }}
      .card.vertical .vertical-person {{
        display: flex; flex: 0 0 auto; align-items: center;
        flex-direction: column; padding: 18px 0 16px; text-align: center;
      }}
      .card.vertical .portrait {{
        width: 126px; height: 142px; margin: 0 0 15px;
        border: 4px solid #fff; border-radius: 18px;
        box-shadow: 0 8px 24px rgba(15,35,50,.16);
      }}
      .card.vertical h1 {{
        max-width: 100%; margin: 0; color: var(--ink);
        font-size: 29px; line-height: 1.04; letter-spacing: -.045em;
      }}
      .card.vertical .company {{ margin: 6px 0 0; font-size: 12px; }}
      .card.vertical .details {{
        display: grid; flex: 1 1 auto; align-content: start;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 13px 16px; margin: 0 -24px; padding: 19px 24px;
        border-top: 1px solid rgba(23,43,59,.08);
        background: rgba(226,234,241,.42);
      }}
      .card.vertical .detail span {{ font-size: 9px; }}
      .card.vertical .detail strong {{ font-size: 12px; }}
      .card.vertical .vertical-footer {{
        display: flex; flex: 0 0 auto; min-height: 86px;
        align-items: center; justify-content: space-between; gap: 14px;
        margin: 0 -24px; padding: 14px 24px;
        color: #fff; background: var(--ink);
      }}
      .card.vertical .vertical-footer-copy {{
        min-width: 0; color: rgba(255,255,255,.82);
        font-size: 10px; font-weight: 700; letter-spacing: .08em;
        line-height: 1.5; text-transform: uppercase;
      }}
      .card.vertical .vertical-footer-copy::before {{
        display: block; width: 28px; height: 3px; margin-bottom: 8px;
        border-radius: 3px; background: var(--accent); content: "";
      }}
      .card.vertical .vertical-footer {{ flex-wrap: wrap; }}
      .card.vertical .card-actions {{ margin-top: 0; padding-top: 0; }}
      .card.vertical .card-actions button {{ color: #fff; border-color: rgba(255,255,255,.3); background: rgba(255,255,255,.1); }}
      .card.vertical .qr {{
        width: 66px; height: 66px; padding: 6px;
        border: 2px solid rgba(255,255,255,.8); border-radius: 10px;
      }}
      /* Vertical concepts need different structure, not only different colors. */
      .card.vertical.editorial {{
        border-left: 9px solid var(--brand);
        background: linear-gradient(110deg, #fff 0 73%, #eaf0f5 73%);
      }}
      .card.vertical.editorial .vertical-person {{
        align-items: center; flex-direction: row; gap: 18px; text-align: left;
      }}
      .card.vertical.editorial .portrait {{ width: 112px; height: 132px; margin: 0; }}
      .card.vertical.editorial .vertical-person h1 {{ font-size: 27px; }}
      .card.vertical.editorial .vertical-person .company {{ max-width: 220px; }}
      .card.vertical.dark {{ color: #f6f8fa; background: radial-gradient(circle at 90% 8%, var(--brand), var(--ink) 58%); }}
      .card.vertical.dark h1, .card.vertical.dark .detail strong {{ color: #fff; }}
      .card.vertical.dark .company, .card.vertical.dark .detail span {{ color: #d0dae2; }}
      .card.vertical.dark .logo-word, .card.vertical.dark .category {{ color: var(--accent); }}
      .card.vertical.dark .details {{ border-color: rgba(255,255,255,.14); background: rgba(255,255,255,.08); }}
      .card.vertical.color-block {{ background: linear-gradient(155deg, var(--brand) 0 22%, #f8fafc 22%); }}
      .card.vertical.color-block .vertical-topline {{ border-color: rgba(255,255,255,.4); }}
      .card.vertical.color-block .logo-word, .card.vertical.color-block .category {{ color: #fff; }}
      .card.vertical.color-block .details {{ background: #fff; }}
      .card.vertical.minimal {{ border: 1px solid #dce3e9; background: #fff; }}
      .card.vertical.minimal .vertical-topline {{ padding-bottom: 15px; border-bottom: 1px solid #dce3e9; }}
      .card.vertical.minimal h1 {{ font-family: Georgia, serif; font-weight: 500; }}
      .card.vertical.minimal .details {{ background: #f7f9fb; }}
      .card.vertical.portrait-led .vertical-person {{ padding: 14px 0 12px; }}
      .card.vertical.portrait-led .portrait {{ width: 154px; height: 174px; }}
      .card.vertical.portrait-led .details {{ background: #fff; }}
      .card.vertical.tech {{ background: linear-gradient(180deg, var(--ink) 0 13%, #f4f7fa 13%); }}
      .card.vertical.tech .vertical-topline {{ border-color: rgba(255,255,255,.2); }}
      .card.vertical.tech .logo-word, .card.vertical.tech .category {{ color: var(--accent); }}
      .card.vertical.tech .details {{ border: 1px solid #dce4eb; border-radius: 12px; background: #fff; }}
      .card.vertical.membership {{ color: #fff; background: linear-gradient(145deg, var(--ink), var(--brand)); }}
      .card.vertical.membership h1, .card.vertical.membership .detail strong {{ color: #fff; }}
      .card.vertical.membership .company, .card.vertical.membership .detail span {{ color: rgba(255,255,255,.78); }}
      .card.vertical.membership .logo-word, .card.vertical.membership .category {{ color: var(--accent); }}
      .card.vertical.membership .details {{ border-color: rgba(255,255,255,.16); background: rgba(255,255,255,.09); }}
      .card.vertical.asymmetric .vertical-person {{ align-items: flex-start; padding-left: 30px; text-align: left; }}
      .card.vertical.asymmetric .vertical-person::after {{
        position: absolute; top: 110px; right: -42px; width: 190px; height: 190px;
        border-radius: 50%; background: var(--brand); opacity: .12; content: ""; pointer-events: none;
      }}
      .card.vertical.asymmetric .portrait, .card.vertical.asymmetric h1,
      .card.vertical.asymmetric .company {{ position: relative; z-index: 1; }}
    """
    vertical = category.default_aspect_ratio == CARD_ORIENTATION_ASPECT_RATIOS["vertical"]
    if vertical:
        vertical_header = (
            f'<header class="vertical-topline">{logo_markup}'
            f'<div class="header-actions"><span class="category">{escape(category.name)}</span>'
            f'{bell_icon}</div></header>'
        )
        identity = (
            f'<h1>{identity_token}</h1>'
            f'<p class="company">{company_subtitle}</p>'
        )
        vertical_markup = (
            f'{vertical_header}<div class="vertical-person">{photo}{identity}</div>'
            f'<div class="details">{field_markup}</div>'
            f'<footer class="vertical-footer">'
            f'<span class="vertical-footer-copy">{escape(category.name)}</span>{qr_code}{card_actions}'
            f'</footer>'
        )
    else:
        vertical_markup = (
            f'{photo}<section class="content">'
            f'<div class="topline">{logo_markup}<div class="header-actions">'
            f'<span class="category">{escape(category.name)}</span>{bell_icon}</div></div>'
            f'<h1>{identity_token}</h1><p class="company">{company_subtitle}</p>'
            f'<div class="details">{field_markup}</div>{card_actions}'
            f'</section>{qr_code}'
        )
    orientation_class = (
        " vertical"
        if vertical
        else ""
    )
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{style}</style></head>
      <body><main class="card {design['key']}{orientation_class}">
        {vertical_markup}
      </main></body></html>"""


def generate_card_template(
    company,
    brand,
    category,
    extra_instruction=None,
    previous_html=None,
    user_prompt=None,
    reference_image_url=None,
    design_direction=None,
):
      """
      Generate one reusable card template.

      The generated HTML contains {{placeholder}} tokens.
      Those tokens are replaced only when rendering the preview
      or creating a real card.
      """

      _, provider, api_key, _ = get_provider_config()

      prompt = build_template_prompt(
          company,
          brand,
          category,
          user_prompt=user_prompt,
          has_reference_image=bool(reference_image_url),
          design_direction=design_direction,
      )

      # -------------------------------------------------------------
      # FORCE DESIGN DIFFERENTIATION
      # -------------------------------------------------------------

      if design_direction:
          design = next(
              (
                  item
                  for item in CARD_DESIGN_DIRECTIONS
                  if item["key"] == design_direction
              ),
              None,
          )

          if design:
              prompt += f"""

  ========================================================
  MANDATORY DESIGN DIRECTION
  ========================================================

  Design concept:
  {design["label"]}

  Required composition:
  {design["instruction"]}

  This is NOT optional.

  You must create a genuinely different composition
  based on this direction.

  Do not merely change:
  - colors
  - font sizes
  - border radius
  - shadows

  You MUST change:
  - element placement
  - information grouping
  - photo placement
  - QR placement
  - header structure
  - footer structure
  - visual hierarchy
  - whitespace/composition

  The resulting card must be visibly different from
  another card generated using another design direction.
  """

      # -------------------------------------------------------------
      # USER INSTRUCTION
      # -------------------------------------------------------------

      if user_prompt:
          prompt += f"""

  ========================================================
  USER DESIGN REQUEST
  ========================================================

  {user_prompt}

  Follow this request while preserving:
  - required fields
  - company branding
  - card dimensions
  - readability
  - reference-image inspiration
  """

      # -------------------------------------------------------------
      # EXTRA VARIANT INSTRUCTION
      # -------------------------------------------------------------

      if extra_instruction:
          prompt += f"""

  ========================================================
  VARIANT-SPECIFIC INSTRUCTION
  ========================================================

  {extra_instruction}

  IMPORTANT:

  The variant-specific instruction has priority for
  composition.

  However, NEVER remove required placeholder tokens.
  """

      # -------------------------------------------------------------
      # PREVIOUS HTML
      # -------------------------------------------------------------

      if previous_html:
          prompt += f"""

  ========================================================
  PREVIOUS TEMPLATE
  ========================================================

  {previous_html}

  Modify the previous template according to the new
  instruction.

  Return the COMPLETE HTML document.

  Do NOT return only the changed section.
  """

      # -------------------------------------------------------------
      # HARD OUTPUT REQUIREMENTS
      # -------------------------------------------------------------

      prompt += """

  ========================================================
  FINAL OUTPUT REQUIREMENTS
  ========================================================

  Before returning the HTML, verify all of the following:

  1. The card contains EVERY required placeholder.

  2. Never replace a placeholder with fake data.

  3. Never remove a placeholder.

  4. The card must actually use the available canvas.

  5. Do not create a giant empty content area.

  6. The card must have a strong visual hierarchy.

  7. The card must look intentionally designed.

  8. The card must have visible content in the middle
    and lower areas.

  9. The photo must be compact.

  10. The QR code must be intentionally positioned.

  11. The company is the issuer/brand.

  12. The person/member/patient/visitor is the
      primary identity.

  13. Return COMPLETE HTML.

  14. Return ONLY HTML.

  15. No markdown.

  16. No explanation.

  17. No ```html fences.

  18. Keep every placeholder EXACTLY as:
      {{field_name}}

  19. Do not invent any additional data fields beyond the required category
      fields and the standard card fields listed above.

  20. Do not omit fields.
  """

      # -------------------------------------------------------------
      # NO API KEY
      # -------------------------------------------------------------

      if not api_key:
          if provider == "gemini" and not reference_image_url:
              return render_mock_card_template(
                  company,
                  brand,
                  category,
                  design_direction=design_direction,
              )
          if reference_image_url and provider == "gemini":
              raise RuntimeError(
                  "Reference image generation requires GEMINI_API_KEY. "
                  "Configure the image generation service and try again."
              )
          # Let generate_text raise an actionable missing-key error.
          return generate_text(prompt, image_data_uri=reference_image_url)

      html = _call_provider_with_retry(prompt, image_data_uri=reference_image_url)

      html = html.strip()

      # Remove markdown fences if Gemini adds them.
      html = re.sub(
          r"^```html\s*",
          "",
          html,
          flags=re.IGNORECASE,
      )

      html = re.sub(
          r"^```\s*",
          "",
          html,
      )

      html = re.sub(
          r"\s*```$",
          "",
          html,
      )

      html = html.strip()

      return html


def encode_uploaded_image_to_data_uri(uploaded_file) -> str:
    """
    Converts a Django UploadedFile into a base64 data: URI,
    since the AI needs either a public URL or inline base64 data
    — an uploaded file has neither until we do this.
    """
    content_type = uploaded_file.content_type or "image/png"
    encoded = base64.b64encode(uploaded_file.read()).decode("utf-8")
    return f"data:{content_type};base64,{encoded}"


def ensure_card_styling(template_html: str, category=None) -> str:
    """Give card markup a designed fallback and enforce its requested dimensions."""
    soup = BeautifulSoup(template_html, "lxml")
    body = soup.body
    has_inline_card_style = body and any(
        element is not body for element in body.find_all(attrs={"style": True})
    )
    has_style_block = any(style.get_text(strip=True) for style in soup.find_all("style"))

    width = 480
    height = 300
    ratio = getattr(category, "default_aspect_ratio", None)
    if ratio:
        try:
            ratio_width, ratio_height = (float(part) for part in ratio.split(":"))
            if ratio_width > 0 and ratio_height > 0:
                height = round(width * ratio_height / ratio_width)
        except (ValueError, TypeError):
            pass

    head = soup.head
    if head is None:
        head = soup.new_tag("head")
        if body is None:
            body = soup.new_tag("body")
            soup.append(body)
        body.insert_before(head)

    if has_style_block or has_inline_card_style:
        size_override = soup.new_tag("style")
        size_override.string = f"""
          html, body {{
            box-sizing: border-box !important;
            width: {width}px !important; height: {height}px !important;
            min-width: 0 !important; min-height: 0 !important;
            max-width: none !important; max-height: none !important;
            margin: 0 !important; padding: 0 !important; overflow: hidden !important;
          }}
          body > *:not(script):not(style) {{
            box-sizing: border-box !important;
            width: 100% !important; height: 100% !important;
            max-width: none !important; max-height: none !important;
            margin: 0 !important;
          }}
          body .card, body main, body article {{
            box-sizing: border-box !important;
            width: 100% !important; height: 100% !important;
            min-width: 0 !important; min-height: 0 !important;
            max-width: none !important; max-height: none !important;
            margin: 0 !important;
          }}
        """
        head.append(size_override)
        return str(soup)

    style = soup.new_tag("style")
    style.string = f"""
      html, body {{ width: {width}px; height: {height}px; margin: 0; }}
      body {{
        box-sizing: border-box; overflow: hidden;
        background: #edf2f7; color: #172b3b;
        font-family: Inter, ui-sans-serif, system-ui, sans-serif;
      }}
      .generated-card-fallback {{
        position: relative; display: flex; box-sizing: border-box;
        width: 100%; height: 100%; flex-direction: column;
        justify-content: center; gap: 10px; overflow: hidden;
        padding: 28px 30px 28px 36px; border: 1px solid #dbe4ec;
        border-radius: 18px;
        background: linear-gradient(145deg, #fff 10%, #f2f7fb 100%);
        box-shadow: 0 12px 26px rgba(25, 49, 68, .13);
      }}
      .generated-card-fallback::before {{
        position: absolute; inset: 0 auto 0 0; width: 7px;
        background: linear-gradient(180deg, #1f6f8b, #f4b942); content: "";
      }}
      .generated-card-fallback > * {{ position: relative; margin: 0; }}
      .generated-card-fallback h1, .generated-card-fallback h2,
      .generated-card-fallback h3 {{
        color: #122334; font-size: 25px; line-height: 1.15;
        letter-spacing: -.035em;
      }}
      .generated-card-fallback p {{
        color: #526575; font-size: 13px; line-height: 1.5;
      }}
      .generated-card-fallback strong {{ color: #1f6f8b; }}
      html, body {{
        width: {width}px !important; height: {height}px !important;
        min-width: 0 !important; min-height: 0 !important;
        max-width: none !important; max-height: none !important;
        margin: 0 !important; overflow: hidden !important;
      }}
      body > *:not(script):not(style) {{
        width: 100% !important; height: 100% !important;
        max-width: none !important; max-height: none !important;
      }}
    """
    head.append(style)

    body.attrs.pop("style", None)
    card = soup.new_tag("div", attrs={"class": "generated-card-fallback"})
    card.extend(list(body.contents))
    body.append(card)
    return str(soup)


def render_preview_html(template_html: str, category=None, company=None) -> str:
    """
    Fills a template's {{placeholder}} tokens with configured company payload
    values, falling back to realistic demo data. The stored template itself is
    never modified — this is a display-only transformation.
    """
    payload = getattr(company, "payload", None)
    payload = payload if isinstance(payload, dict) else {}

    def replace_token(match):
        key = match.group(1).strip()
        payload_key = key.strip("{}").strip()
        if payload_key in payload and payload[payload_key] is not None:
            value = payload[payload_key]
        elif key == "company_name" and company and company.company_name:
            value = company.company_name
        else:
            value = DEMO_DATA.get(key, key.replace("_", " ").title())
        return escape(str(value))

    styled_html = ensure_card_styling(template_html, category)
    return re.sub(r"\{\{(\w+)\}\}", replace_token, styled_html)


def is_renderable_card_template(template_html: str, required_fields) -> bool:
    """Reject truncated or malformed model HTML before it reaches the iframe."""
    if not isinstance(template_html, str) or not template_html.strip():
        return False

    soup = BeautifulSoup(template_html, "lxml")
    body = soup.body
    if body is None or not soup.find("style"):
        return False

    card_root = body.find(["main", "article", "section"])
    if card_root is None:
        card_root = body.find("div", class_=re.compile(r"\bcard\b", re.IGNORECASE))
    if card_root is None:
        return False

    body_html = str(body)
    if any(card_placeholder(field) not in body_html for field in required_fields):
        return False

    for node in body.find_all(["style", "script"]):
        node.decompose()
    visible_text = body.get_text(" ", strip=True)
    visible_fields = [
        field for field in required_fields if field not in ("photo", "qr_code")
    ]
    if any(card_placeholder(field) not in visible_text for field in visible_fields):
        return False
    if re.search(
        r"\b(?:font-family|font-size|letter-spacing|border-radius|box-shadow|"
        r"background(?:-color)?|grid-template-columns)\s*:",
        visible_text,
        re.IGNORECASE,
    ):
        return False
    return True


def render_card_from_template(template_html: str, data: dict) -> str:
    """
    Fills a template with REAL data (for actual employee/record use later).
    """
    rendered = template_html
    for key, value in data.items():
        rendered = rendered.replace("{{" + key + "}}", str(value))
    return rendered
