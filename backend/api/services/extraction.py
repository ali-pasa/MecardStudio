# api/services/extraction.py

import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from colorthief import ColorThief
from io import BytesIO
import json
from django.conf import settings

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

    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        candidate = urljoin(base_url, og_image["content"])
        if is_valid_image_url(candidate):
            return candidate

    icon_link = soup.find("link", rel=lambda v: v and "icon" in v.lower())
    if icon_link and icon_link.get("href"):
        candidate = urljoin(base_url, icon_link["href"])
        if is_valid_image_url(candidate):
            return candidate

    header = soup.find(["header", "nav"])
    if header:
        img = header.find("img")
        if img and img.get("src"):
            candidate = urljoin(base_url, img["src"])
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


def extract_company_info_with_ai(page_text: str, meta_description: str) -> dict:
    api_key = getattr(settings, "GEMINI_API_KEY", None)

    if not api_key:
        return {
            "company_name": "Test Company (mock data)",
            "tagline": "Placeholder — no GEMINI_API_KEY set",
            "about": meta_description or "No description found.",
            "industry": "Unknown",
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
        return json.loads(raw_text)
    except json.JSONDecodeError:
        return {}


def run_full_extraction(website_url: str) -> dict:
    soup = fetch_page(website_url)

    meta_desc_tag = soup.find("meta", attrs={"name": "description"})
    meta_description = meta_desc_tag["content"] if meta_desc_tag else ""
    page_text = soup.get_text(separator=" ", strip=True)

    logo_url = extract_logo_url(soup, website_url)
    social_links = extract_social_links(soup)
    colors = extract_dominant_colors(logo_url) if logo_url else {}
    company_info = extract_company_info_with_ai(page_text, meta_description)

    return {
        "company_info": company_info,
        "social_links": social_links,
        "brand": {"logo_url": logo_url, **colors},
    }