# api/services/extraction.py
"""
Website -> company/brand extraction for card generation.

Pipeline (designed to minimise latency and AI tokens):
  1. Fetch the homepage once (size-capped, connection-pooled).
  2. Pull everything we can *deterministically*: JSON-LD (schema.org),
     OpenGraph/meta tags, tel:/mailto: links, <address>, social links,
     logo, fonts and colours.
  3. Fetch secondary resources in parallel: stylesheets, the logo image and
     (only if contact details are still missing) the contact page.
  4. Ask the AI only for fields that are still missing, sending a compact,
     de-duplicated text digest (no scripts/CSS/nav noise) instead of raw page
     text. Results are cached by prompt hash, and failures degrade gracefully.
"""

import hashlib
import json
import re
import logging
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from colorthief import ColorThief
from django.conf import settings
from django.core.cache import cache
from requests.adapters import HTTPAdapter

from .ai_provider import generate_text, provider_has_api_key

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; MeCardStudioBot/1.0)"
REQUEST_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
PAGE_TIMEOUT = (5, 10)        # (connect, read) seconds
ASSET_TIMEOUT = (4, 6)
MAX_PAGE_BYTES = 3_000_000
MAX_CSS_BYTES = 600_000
MAX_IMAGE_BYTES = 2_000_000
MAX_STYLESHEETS = 4
AI_TEXT_BUDGET = 2500         # characters of page digest sent to the AI
AI_CACHE_SECONDS = 60 * 60 * 24

# Max lengths of the Company / CompanyBrandPreference columns.
FIELD_LIMITS = {
    "company_name": 255, "tagline": 255, "industry": 150, "address": 500,
    "phone": 50, "email": 255, "font_family": 150, "brand_style": 100,
    "about": 2000,
}

COLOR_PATTERN = re.compile(
    r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b"
    r"|rgba?\(\s*[\d.]+\s*,\s*[\d.]+\s*,\s*[\d.]+(?:\s*,\s*[\d.]+)?\s*\)",
    re.IGNORECASE,
)
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}")
PHONE_PATTERN = re.compile(r"(?:\+|00)?\d[\d\s().-]{7,18}\d")
JUNK_EMAIL = re.compile(
    r"(example\.|sentry|wixpress|@\d+x\.|\.(png|jpe?g|gif|svg|webp)$|noreply|no-reply)",
    re.IGNORECASE,
)

# Domains mapped to Company model columns.
SOCIAL_DOMAINS = {
    "linkedin.com": "linkedin_url",
    "instagram.com": "instagram_url",
    "facebook.com": "facebook_url",
    "fb.com": "facebook_url",
    "youtube.com": "youtube_url",
    "youtu.be": "youtube_url",
    "twitter.com": "twitter_url",
    "x.com": "twitter_url",
}
# Extra profiles kept in Company.meta_data (no dedicated columns).
EXTRA_SOCIAL_DOMAINS = {
    "tiktok.com": "tiktok", "github.com": "github", "pinterest.com": "pinterest",
    "threads.net": "threads", "behance.net": "behance", "dribbble.com": "dribbble",
    "t.me": "telegram", "snapchat.com": "snapchat", "wa.me": "whatsapp",
    "api.whatsapp.com": "whatsapp", "whatsapp.com": "whatsapp",
}
SHARE_LINK = re.compile(
    r"/(sharer|share|intent|shareArticle|dialog|plugins|hashtag|watch\?)", re.IGNORECASE
)

GENERIC_FONTS = {
    "serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui",
    "ui-sans-serif", "ui-serif", "ui-monospace", "ui-rounded", "inherit",
    "initial", "unset", "-apple-system", "blinkmacsystemfont", "segoe ui",
    "emoji", "math", "fangsong", "apple color emoji", "segoe ui emoji",
    "segoe ui symbol", "noto color emoji",
}
ICON_FONT = re.compile(r"(awesome|icon|glyph|dashicons|eicons|material symbols|fa-)", re.I)

AI_FIELDS_SPEC = {
    "company_name": "official brand name only (no slogans)",
    "tagline": "short slogan, max 10 words",
    "about": "1-2 sentence description, max 250 chars",
    "industry": "1-4 words",
    "address": "full postal address of HQ/main office",
    "phone": "main phone with country code if shown",
    "email": "main public contact email",
    "brand_style": "2-4 words describing the visual brand tone, e.g. 'modern minimal', 'luxury classic'",
}


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

