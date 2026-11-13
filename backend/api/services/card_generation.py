import re
import json
import base64
import copy
import random
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


def card_fields_for_category(category, company=None):
    """Return category, custom company payload, and standard card fields."""
    fields = list(category.required_fields or [])
    payload = getattr(company, "payload", None)
    if isinstance(payload, dict):
        for payload_key, value in payload.items():
            key = str(payload_key).strip().strip("{}").strip()
            if re.fullmatch(r"\w+", key) and value is not None and str(value).strip():
                fields.append(key)
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


FIELD_LABELS = {
    "photo": "Photo", "qr_code": "QR code", "id_number": "ID No.",
    "valid_until": "Valid until", "job_title": "Designation", "membership_id": "Member ID",
    "patient_id": "Patient ID", "blood_group": "Blood group", "policy_number": "Policy No.",
    "provider_name": "Provider", "vehicle_number": "Vehicle No.", "company_name": "Issuer",
}

# Only the hints for fields a category actually has are sent (no wasted tokens).
FIELD_HINTS = {
    "blood_group": "blood group as a high-contrast badge",
    "emergency_contact": "emergency contact clearly labelled and high contrast",
    "tier": "tier as a badge/ribbon",
    "valid_until": "validity as a small line near the footer",
    "vehicle_number": "vehicle number as a large licence-plate style block",
    "medical_notes": "medical notes may wrap to 2 lines in smaller text",
    "visit_date": "visit date and host grouped together",
    "id_number": "ID numbers in tabular/monospace figures",
    "membership_id": "member ID in tabular/monospace figures",
    "policy_number": "policy number in tabular/monospace figures",
}

# Design directions that suit each category best (by slug keyword).
CATEGORY_DIRECTION_PREFERENCES = (
    ("membership", ("membership", "dark", "asymmetric")),
    ("insurance", ("minimal", "membership", "tech")),
    ("visitor", ("tech", "color-block", "minimal")),
    ("health", ("minimal", "tech", "editorial")),
    ("emergency", ("color-block", "minimal", "tech")),
    ("parking", ("color-block", "tech", "dark")),
    ("business", ("minimal", "editorial", "dark")),
    ("id", ("portrait", "editorial", "tech")),
)

REFERENCE_VARIATIONS = (
    "Faithful recreation of the reference card's layout and style.",
    "Same visual language as the reference, but an alternate arrangement of photo, details and QR.",
    "Same palette and typography as the reference, with a bolder header and footer treatment.",
)

CARD_SIZE_STYLE_ATTR = "data-card-size"


def _card_dimensions(category):
    width, height = 480, 300
    ratio = getattr(category, "default_aspect_ratio", None)
    if ratio:
        try:
            ratio_width, ratio_height = (float(part) for part in ratio.split(":"))
            if ratio_width > 0 and ratio_height > 0:
                height = round(width * ratio_height / ratio_width)
        except (ValueError, TypeError):
            pass
    return width, height


def _field_label(field):
    return FIELD_LABELS.get(field, field.replace("_", " ").capitalize())


def pick_design_directions(count, category=None, rng=None):
    """Distinct directions, category-appropriate ones first, shuffled per request."""
    rng = rng or random.Random()
    slug = (getattr(category, "slug", "") or getattr(category, "name", "") or "").lower()
    preferred = next((keys for word, keys in CATEGORY_DIRECTION_PREFERENCES if word in slug), ())
    by_key = {d["key"]: d for d in CARD_DESIGN_DIRECTIONS}
    first = [by_key[k] for k in preferred if k in by_key]
    rest = [d for d in CARD_DESIGN_DIRECTIONS if d["key"] not in preferred]
    rng.shuffle(first)
    rng.shuffle(rest)
    ordered = first + rest
    return [ordered[i % len(ordered)] for i in range(count)]


def _brand_extras(company, brand):
    """Optional brand facts from URL extraction; omitted lines cost no tokens."""
    parts = []
    if brand and getattr(brand, "font_family", None):
        parts.append(f"font {brand.font_family} (Google Fonts if available)")
    if brand and getattr(brand, "brand_style", None):
        parts.append(f"tone {brand.brand_style}")
    if getattr(company, "industry", None):
        parts.append(f"industry {company.industry}")
    if getattr(company, "tagline", None):
        parts.append(f'optional small tagline "{company.tagline}"')
    return "; ".join(parts)


