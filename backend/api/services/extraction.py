# api/services/extraction.py

import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from colorthief import ColorThief
from io import BytesIO
import json
from django.conf import settings

COLOR_PATTERN = re.compile(
    r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b"
    r"|rgba?\(\s*[\d.]+\s*,\s*[\d.]+\s*,\s*[\d.]+(?:\s*,\s*[\d.]+)?\s*\)",
    re.IGNORECASE,
)

SOCIAL_DOMAINS = {
    "linkedin.com": "linkedin_url",
    "instagram.com": "instagram_url",
    "facebook.com": "facebook_url",
    "youtube.com": "youtube_url",
    "twitter.com": "twitter_url",
    "x.com": "twitter_url",
}


def fetch_page(url: str) -> BeautifulSoup:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; MeCardStudioBot/1.0)"}
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    return BeautifulSoup(response.text, "lxml")


def extract_logo_url(soup: BeautifulSoup, base_url: str) -> str | None:
    def is_valid_image_url(u: str) -> bool:
        return bool(u) and u.startswith(("http://", "https://"))

    logo_meta = soup.find("meta", property=re.compile(r"^(og:logo|twitter:image:src)$", re.I))
    if logo_meta and logo_meta.get("content"):
        candidate = urljoin(base_url, logo_meta["content"])
        if is_valid_image_url(candidate):
            return candidate

    logo_image = soup.find(
        "img",
        attrs={
            "class": lambda value: value and any("logo" in item.lower() for item in (
                value if isinstance(value, list) else value.split()
            ))
        },
    )
    if logo_image and logo_image.get("src"):
        candidate = urljoin(base_url, logo_image["src"])
        if is_valid_image_url(candidate):
            return candidate

    logo_image = soup.find("img", alt=lambda value: value and "logo" in value.lower())
    if logo_image and logo_image.get("src"):
        candidate = urljoin(base_url, logo_image["src"])
        if is_valid_image_url(candidate):
            return candidate

    header = soup.find(["header", "nav"])
    if header:
        for img in header.find_all("img", src=True):
            candidate = urljoin(base_url, img["src"])
            if is_valid_image_url(candidate):
                return candidate

    icon_link = soup.find("link", rel=lambda value: value and "icon" in value.lower())
    if icon_link and icon_link.get("href"):
        candidate = urljoin(base_url, icon_link["href"])
        if is_valid_image_url(candidate):
            return candidate

    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        candidate = urljoin(base_url, og_image["content"])
        if is_valid_image_url(candidate):
            return candidate

    return None


def extract_social_links(soup: BeautifulSoup) -> dict:
    links = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        domain = urlparse(href).netloc.replace("www.", "")
        for social_domain, field_name in SOCIAL_DOMAINS.items():
            if social_domain in domain and field_name not in links:
                # Skip individual YouTube video links — only keep channel-style URLs
                if social_domain in ("youtube.com",) and "watch?v=" in href:
                    continue
                links[field_name] = href
    return links


def extract_dominant_colors(logo_url: str) -> dict:
    try:
        img_response = requests.get(logo_url, timeout=10)
        img_response.raise_for_status()
        color_thief = ColorThief(BytesIO(img_response.content))
        palette = color_thief.get_palette(color_count=3, quality=1)
        to_hex = lambda rgb: "#{:02x}{:02x}{:02x}".format(*rgb)
        return {
            "primary_color": to_hex(palette[0]) if len(palette) > 0 else None,
            "secondary_color": to_hex(palette[1]) if len(palette) > 1 else None,
            "accent_color": to_hex(palette[2]) if len(palette) > 2 else None,
        }
    except Exception:
        return {"primary_color": None, "secondary_color": None, "accent_color": None}


def normalize_color(value: str) -> str | None:
    value = value.strip()
    if value.startswith("#"):
        hex_value = value[1:]
        if len(hex_value) in (3, 4):
            hex_value = "".join(character * 2 for character in hex_value[:3])
        elif len(hex_value) == 8:
            hex_value = hex_value[:6]
        if len(hex_value) == 6:
            return f"#{hex_value.lower()}"
        return None

    rgb_match = re.fullmatch(
        r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)(?:\s*,\s*[\d.]+)?\s*\)",
        value,
        re.IGNORECASE,
    )
    if not rgb_match:
        return None
    channels = [max(0, min(255, round(float(channel)))) for channel in rgb_match.groups()]
    return "#{:02x}{:02x}{:02x}".format(*channels)