def _new_session() -> requests.Session:
    session = requests.Session()
    adapter = HTTPAdapter(pool_connections=4, pool_maxsize=8, max_retries=1)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(REQUEST_HEADERS)
    return session


def normalize_website_url(url: str) -> str:
    url = (url or "").strip()
    if url and not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url.lstrip("/")
    return url


def _get_bytes(session, url, *, timeout, max_bytes) -> tuple[bytes, str]:
    """GET with a hard size cap; returns (body, final_url)."""
    with session.get(url, timeout=timeout, stream=True, allow_redirects=True) as response:
        response.raise_for_status()
        chunks, size = [], 0
        for chunk in response.iter_content(65536):
            chunks.append(chunk)
            size += len(chunk)
            if size >= max_bytes:
                break
        return b"".join(chunks)[:max_bytes], response.url


def fetch_page(url: str, session=None) -> tuple[BeautifulSoup, str]:
    """Return (soup, final_url). Passing bytes lets the parser honour <meta charset>."""
    session = session or _new_session()
    body, final_url = _get_bytes(session, url, timeout=PAGE_TIMEOUT, max_bytes=MAX_PAGE_BYTES)
    return BeautifulSoup(body, "lxml"), final_url


def _safe_fetch(session, url, *, timeout=ASSET_TIMEOUT, max_bytes=MAX_CSS_BYTES):
    try:
        return _get_bytes(session, url, timeout=timeout, max_bytes=max_bytes)[0]
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def _clean(value, limit=None) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = next((v for v in value if isinstance(v, str) and v.strip()), "")
    if not isinstance(value, str):
        return ""
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit].rstrip() if limit else value


def _clamp(field, value) -> str:
    return _clean(value, FIELD_LIMITS.get(field))


def _is_http_url(url: str) -> bool:
    return bool(url) and url.startswith(("http://", "https://"))


def _meta(soup, *names) -> str:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if tag and _clean(tag.get("content")):
            return _clean(tag.get("content"))
    return ""


def _host(url: str) -> str:
    return re.sub(r"^www\.", "", (urlparse(url).hostname or "").lower())


# --------------------------------------------------------------------------- #
# JSON-LD (schema.org) — the richest structured source when present
# --------------------------------------------------------------------------- #

ORG_TYPES = re.compile(
    r"(Organization|Corporation|LocalBusiness|Store|Restaurant|Hotel|Company|"
    r"MedicalOrganization|EducationalOrganization|NGO|ProfessionalService|"
    r"Brand|Dentist|Physician|Hospital|Clinic|LegalService|Airline|SportsClub)",
    re.IGNORECASE,
)


# Too generic to be useful as an "industry".
GENERIC_ORG_TYPES = {
    "Organization", "WebSite", "Corporation", "LocalBusiness", "Company", "Brand",
    "NGO", "ProfessionalService", "Store", "OnlineBusiness", "OnlineStore", "Thing",
}


def _iter_jsonld_nodes(data):
    if isinstance(data, list):
        for item in data:
            yield from _iter_jsonld_nodes(item)
    elif isinstance(data, dict):
        yield data
        for key in ("@graph", "publisher", "provider", "brand", "author", "organization"):
            if key in data:
                yield from _iter_jsonld_nodes(data[key])