def build_template_prompt(
    company,
    brand,
    category,
    user_prompt=None,
    has_reference_image=False,
    design_direction=None,
    concepts=None,
):
    """Compact shared design brief. `concepts` (list of str) asks for several
    cards in one response so the brief and any reference image are sent once."""
    fields = card_fields_for_category(category, company)
    width, height = _card_dimensions(category)
    vertical = height > width
    identity = next((f for f in fields if f in PERSON_IDENTITY_FIELDS), "full_name")

    field_lines = []
    for field in fields:
        token = card_placeholder(field)
        if field == "photo":
            field_lines.append(f'<img src="{token}"> compact portrait, object-fit:cover')
        elif field == "qr_code":
            field_lines.append(f'<img src="{token}"> QR on a white tile with padding')
        elif field == identity:
            field_lines.append(f"{token} cardholder name: the largest text")
        else:
            field_lines.append(f"{token} label \"{_field_label(field)}\"")
    hints = [FIELD_HINTS[f] for f in fields if f in FIELD_HINTS]

    logo = (
        f"logo <img> {brand.logo_url}" if brand and getattr(brand, "logo_url", None)
        else "no logo: use a text wordmark of {{company_name}}"
    )
    extras = _brand_extras(company, brand)
    layout = (
        "Vertical badge: header ~10%, portrait + name ~32%, two-column details ~38%, "
        "footer band with QR at the bottom."
        if vertical else
        "Horizontal card: portrait on one side, name and details grouped beside it, QR tile placed deliberately."
    )

    lines = [
        f'Design a reusable "{category.name}" card TEMPLATE as self-contained HTML.',
        "",
        f'BRAND (exact values): company "{company.company_name or "Company Name"}"; {logo}; '
        f"primary {getattr(brand, 'primary_color', None) or '#1f6f8b'}, "
        f"secondary {getattr(brand, 'secondary_color', None) or '#172b3b'}, "
        f"accent {getattr(brand, 'accent_color', None) or '#f4b942'}"
        + (f"; {extras}" if extras else "") + ".",
        "",
        "FIELDS: include every token exactly as written, as visible text (labels short):",
        *(f"- {line}" for line in field_lines),
    ]
    if hints:
        lines.append("Field styling: " + "; ".join(hints) + ".")
    lines += [
        "Never invent sample data or extra fields. {{company_name}} is the issuer mark, not the hero.",
        "",
        f"CANVAS: one root <main class=\"card\"> exactly {width}x{height}px; body margin 0 with "
        "nothing outside the card; overflow hidden; box-sizing border-box. " + layout,
        "",
        "QUALITY: looks like a real printed badge from a top design studio; clear hierarchy; "
        "8px spacing grid; neutral base with brand colours as accents (stripe, band, badge); "
        "fill the canvas evenly with no large empty areas and no clipped text; text >= 9px; "
        "no buttons, icons for app actions, or JavaScript.",
    ]

    if has_reference_image:
        lines += [
            "",
            "REFERENCE IMAGE attached: it is the primary design spec. Match its composition, "
            "typography, shapes, spacing and palette; replace its sample data with the tokens; "
            "ignore screenshot/device chrome.",
        ]
    if user_prompt:
        lines += ["", f"USER REQUEST (highest priority for style): {user_prompt}"]

    if concepts and len(concepts) > 1:
        lines += [
            "",
            f"Create {len(concepts)} cards. Each must differ in LAYOUT (photo/QR position, "
            "header/footer structure, grouping), not just colour:",
            *(f"{i}. {concept}" for i, concept in enumerate(concepts, 1)),
            "",
            f"OUTPUT: {len(concepts)} complete HTML documents, each preceded by its marker line "
            "<!--CARD n--> (n = 1..). Compact CSS in one <style> per card: no comments, short "
            "class names, no unused rules. A Google Fonts <link> is allowed. No markdown, no prose.",
        ]
    else:
        concept = (concepts or [design_direction])[0] if (concepts or design_direction) else None
        if concept:
            lines += ["", f"CONCEPT: {concept}"]
        lines += [
            "",
            "OUTPUT: one complete HTML document. Compact CSS in one <style>: no comments, short "
            "class names, no unused rules. A Google Fonts <link> is allowed. No markdown, no prose.",
        ]
    return "\n".join(lines)