def extract_brand_colors(soup: BeautifulSoup, website_url: str, logo_url: str | None) -> dict:
    """Extract palette colors from site metadata/CSS, using the logo as fallback."""
    metadata = {}
    for meta in soup.find_all("meta"):
        name = (meta.get("name") or meta.get("property") or "").strip().lower()
        content = meta.get("content", "")
        if not content:
            continue
        field = None
        if name in (
            "theme-color", "msapplication-tilecolor", "brand-color",
            "primary-color", "color:primary", "og:primary_color",
            "brand:primary_color",
        ):
            field = "primary_color"
        elif name in ("secondary-color", "color:secondary", "brand:secondary_color"):
            field = "secondary_color"
        elif name in ("accent-color", "color:accent", "brand:accent_color"):
            field = "accent_color"

        color = normalize_color(content)
        if field and color and field not in metadata:
            metadata[field] = color

    stylesheets = []
    css_text = []
    for style in soup.find_all("style"):
        if style.string or style.get_text():
            css_text.append(style.string or style.get_text())
    for element in soup.find_all(attrs={"style": True}):
        css_text.append(element["style"])

    for link in soup.find_all("link", rel=lambda value: value and "stylesheet" in value):
        href = link.get("href")
        if href:
            stylesheets.append(urljoin(website_url, href))
    for stylesheet_url in stylesheets[:4]:
        try:
            response = requests.get(stylesheet_url, timeout=5)
            response.raise_for_status()
            css_text.append(response.text[:500_000])
        except requests.RequestException:
            continue

    named_colors = {}
    contextual_colors = []
    for stylesheet in css_text:
        for variable, value in re.findall(
            r"(--[\w-]*(?:brand|primary|secondary|accent|theme)[\w-]*)\s*:\s*([^;}]+)",
            stylesheet,
            re.IGNORECASE,
        ):
            variable = variable.lower()
            if "secondary" in variable:
                target = "secondary_color"
            elif "accent" in variable:
                target = "accent_color"
            elif "primary" in variable or "brand" in variable or "theme" in variable:
                target = "primary_color"
            else:
                continue
            color = next(
                (normalize_color(match.group()) for match in COLOR_PATTERN.finditer(value)
                 if normalize_color(match.group())),
                None,
            )
            if color:
                named_colors.setdefault(target, color)

        for rule in re.finditer(r"([^{}]+)\{([^{}]*)\}", stylesheet):
            selector, declarations = rule.groups()
            selector = selector.lower()
            if not any(term in selector for term in ("header", "nav", "button", ".brand", ".logo", ".primary", ".accent")):
                continue
            contextual_colors.extend(
                color
                for match in COLOR_PATTERN.finditer(declarations)
                if (color := normalize_color(match.group()))
            )

    image_colors = extract_dominant_colors(logo_url) if logo_url else {}
    result = {}
    for field in ("primary_color", "secondary_color", "accent_color"):
        result[field] = (
            metadata.get(field)
            or named_colors.get(field)
            or image_colors.get(field)
        )

    if contextual_colors:
        result["primary_color"] = metadata.get("primary_color") or named_colors.get("primary_color") or contextual_colors[0]
        if len(contextual_colors) > 1:
            result["accent_color"] = metadata.get("accent_color") or named_colors.get("accent_color") or contextual_colors[1]
    return result


def extract_company_name(soup: BeautifulSoup, website_url: str) -> str:
    site_name = soup.find("meta", property="og:site_name")
    if site_name and site_name.get("content", "").strip():
        return site_name["content"].strip()

    application_name = soup.find("meta", attrs={"name": "application-name"})
    if application_name and application_name.get("content", "").strip():
        return application_name["content"].strip()

    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if title:
        # Browser titles commonly append a tagline after a separator.
        return re.split(r"\s+[|–—-]\s+", title, maxsplit=1)[0].strip() or title

    heading = soup.find("h1")
    if heading:
        heading_text = heading.get_text(" ", strip=True)
        if heading_text:
            return heading_text

    host = urlparse(website_url).hostname or ""
    host = re.sub(r"^www\.", "", host, flags=re.IGNORECASE)
    domain_label = host.split(".", 1)[0]
    return domain_label.replace("-", " ").replace("_", " ").title() or "Unknown company"


def extract_company_info_with_ai(
    page_text: str,
    meta_description: str,
    fallback_company_name: str,
) -> dict:
    api_key = getattr(settings, "GEMINI_API_KEY", None)

    if not api_key:
        return {
            "company_name": fallback_company_name,
            "tagline": "",
            "about": meta_description,
            "industry": "",
            "address": "",
            "phone": "",
            "email": "",
        }

    from openai import OpenAI

    client = OpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )

    prompt = f"""Extract structured company information from this website content.
Return ONLY valid JSON, no other text, matching this exact schema:
{{
  "company_name": "",
  "tagline": "",
  "about": "",
  "industry": "",
  "address": "",
  "phone": "",
  "email": ""
}}

Meta description: {meta_description}

Page content:
{page_text[:6000]}
"""

    response = client.chat.completions.create(
        model="gemini-3.6-flash",
        messages=[{"role": "user", "content": prompt}],
    )

    raw_text = response.choices[0].message.content.strip()
    raw_text = re.sub(r"^```json|```$", "", raw_text, flags=re.MULTILINE).strip()

    try:
        company_info = json.loads(raw_text)
    except json.JSONDecodeError:
        company_info = {}

    if not isinstance(company_info, dict):
        company_info = {}
    company_info["company_name"] = (
        company_info.get("company_name") or fallback_company_name
    )
    return company_info


def run_full_extraction(website_url: str) -> dict:
    soup = fetch_page(website_url)

    meta_desc_tag = soup.find("meta", attrs={"name": "description"})
    meta_description = meta_desc_tag["content"] if meta_desc_tag else ""
    page_text = soup.get_text(separator=" ", strip=True)
    fallback_company_name = extract_company_name(soup, website_url)

    logo_url = extract_logo_url(soup, website_url)
    social_links = extract_social_links(soup)
    colors = extract_brand_colors(soup, website_url, logo_url)
    company_info = extract_company_info_with_ai(
        page_text,
        meta_description,
        fallback_company_name,
    )

    return {
        "company_info": company_info,
        "social_links": social_links,
        "brand": {"logo_url": logo_url, **colors},
    }