def extract_jsonld(soup: BeautifulSoup, base_url: str) -> dict:
    """Return the best schema.org Organization-like node, flattened."""
    best, best_score = None, -1
    for script in soup.find_all("script", type=re.compile(r"ld\+json", re.I)):
        raw = script.string or script.get_text() or ""
        try:
            data = json.loads(raw.strip())
        except (ValueError, TypeError):
            continue
        for node in _iter_jsonld_nodes(data):
            types = node.get("@type") or ""
            types = " ".join(types) if isinstance(types, list) else str(types)
            if not ORG_TYPES.search(types) and types != "WebSite":
                continue
            score = sum(1 for k in ("name", "logo", "telephone", "email", "address", "sameAs") if node.get(k))
            score += 3 if ORG_TYPES.search(types) else 0
            if score > best_score:
                best, best_score = node, score
    if not best:
        return {}

    types = best.get("@type")
    types = types if isinstance(types, list) else [types]
    result = {
        "company_name": _clean(best.get("name") or best.get("legalName")),
        "about": _clean(best.get("description")),
        "tagline": _clean(best.get("slogan")),
        "phone": _clean(best.get("telephone")),
        "email": _clean(best.get("email")).replace("mailto:", ""),
        "same_as": [],
        "jsonld_type": next((str(t) for t in types if t and str(t) not in GENERIC_ORG_TYPES), ""),
    }

    logo = best.get("logo") or best.get("image")
    if isinstance(logo, list):
        logo = logo[0] if logo else None
    if isinstance(logo, dict):
        logo = logo.get("url") or logo.get("contentUrl")
    if isinstance(logo, str) and logo.strip():
        result["logo_url"] = urljoin(base_url, logo.strip())

    address = best.get("address")
    if isinstance(address, list):
        address = address[0] if address else None
    if isinstance(address, dict):
        parts = [
            address.get("streetAddress"), address.get("addressLocality"),
            address.get("addressRegion"), address.get("postalCode"),
        ]
        country = address.get("addressCountry")
        if isinstance(country, dict):
            country = country.get("name")
        parts.append(country)
        result["address"] = ", ".join(_clean(p) for p in parts if _clean(p))
    elif isinstance(address, str):
        result["address"] = _clean(address)

    same_as = best.get("sameAs") or []
    if isinstance(same_as, str):
        same_as = [same_as]
    result["same_as"] = [u for u in same_as if isinstance(u, str) and _is_http_url(u)]

    contact = best.get("contactPoint")
    if isinstance(contact, list):
        contact = contact[0] if contact else None
    if isinstance(contact, dict):
        result["phone"] = result["phone"] or _clean(contact.get("telephone"))
        result["email"] = result["email"] or _clean(contact.get("email")).replace("mailto:", "")
    return {k: v for k, v in result.items() if v}


# --------------------------------------------------------------------------- #
# Logo, socials, contacts, fonts
# --------------------------------------------------------------------------- #

def _has_logo_hint(tag) -> bool:
    attrs = " ".join(
        " ".join(v) if isinstance(v, list) else str(v)
        for k, v in tag.attrs.items() if k in ("class", "id", "alt", "src", "data-src", "title")
    ).lower()
    return "logo" in attrs


def _img_src(img, base_url):
    src = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
    if not src and img.get("srcset"):
        src = img["srcset"].split(",")[0].strip().split(" ")[0]
    if not src or src.startswith("data:"):
        return None
    candidate = urljoin(base_url, src)
    return candidate if _is_http_url(candidate) else None


def extract_logo_url(soup: BeautifulSoup, base_url: str, jsonld: dict | None = None) -> str | None:
    jsonld = jsonld or {}
    if _is_http_url(jsonld.get("logo_url", "")):
        return jsonld["logo_url"]

    og_logo = _meta(soup, "og:logo")
    if og_logo:
        candidate = urljoin(base_url, og_logo)
        if _is_http_url(candidate):
            return candidate

    # A logo-hinted <img> inside the header/nav is the strongest DOM signal,
    # then any logo-hinted <img>, then the image inside the "home" link.
    regions = [r for r in soup.find_all(["header", "nav"], limit=3)] + [soup]
    for region in regions:
        for img in region.find_all("img", limit=40):
            if _has_logo_hint(img) or (img.parent and img.parent.name == "a" and _has_logo_hint(img.parent)):
                candidate = _img_src(img, base_url)
                if candidate:
                    return candidate

    for anchor in soup.find_all("a", href=True, limit=60):
        if urlparse(urljoin(base_url, anchor["href"])).path in ("", "/"):
            img = anchor.find("img")
            candidate = _img_src(img, base_url) if img else None
            if candidate:
                return candidate

    header = soup.find(["header", "nav"])
    if header:
        img = header.find("img")
        candidate = _img_src(img, base_url) if img else None
        if candidate:
            return candidate

    # Icons: prefer high-resolution apple-touch-icon over tiny favicons.
    icons = []
    for link in soup.find_all("link", href=True):
        rel = " ".join(link.get("rel") or []).lower()
        if "icon" not in rel:
            continue
        sizes = link.get("sizes") or ""
        size = max((int(n) for n in re.findall(r"\d+", sizes)), default=0)
        score = size + (500 if "apple-touch" in rel else 0) + (300 if link["href"].endswith(".svg") else 0)
        icons.append((score, urljoin(base_url, link["href"])))
    for _, candidate in sorted(icons, reverse=True):
        if _is_http_url(candidate):
            return candidate

    og_image = _meta(soup, "og:image", "twitter:image", "twitter:image:src")
    if og_image:
        candidate = urljoin(base_url, og_image)
        if _is_http_url(candidate):
            return candidate
    return None