def _call_provider_with_retry(prompt, image_data_uri=None, max_tokens=None):
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            return generate_text(
                prompt, image_data_uri=image_data_uri, max_tokens=max_tokens, purpose="card"
            )
        except Exception as e:
            message = str(e)
            # Treat 429 as exhausted quota for this generation. Retrying every
            # variant immediately multiplies requests and cannot fix RPD/TPM.
            is_503 = "503" in message or "UNAVAILABLE" in message or "overloaded" in message.lower()
            if is_503 and attempt < max_attempts:
                time.sleep(2 * attempt)  # 2s, then 4s backoff
                continue
            raise


def _strip_fences(text):
    text = re.sub(r"```(?:html)?", "", text or "", flags=re.IGNORECASE)
    return text.strip()


def split_generated_cards(text, count):
    """Split a multi-card response into `count` HTML strings (None where missing)."""
    text = _strip_fences(text)
    parts = [
        part.strip() for part in re.split(r"<!--\s*CARD\s*\d*\s*-->", text, flags=re.IGNORECASE)
        if re.search(r"<(?:html|body|main|style)\b", part, re.IGNORECASE)
    ]
    if len(parts) < min(count, 2):
        documents = re.findall(
            r"(?:<!doctype html>\s*)?<html\b.*?(?:</html>|$)", text, flags=re.IGNORECASE | re.DOTALL
        )
        if len(documents) > len(parts):
            parts = [d.strip() for d in documents]
    return (parts + [None] * count)[:count]


def strip_card_size_overrides(template_html):
    """Remove styles injected by ensure_card_styling (saves tokens on edits)."""
    soup = BeautifulSoup(template_html, "lxml")
    for style in soup.find_all("style", attrs={CARD_SIZE_STYLE_ATTR: True}):
        style.decompose()
    return str(soup)


def _card_token_budget(count):
    per_card = getattr(settings, "AI_CARD_MAX_TOKENS_PER_VARIANT", 4000)
    return min(per_card * max(count, 1), 16000)


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

    card_fields = card_fields_for_category(category, company)
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


def _mock_allowed(provider, api_key, reference_image_url):
    return not api_key and provider == "gemini" and not reference_image_url


def _raise_for_missing_key(provider, api_key, reference_image_url):
    if api_key:
        return
    if reference_image_url and provider == "gemini":
        raise RuntimeError(
            "Reference image generation requires GEMINI_API_KEY. "
            "Configure the image generation service and try again."
        )
    # Let generate_text raise an actionable missing-key error.
    generate_text("")


