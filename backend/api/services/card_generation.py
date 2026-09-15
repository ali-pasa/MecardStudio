# api/services/card_generation.py

import re
import json
import base64
from django.conf import settings


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

DEMO_DATA = {
    "full_name": "Jane Doe",
    "department": "Engineering",
    "id_number": "EMP-2024-0451",
    "valid_until": "31 Dec 2027",
    "photo_url": "https://placehold.co/200x250/e2e8f0/64748b?text=Photo",
    "qr_code_url": "https://placehold.co/150x150/ffffff/000000?text=QR",
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


def build_template_prompt(company, brand, category, user_prompt=None):
    required_fields = ", ".join(category.required_fields)

    base_context = f"""You are a professional card/badge template designer. Generate a
complete, self-contained HTML file (inline <style> only, no external
CSS/JS) for a reusable "{category.name}" TEMPLATE.

IMPORTANT — THIS IS A TEMPLATE, NOT A FILLED-IN CARD:
Do not invent sample data (no fake names, fake ID numbers, fake dates).
For every field below, insert the EXACT placeholder token shown —
these will be programmatically replaced with real data later.

FIELDS TO PLACE IN THE DESIGN (as literal placeholder tokens):
{required_fields}

CARD REQUIREMENTS:
- Aspect ratio: {category.default_aspect_ratio or "1.6:1"}
- Leave a clearly styled area for the QR code placeholder token
- Layout should look like a real ID/pass/card, not a form

FIXED BRAND DATA (use these as real, actual values — NOT placeholders):
- Company name: {company.company_name or "Company Name"}
- Logo URL: {brand.logo_url if brand and brand.logo_url else "none — use a text logo instead"}
- Primary color: {brand.primary_color if brand and brand.primary_color else "#2563eb"}
- Secondary color: {brand.secondary_color if brand and brand.secondary_color else "#1e293b"}
- Accent color: {brand.accent_color if brand and brand.accent_color else "#f59e0b"}
"""

    if user_prompt:
        base_context += f"\n\nUSER'S SPECIFIC DESIGN REQUEST: {user_prompt}\nIncorporate this into the design.\n"

    base_context += """
OUTPUT RULES:
- Return ONLY the HTML code — no explanation, no markdown code fences
- Use the brand colors meaningfully (background, accents, borders, text)
- Keep every {{placeholder}} token EXACTLY as given, character for character
- Make it look professional and polished
"""
    return base_context


def generate_card_template(
    company, brand, category,
    extra_instruction=None,
    previous_html=None,
    user_prompt=None,
    reference_image_url=None,   # either a real URL or a data: URI (base64)
):
    """
    Generates (or edits) a reusable card TEMPLATE.
    If reference_image_url is provided (a real image URL or a base64
    data: URI), the AI is shown this image to match style/layout from.
    """
    api_key = getattr(settings, "GEMINI_API_KEY", None)

    prompt = build_template_prompt(company, brand, category, user_prompt=user_prompt)

    if extra_instruction:
        prompt += f"\n\nADDITIONAL INSTRUCTION: {extra_instruction}\nApply this to the design above, keeping all placeholder tokens intact."

    if reference_image_url:
        prompt += "\n\nA REFERENCE IMAGE is attached — use it as visual/style inspiration (layout, color mood, general aesthetic) for this card design, while still using the FIXED BRAND DATA above for actual colors/logo."

    if previous_html:
        prompt += f"\n\nHere is the PREVIOUS TEMPLATE HTML to modify:\n{previous_html}\n"
        prompt += "Apply the instruction above to this existing template and return the full updated HTML, preserving all {{placeholder}} tokens."

    if not api_key:
        field_placeholders = "\n".join(
            f"<p><strong>{f}:</strong> {FIELD_TOKEN_MAP.get(f, '{{' + f + '}}')}</p>"
            for f in category.required_fields
        )
        return f"""<html><body style="font-family:sans-serif;padding:20px;
        border:2px dashed #ccc;width:340px;">
        <h3>{{{{company_name}}}}</h3>
        <p>{category.name} template (mock — no AI key set)</p>
        {field_placeholders}
        </body></html>"""

    from openai import OpenAI

    client = OpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )

    # Build multimodal message content if an image is provided
    if reference_image_url:
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": reference_image_url}},
        ]
    else:
        content = prompt

    response = client.chat.completions.create(
        model="gemini-3.6-flash",
        messages=[{"role": "user", "content": content}],
    )

    html = response.choices[0].message.content.strip()
    html = re.sub(r"^```html|^```|```$", "", html, flags=re.MULTILINE).strip()

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


def render_preview_html(template_html: str, category=None) -> str:
    """
    Fills a template's {{placeholder}} tokens with realistic DEMO data,
    purely for visual preview purposes. The stored template itself is
    never modified — this is a display-only transformation.
    """
    def replace_token(match):
        key = match.group(1).strip()
        return DEMO_DATA.get(key, key.replace("_", " ").title())

    return re.sub(r"\{\{(\w+)\}\}", replace_token, template_html)


def render_card_from_template(template_html: str, data: dict) -> str:
    """
    Fills a template with REAL data (for actual employee/record use later).
    """
    rendered = template_html
    for key, value in data.items():
        rendered = rendered.replace("{{" + key + "}}", str(value))
    return rendered