def _classify_social(href: str):
    domain = _host(href)
    if not domain or SHARE_LINK.search(href):
        return None, None
    for social_domain, field in SOCIAL_DOMAINS.items():
        if domain == social_domain or domain.endswith("." + social_domain):
            path = urlparse(href).path.strip("/")
            if not path:  # bare domain, not a profile
                return None, None
            return "core", field
    for social_domain, key in EXTRA_SOCIAL_DOMAINS.items():
        if domain == social_domain or domain.endswith("." + social_domain):
            return "extra", key
    return None, None


def extract_social_links(soup: BeautifulSoup, same_as=None, extras: dict | None = None) -> dict:
    """Core social URLs for Company columns; other profiles go into `extras`."""
    links = {}
    hrefs = list(same_as or []) + [a["href"] for a in soup.find_all("a", href=True)]
    for href in hrefs:
        href = href.strip()
        if not _is_http_url(href):
            continue
        kind, key = _classify_social(href)
        if kind == "core" and key not in links:
            links[key] = href[:500]
        elif kind == "extra" and extras is not None:
            extras.setdefault(key, href[:500])
    return links


def extract_contacts(soup: BeautifulSoup) -> dict:
    """Phones/emails from tel:/mailto: links, <address> blocks and footer text."""
    phones, emails = [], []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        lower = href.lower()
        if lower.startswith("tel:"):
            phone = _clean(re.sub(r"^tel:", "", href, flags=re.I).split("?")[0])
            if len(re.sub(r"\D", "", phone)) >= 6:
                phones.append(phone)
        elif lower.startswith("mailto:"):
            email = href[7:].split("?")[0].strip()
            if EMAIL_PATTERN.fullmatch(email) and not JUNK_EMAIL.search(email):
                emails.append(email.lower())

    address = ""
    address_tag = soup.find("address")
    if address_tag:
        address = _clean(address_tag.get_text(" ", strip=True))

    # Footer/contact blocks are where visible contact details usually live.
    footer_text = " ".join(
        f.get_text(" ", strip=True)
        for f in soup.find_all(["footer", "address"], limit=3)
    )
    if not emails:
        emails = [
            e.lower() for e in EMAIL_PATTERN.findall(footer_text)
            if not JUNK_EMAIL.search(e)
        ]
    if not phones:
        for match in PHONE_PATTERN.findall(footer_text):
            digits = re.sub(r"\D", "", match)
            # Avoid years/postcodes/ID numbers: require a plausible phone length.
            if 8 <= len(digits) <= 15 and not re.fullmatch(r"(19|20)\d{2}\D*(19|20)\d{2}", match.strip()):
                phones.append(_clean(match))

    return {
        "phones": list(dict.fromkeys(phones))[:3],
        "emails": list(dict.fromkeys(emails))[:3],
        "address": address if 10 <= len(address) <= 500 else "",
    }


def _first_real_font(value: str) -> str:
    for family in value.split(","):
        family = family.strip().strip("'\"").strip()
        if not family or family.lower() in GENERIC_FONTS or family.startswith("var("):
            continue
        if ICON_FONT.search(family) or family.startswith("--"):
            continue
        # Reject sizes/weights/keywords picked up from font shorthands or size variables.
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9 \-]{1,60}", family) or re.search(
            r"\d+(px|em|rem|pt|%)|^(bold|normal|italic|light|\d+)$", family, re.I
        ):
            continue
        return family
    return ""


def extract_font_family(soup: BeautifulSoup, css_texts: list[str]) -> str:
    # Google Fonts links are explicit and reliable.
    for link in soup.find_all("link", href=True):
        href = link["href"]
        if "fonts.googleapis.com" in href:
            match = re.search(r"family=([^:&|]+)", href)
            if match:
                family = _first_real_font(match.group(1).replace("+", " "))
                if family:
                    return family

    css = "\n".join(css_texts)
    for pattern in (
        r"--[\w-]*font[\w-]*(?:primary|body|base|heading|sans|main)[\w-]*\s*:\s*([^;}]+)",
        r"(?:^|[}\s,])(?:body|html|:root)\s*\{[^}]*?font-family\s*:\s*([^;}]+)",
        r"(?:^|[}\s,])h1[^{]*\{[^}]*?font-family\s*:\s*([^;}]+)",
        r"font-family\s*:\s*([^;}]+)",
    ):
        for match in re.finditer(pattern, css, re.IGNORECASE):
            family = _first_real_font(match.group(1))
            if family:
                return family
    return ""