def generate_card_variants(
    company,
    brand,
    category,
    directions,
    user_prompt=None,
    reference_image_url=None,
):
    """Generate several templates in ONE AI request.

    The design brief and any reference image are sent once for the whole batch
    instead of once per variant. Returns one HTML string (or None when the
    model returned nothing usable for that slot) per direction.
    """
    _, provider, api_key, _ = get_provider_config()
    if _mock_allowed(provider, api_key, reference_image_url):
        return [
            render_mock_card_template(company, brand, category, design_direction=d["key"])
            for d in directions
        ]
    _raise_for_missing_key(provider, api_key, reference_image_url)

    if reference_image_url:
        concepts = [REFERENCE_VARIATIONS[i % len(REFERENCE_VARIATIONS)] for i in range(len(directions))]
    else:
        concepts = [f"{d['label']}: {d['instruction']}" for d in directions]

    prompt = build_template_prompt(
        company,
        brand,
        category,
        user_prompt=user_prompt,
        has_reference_image=bool(reference_image_url),
        concepts=concepts,
    )
    raw = _call_provider_with_retry(
        prompt, image_data_uri=reference_image_url, max_tokens=_card_token_budget(len(directions))
    )
    if len(directions) == 1:
        return [_strip_fences(raw) or None]
    return split_generated_cards(raw, len(directions))


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
    Generate (or revise) one reusable card template.

    The generated HTML contains {{placeholder}} tokens.
    Those tokens are replaced only when rendering the preview
    or creating a real card.
    """
    _, provider, api_key, _ = get_provider_config()

    if previous_html:
        # Edit: send only the instruction, required tokens and the card itself
        # (without our injected sizing styles) instead of the whole design brief.
        width, height = _card_dimensions(category)
        tokens = ", ".join(
            card_placeholder(field) for field in card_fields_for_category(category, company)
        )
        prompt = (
            f"Revise this card template. Instruction: {extra_instruction or 'improve the design'}\n"
            f"Keep every token ({tokens}) exactly as written, the {width}x{height}px canvas "
            "and the brand colours unless the instruction says otherwise. Keep CSS compact. "
            "Return the complete revised HTML only, no markdown.\n\n"
            f"{strip_card_size_overrides(previous_html)}"
        )
    else:
        direction = next(
            (d for d in CARD_DESIGN_DIRECTIONS if d["key"] == design_direction), None
        )
        concept = (
            f"{direction['label']}: {direction['instruction']}" if direction else design_direction
        )
        if extra_instruction:
            concept = f"{concept}. {extra_instruction}" if concept else extra_instruction
        if _mock_allowed(provider, api_key, reference_image_url):
            return render_mock_card_template(
                company, brand, category, design_direction=design_direction
            )
        prompt = build_template_prompt(
            company,
            brand,
            category,
            user_prompt=user_prompt,
            has_reference_image=bool(reference_image_url),
            design_direction=concept,
        )

    _raise_for_missing_key(provider, api_key, reference_image_url)
    html = _call_provider_with_retry(
        prompt, image_data_uri=reference_image_url, max_tokens=_card_token_budget(1)
    )
    return _strip_fences(html)


def repair_missing_fields(template_html, required_fields):
    """Add any placeholder the model forgot into the card instead of
    discarding an otherwise good design (and paying for a regeneration)."""
    if not isinstance(template_html, str) or not template_html.strip():
        return template_html
    missing = [f for f in required_fields if card_placeholder(f) not in template_html]
    # Patch a few omissions only; a design missing most fields is not worth saving.
    if not missing or len(missing) > max(2, len(required_fields) // 3):
        return template_html

    soup = BeautifulSoup(template_html, "lxml")
    body = soup.body
    if body is None or not soup.find("style"):
        return template_html
    root = body.find(["main", "article", "section"]) or body.find(
        "div", class_=re.compile(r"\bcard\b", re.IGNORECASE)
    )
    if root is None:
        return template_html

    parts = []
    for field in missing:
        token = card_placeholder(field)
        if field == "photo":
            parts.append(f'<img class="mc-extra-photo" src="{token}" alt="Photo">')
        elif field == "qr_code":
            parts.append(f'<img class="mc-extra-qr" src="{token}" alt="QR code">')
        else:
            parts.append(
                f'<span class="mc-extra-item"><b>{escape(_field_label(field))}</b> {token}</span>'
            )
    extra = BeautifulSoup(f'<div class="mc-extra">{"".join(parts)}</div>', "html.parser")
    root.append(extra)

    style = soup.new_tag("style")
    style.string = (
        ".mc-extra{position:absolute;left:12px;right:12px;bottom:8px;display:flex;flex-wrap:wrap;"
        "align-items:center;gap:4px 10px;font-size:9px;line-height:1.3;opacity:.9;z-index:2}"
        ".mc-extra b{font-weight:700;opacity:.7;margin-right:3px}"
        ".mc-extra-photo{width:34px;height:42px;object-fit:cover;border-radius:4px}"
        ".mc-extra-qr{width:40px;height:40px;background:#fff;padding:3px;border-radius:4px}"
    )
    (soup.head or soup).append(style)
    return str(soup)


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

    width, height = _card_dimensions(category)

    head = soup.head
    if head is None:
        head = soup.new_tag("head")
        if body is None:
            body = soup.new_tag("body")
            soup.append(body)
        body.insert_before(head)

    if has_style_block or has_inline_card_style:
        # Drop overrides from earlier passes so they never accumulate.
        for previous in soup.find_all("style", attrs={CARD_SIZE_STYLE_ATTR: True}):
            previous.decompose()
        size_override = soup.new_tag("style", attrs={CARD_SIZE_STYLE_ATTR: "1"})
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