def extract_company_name(soup: BeautifulSoup, website_url: str) -> str:
    site_name = _meta(soup, "og:site_name", "application-name", "apple-mobile-web-app-title")
    if site_name:
        return site_name

    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if title and title.lower() not in ("home", "homepage", "welcome", "index"):
        # Browser titles commonly append a tagline after a separator.
        return re.split(r"\s+[|–—:·-]\s+", title, maxsplit=1)[0].strip() or title

    heading = soup.find("h1")
    if heading:
        heading_text = heading.get_text(" ", strip=True)
        if heading_text and len(heading_text) <= 60:
            return heading_text

    host = _host(website_url)
    domain_label = host.split(".", 1)[0]
    return domain_label.replace("-", " ").replace("_", " ").title() or "Unknown company"


def _find_contact_url(soup: BeautifulSoup, base_url: str) -> str | None:
    base_host = _host(base_url)
    best = None
    for a in soup.find_all("a", href=True):
        url = urljoin(base_url, a["href"]).split("#")[0]
        if not _is_http_url(url) or _host(url) != base_host:
            continue
        label = f"{urlparse(url).path} {a.get_text(' ', strip=True)}".lower()
        if re.search(r"contact|get-in-touch|reach-us|locations?", label):
            return url
        if best is None and re.search(r"about", label):
            best = url
    return best


# --------------------------------------------------------------------------- #
# Colours
# --------------------------------------------------------------------------- #

def normalize_color(value: str) -> str | None:
    value = value.strip()
    if value.startswith("#"):
        hex_value = value[1:]
        if len(hex_value) in (3, 4):
            hex_value = "".join(character * 2 for character in hex_value[:3])
        elif len(hex_value) == 8:
            hex_value = hex_value[:6]
        if len(hex_value) == 6 and re.fullmatch(r"[0-9a-fA-F]{6}", hex_value):
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


def _is_neutral(hex_color: str) -> bool:
    """White/black/grey colours make poor brand colours."""
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return max(r, g, b) - min(r, g, b) < 24 or max(r, g, b) < 20 or min(r, g, b) > 240


def _luminance(hex_color: str) -> float:
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _dominant_colors_from_bytes(data: bytes, content_hint: str = "") -> list[str]:
    if not data:
        return []
    head = data[:400].lstrip().lower()
    if content_hint.endswith(".svg") or head.startswith(b"<svg") or b"<svg" in head:
        text = data.decode("utf-8", "ignore")
        counts = {}
        for match in COLOR_PATTERN.finditer(text):
            color = normalize_color(match.group())
            if color:
                counts[color] = counts.get(color, 0) + 1
        return [c for c, _ in sorted(counts.items(), key=lambda kv: -kv[1])]
    try:
        from PIL import Image
        image = Image.open(BytesIO(data))
        image.thumbnail((160, 160))           # ColorThief is O(pixels): shrink first
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA")
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        palette = ColorThief(buffer).get_palette(color_count=5, quality=3)
        return ["#{:02x}{:02x}{:02x}".format(*rgb) for rgb in palette]
    except Exception:
        return []


def extract_dominant_colors(logo_url: str, logo_bytes: bytes | None = None) -> dict:
    if logo_bytes is None and logo_url:
        logo_bytes = _safe_fetch(_new_session(), logo_url, max_bytes=MAX_IMAGE_BYTES)
    palette = _dominant_colors_from_bytes(logo_bytes or b"", (logo_url or "").lower().split("?")[0])
    branded = [c for c in palette if not _is_neutral(c)] + [c for c in palette if _is_neutral(c)]
    return {
        "primary_color": branded[0] if len(branded) > 0 else None,
        "secondary_color": branded[1] if len(branded) > 1 else None,
        "accent_color": branded[2] if len(branded) > 2 else None,
    }


def _stylesheet_urls(soup: BeautifulSoup, base_url: str) -> list[str]:
    urls = []
    for link in soup.find_all("link", href=True):
        rel = " ".join(link.get("rel") or []).lower()
        href = link["href"]
        if "stylesheet" not in rel or "fonts.googleapis.com" in href:
            continue
        url = urljoin(base_url, href)
        # Skip well-known third-party/plugin CSS; it never carries the brand palette.
        if re.search(r"(bootstrap|font-?awesome|jquery|swiper|slick|animate|cookie|gtm|recaptcha)", url, re.I):
            continue
        if _is_http_url(url):
            urls.append(url)
    return urls[:MAX_STYLESHEETS]


def extract_brand_colors(
    soup: BeautifulSoup,
    website_url: str,
    logo_url: str | None,
    external_css: list[str] | None = None,
    logo_bytes: bytes | None = None,
) -> dict:
    """Extract palette colours from site metadata/CSS, using the logo as fallback.

    `external_css` / `logo_bytes` may be pre-fetched (in parallel) by the caller;
    when omitted they are fetched here.
    """
    metadata = {}
    meta_fields = {
        "primary_color": (
            "theme-color", "msapplication-tilecolor", "brand-color", "primary-color",
            "color:primary", "og:primary_color", "brand:primary_color",
        ),
        "secondary_color": ("secondary-color", "color:secondary", "brand:secondary_color"),
        "accent_color": ("accent-color", "color:accent", "brand:accent_color"),
    }
    for meta in soup.find_all("meta"):
        name = (meta.get("name") or meta.get("property") or "").strip().lower()
        color = normalize_color(meta.get("content", "") or "")
        if not color or _is_neutral(color):
            continue
        for field, names in meta_fields.items():
            if name in names:
                metadata.setdefault(field, color)

    css_text = [s.string or s.get_text() for s in soup.find_all("style")]
    css_text += [el["style"] for el in soup.find_all(attrs={"style": True}, limit=300)]
    if external_css is None:
        session = _new_session()
        external_css = [
            body.decode("utf-8", "ignore") for body in
            (_safe_fetch(session, url) for url in _stylesheet_urls(soup, website_url)) if body
        ]
    css_text += external_css

    named_colors = {}
    contextual_counts = {}
    for stylesheet in css_text:
        if not stylesheet:
            continue
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
            else:
                target = "primary_color"
            color = next(
                (c for m in COLOR_PATTERN.finditer(value) if (c := normalize_color(m.group()))),
                None,
            )
            if color and not _is_neutral(color):
                named_colors.setdefault(target, color)

        for rule in re.finditer(r"([^{}]+)\{([^{}]*)\}", stylesheet):
            selector, declarations = rule.groups()
            selector = selector.lower()
            if not any(term in selector for term in (
                "header", "nav", "button", ".btn", ".brand", ".logo", ".primary", ".accent", ".cta"
            )):
                continue
            for match in COLOR_PATTERN.finditer(declarations):
                color = normalize_color(match.group())
                if color and not _is_neutral(color):
                    contextual_counts[color] = contextual_counts.get(color, 0) + 1

    contextual = [c for c, _ in sorted(contextual_counts.items(), key=lambda kv: -kv[1])]

    result = {
        field: metadata.get(field) or named_colors.get(field)
        for field in ("primary_color", "secondary_color", "accent_color")
    }
    if not result["primary_color"] and contextual:
        result["primary_color"] = contextual[0]
    if not result["accent_color"]:
        result["accent_color"] = next((c for c in contextual if c not in result.values()), None)

    # Only analyse the logo when CSS/metadata left gaps.
    if logo_url and not all(result.values()):
        if logo_bytes is None:
            logo_bytes = _safe_fetch(_new_session(), logo_url, max_bytes=MAX_IMAGE_BYTES)
        palette = _dominant_colors_from_bytes(logo_bytes or b"", logo_url.lower().split("?")[0])
        # Brand hues first, then dark neutrals (fine as "ink"); never near-white.
        ranked = [c for c in palette if not _is_neutral(c)] + [
            c for c in palette if _is_neutral(c) and _luminance(c) < 0.5
        ]
        used = {c for c in result.values() if c}
        candidates = iter(c for c in ranked if c not in used)
        for field in ("primary_color", "secondary_color", "accent_color"):
            if not result[field]:
                result[field] = next(candidates, None)
    return result


# --------------------------------------------------------------------------- #
# AI (only for gaps)
# --------------------------------------------------------------------------- #

NOISE_TAGS = ["script", "style", "noscript", "svg", "template", "iframe", "canvas", "form", "select"]


def build_page_digest(soup: BeautifulSoup, extra_soups=(), budget: int = AI_TEXT_BUDGET) -> str:
    """Compact, de-duplicated text: headings, hero copy, about & footer/contact text."""
    lines, seen = [], set()

    def add(text, max_len=300):
        text = _clean(text)
        if len(text) < 3:
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        lines.append(text[:max_len])

    for page in (soup, *extra_soups):
        for tag in page(NOISE_TAGS):
            tag.decompose()
        body = page.body or page
        for el in body.find_all(["h1", "h2", "h3"], limit=12):
            add(el.get_text(" ", strip=True), 160)
        for el in body.find_all(["p", "li"], limit=80):
            text = el.get_text(" ", strip=True)
            if 40 <= len(text) or re.search(r"\d{3}|@|street|road|ave|suite|floor", text, re.I):
                add(text)
        for el in body.find_all(["address", "footer"], limit=3):
            add(el.get_text(" | ", strip=True), 600)

    digest, total = [], 0
    for line in lines:
        if total + len(line) > budget:
            break
        digest.append(line)
        total += len(line) + 1
    return "\n".join(digest)


def _parse_json_object(raw: str) -> dict:
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    try:
        data = json.loads(raw)
    except ValueError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        try:
            data = json.loads(match.group()) if match else {}
        except ValueError:
            data = {}
    return data if isinstance(data, dict) else {}


def extract_company_info_with_ai(
    page_text: str,
    meta_description: str,
    fallback_company_name: str,
    missing_fields=None,
    known: dict | None = None,
) -> dict:
    """Ask the AI only for `missing_fields`; never raises."""
    fields = [f for f in (missing_fields or AI_FIELDS_SPEC) if f in AI_FIELDS_SPEC]
    base = {"company_name": fallback_company_name, "about": meta_description}
    if not fields or not provider_has_api_key():
        return base

    known_lines = "\n".join(f"{k}: {v}" for k, v in (known or {}).items() if v)
    schema = "\n".join(f'"{f}": {AI_FIELDS_SPEC[f]}' for f in fields)
    prompt = (
        "Extract company facts from this website text. Reply with ONE minified JSON "
        "object with exactly these keys; use \"\" when not stated (never guess contact "
        f"details).\n{schema}\n\n"
        f"Known: {known_lines or 'n/a'}\n"
        f"Meta description: {meta_description or 'n/a'}\n"
        f"Text:\n{page_text[:AI_TEXT_BUDGET]}"
    )

    cache_key = "extract:" + hashlib.sha256(prompt.encode()).hexdigest()
    data = cache.get(cache_key)
    if data is None:
        try:
            raw = generate_text(
                prompt,
                max_tokens=getattr(settings, "AI_EXTRACTION_MAX_TOKENS", 600),
                purpose="extraction",
            )
            data = _parse_json_object(raw)
            if data:
                cache.set(cache_key, data, AI_CACHE_SECONDS)
        except Exception:
            logger.warning("AI company extraction failed; using deterministic data only.", exc_info=True)
            data = {}

    result = dict(base)
    for field in fields:
        value = data.get(field)
        if isinstance(value, str) and value.strip():
            result[field] = value.strip()
    result["company_name"] = result.get("company_name") or fallback_company_name
    return result


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def run_full_extraction(website_url: str) -> dict:
    session = _new_session()
    website_url = normalize_website_url(website_url)
    soup, base_url = fetch_page(website_url, session)

    meta_description = _meta(soup, "description", "og:description", "twitter:description")
    if not soup.get_text(strip=True) and not meta_description:
        raise ValueError("No company information could be fetched from that URL.")

    # ---- 1. deterministic extraction on the homepage ------------------------
    jsonld = extract_jsonld(soup, base_url)
    contacts = extract_contacts(soup)
    extras = {}
    social_links = extract_social_links(soup, jsonld.get("same_as"), extras)
    logo_url = extract_logo_url(soup, base_url, jsonld)

    name_is_confident = bool(jsonld.get("company_name") or _meta(soup, "og:site_name", "application-name"))
    company_name = jsonld.get("company_name") or extract_company_name(soup, base_url)

    info = {
        "company_name": company_name,
        "tagline": jsonld.get("tagline", ""),
        "about": jsonld.get("about") or meta_description,
        "industry": "",
        "address": jsonld.get("address") or contacts["address"],
        "phone": jsonld.get("phone") or (contacts["phones"][0] if contacts["phones"] else ""),
        "email": jsonld.get("email") or (contacts["emails"][0] if contacts["emails"] else ""),
    }

    # ---- 2. secondary fetches in parallel ------------------------------------
    need_contact_page = not (info["phone"] and info["email"] and info["address"])
    contact_url = _find_contact_url(soup, base_url) if need_contact_page else None
    css_urls = _stylesheet_urls(soup, base_url)

    with ThreadPoolExecutor(max_workers=6) as pool:
        css_futures = [pool.submit(_safe_fetch, session, url) for url in css_urls]
        logo_future = (
            pool.submit(_safe_fetch, session, logo_url, max_bytes=MAX_IMAGE_BYTES)
            if logo_url else None
        )
        contact_future = (
            pool.submit(_safe_fetch, session, contact_url, timeout=PAGE_TIMEOUT, max_bytes=MAX_PAGE_BYTES)
            if contact_url else None
        )
        external_css = [
            body.decode("utf-8", "ignore") for body in (f.result() for f in css_futures) if body
        ]
        logo_bytes = logo_future.result() if logo_future else None
        contact_body = contact_future.result() if contact_future else None

    extra_soups = []
    if contact_body:
        contact_soup = BeautifulSoup(contact_body, "lxml")
        extra_soups.append(contact_soup)
        c_jsonld = extract_jsonld(contact_soup, contact_url)
        c_contacts = extract_contacts(contact_soup)
        info["address"] = info["address"] or c_jsonld.get("address") or c_contacts["address"]
        info["phone"] = info["phone"] or c_jsonld.get("phone") or next(iter(c_contacts["phones"]), "")
        info["email"] = info["email"] or c_jsonld.get("email") or next(iter(c_contacts["emails"]), "")
        contacts["phones"] = list(dict.fromkeys(contacts["phones"] + c_contacts["phones"]))[:3]
        contacts["emails"] = list(dict.fromkeys(contacts["emails"] + c_contacts["emails"]))[:3]
        for key, value in extract_social_links(contact_soup, None, extras).items():
            social_links.setdefault(key, value)

    inline_css = [s.string or s.get_text() for s in soup.find_all("style")]
    font_family = extract_font_family(soup, inline_css + external_css)
    colors = extract_brand_colors(soup, base_url, logo_url, external_css, logo_bytes)

    # ---- 3. AI only for what is still missing --------------------------------
    missing = [f for f in ("tagline", "about", "industry", "address", "phone", "email") if not info.get(f)]
    if not name_is_confident:
        missing.insert(0, "company_name")
    missing.append("brand_style")
    if jsonld.get("jsonld_type") and "industry" in missing:
        info["industry"] = re.sub(r"(?<!^)(?=[A-Z])", " ", jsonld["jsonld_type"])
        missing.remove("industry")

    known = {k: v for k, v in info.items() if v and k in ("company_name", "industry")}
    digest = build_page_digest(soup, extra_soups)
    ai_info = extract_company_info_with_ai(digest, meta_description, company_name, missing, known)

    brand_style = ai_info.pop("brand_style", "")
    for field in missing:
        if ai_info.get(field):
            info[field] = ai_info[field]

    # Don't trust AI-invented contact details that never appear on the site.
    haystack = digest.lower() + " " + json.dumps(jsonld).lower()
    if "email" in missing and info["email"] and info["email"].lower() not in haystack:
        info["email"] = ""
    if "phone" in missing and info["phone"]:
        digits = re.sub(r"\D", "", info["phone"])
        if digits[-7:] not in re.sub(r"\D", "", haystack):
            info["phone"] = ""
    if info["email"] and not EMAIL_PATTERN.fullmatch(info["email"]):
        info["email"] = ""

    company_info = {field: _clamp(field, value) for field, value in info.items()}
    company_info["company_name"] = company_info["company_name"] or _clamp("company_name", company_name)

    if contacts["phones"][1:]:
        extras["additional_phones"] = contacts["phones"][1:]
    if contacts["emails"][1:]:
        extras["additional_emails"] = contacts["emails"][1:]

    return {
        "company_info": company_info,
        "social_links": social_links,
        "brand": {
            "logo_url": logo_url if logo_url and len(logo_url) <= 500 else None,
            **colors,
            "font_family": _clamp("font_family", font_family) or None,
            "brand_style": _clamp("brand_style", brand_style) or None,
        },
        "extras": extras,
        "source_url": base_url,
    }
