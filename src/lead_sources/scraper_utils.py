from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..config import settings
from ..models import CandidateImage
from ..utils import HEADERS, normalize_text

BAD_IMAGE_HINTS = {
    "logo", "icon", "avatar", "map", "marker", "sprite", "banner", "favicon",
    "broker", "agent", "profile", "headshot", "placeholder"
}
ROOM_HINT_KEYWORDS = {
    "garage": ["garage", "carport"],
    "kitchen": ["kitchen"],
    "living room": ["living", "family room", "lounge"],
    "bathroom": ["bathroom", "restroom", "powder"],
    "office": ["office", "workspace", "conference", "meeting"],
    "warehouse": ["warehouse", "industrial", "loading", "showroom"],
    "retail": ["retail", "storefront", "sales floor"],
}


def make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        read=3,
        connect=3,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD", "OPTIONS"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(HEADERS)
    return session


def fetch_soup(url: str) -> BeautifulSoup:
    session = make_session()
    resp = session.get(url, timeout=settings.request_timeout)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "lxml")


def domain_matches(url: str, domain_keywords: list[str]) -> bool:
    host = urlparse(url).netloc.lower()
    return any(d in host for d in domain_keywords)


def collect_search_urls(query_results: Iterable[Dict[str, Any]], allowed_domains: list[str]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for r in query_results:
        u = (r.get("href") or r.get("url") or "").strip()
        if not u or not u.startswith("http"):
            continue
        if not domain_matches(u, allowed_domains):
            continue
        normalized = normalize_listing_url(u)
        if normalized not in seen:
            seen.add(normalized)
            urls.append(normalized)
    return urls


def normalize_listing_url(url: str) -> str:
    # strip tracking querystrings while preserving core path
    parsed = urlparse(url)
    normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    return normalized.rstrip("/")


def parse_json_ld(soup: BeautifulSoup) -> list[dict]:
    objects: list[dict] = []
    for tag in soup.find_all("script", attrs={"type": re.compile(r'ld\+json', re.I)}):
        raw = (tag.string or tag.get_text() or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    objects.append(item)
        elif isinstance(data, dict):
            graph = data.get("@graph")
            if isinstance(graph, list):
                for item in graph:
                    if isinstance(item, dict):
                        objects.append(item)
            objects.append(data)
    return objects


def deep_find_values(obj: Any, keys: set[str]) -> list[Any]:
    found: list[Any] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys:
                found.append(v)
            found.extend(deep_find_values(v, keys))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(deep_find_values(item, keys))
    return found


def extract_best_text(values: list[Any]) -> str:
    for v in values:
        if isinstance(v, str) and normalize_text(v):
            return normalize_text(v)
        if isinstance(v, dict):
            for candidate_key in ["streetAddress", "addressLocality", "postalCode", "name"]:
                if candidate_key in v and normalize_text(str(v[candidate_key])):
                    return normalize_text(str(v[candidate_key]))
    return ""


def extract_address_from_structured(items: list[dict]) -> str:
    for item in items:
        addr = item.get("address")
        if isinstance(addr, dict):
            pieces = [
                addr.get("streetAddress", ""),
                addr.get("addressLocality", ""),
                addr.get("addressRegion", ""),
                addr.get("postalCode", ""),
            ]
            address = normalize_text(", ".join([p for p in pieces if p]))
            if address:
                return address
        elif isinstance(addr, str) and normalize_text(addr):
            return normalize_text(addr)
    return ""


def extract_price_from_structured(items: list[dict]) -> str:
    keys = {"price", "lowPrice", "highPrice"}
    vals = []
    for item in items:
        vals.extend(deep_find_values(item, keys))
    for v in vals:
        if isinstance(v, (int, float)):
            return f"${v:,.0f}"
        if isinstance(v, str):
            txt = normalize_text(v)
            if txt.startswith("$"):
                return txt
            if re.fullmatch(r"[\d,]+(?:\.\d+)?", txt):
                return f"${txt}"
    return ""


def extract_size_from_structured(items: list[dict]) -> str:
    # Typical keys vary widely across sites.
    keys = {"floorSize", "size", "area", "value", "squareFootage"}
    vals = []
    for item in items:
        vals.extend(deep_find_values(item, keys))
    for v in vals:
        if isinstance(v, dict):
            value = v.get("value") or v.get("maxValue") or v.get("minValue")
            unit = v.get("unitText") or v.get("unitCode") or ""
            if value:
                return normalize_text(f"{value} {unit}")
        elif isinstance(v, str):
            txt = normalize_text(v)
            if re.search(r"sq\.?\s*ft|sf|square\s*feet", txt, re.I):
                return txt
    return ""


def looks_like_property_image(url: str, alt: str = "") -> bool:
    hay = f"{url} {alt}".lower()
    return not any(bad in hay for bad in BAD_IMAGE_HINTS)


def room_hint_from_text(text: str) -> str:
    t = normalize_text(text).lower()
    for label, keywords in ROOM_HINT_KEYWORDS.items():
        if any(k in t for k in keywords):
            return label
    return ""


def iter_image_candidates(tag) -> Iterable[str]:
    attrs = ["src", "data-src", "data-lazy-src", "data-original", "data-image", "content"]
    for attr in attrs:
        val = tag.get(attr)
        if val:
            yield val
    srcset = tag.get("srcset") or tag.get("data-srcset")
    if srcset:
        for part in srcset.split(","):
            piece = part.strip().split(" ")[0].strip()
            if piece:
                yield piece


def extract_candidate_images(soup: BeautifulSoup, base_url: str, max_images: int = 40) -> list[CandidateImage]:
    images: list[CandidateImage] = []
    seen: set[str] = set()

    def add(url: str, caption: str = "", source: str = base_url):
        if not url:
            return
        full = urljoin(base_url, url)
        if not full.startswith("http"):
            return
        full = full.strip()
        if full in seen:
            return
        if not looks_like_property_image(full, caption):
            return
        seen.add(full)
        images.append(
            CandidateImage(
                url=full,
                source=source,
                caption=normalize_text(caption),
                room_type_hint=room_hint_from_text(caption),
            )
        )

    # Meta tags first; sometimes the page exposes key listing photos here.
    for meta in soup.find_all(["meta", "link"]):
        prop = (meta.get("property") or meta.get("name") or meta.get("rel") or "")
        if isinstance(prop, list):
            prop = " ".join(prop)
        if any(k in str(prop).lower() for k in ["og:image", "twitter:image", "image_src"]):
            for url in iter_image_candidates(meta):
                add(url, caption="meta image")

    # General img tags.
    for img in soup.find_all("img"):
        alt = normalize_text(img.get("alt", ""))
        for url in iter_image_candidates(img):
            add(url, caption=alt)
            if len(images) >= max_images:
                return images[:max_images]

    return images[:max_images]


def find_best_address(text: str, title: str = "") -> str:
    patterns = [
        r"([0-9]{1,6}[^,\n]+,\s*[^,\n]+,\s*FL\s*\d{5})",
        r"([0-9]{1,6}[^,\n]+,\s*Miami[^\n,]*,?\s*FL\s*\d{5})",
        r"([0-9]{1,6}[^,\n]+,\s*Coral Gables[^\n,]*,?\s*FL\s*\d{5})",
    ]
    blob = f"{title} {text}"
    for p in patterns:
        m = re.search(p, blob, re.I)
        if m:
            return normalize_text(m.group(1))
    return normalize_text(title)


def find_price(text: str) -> str:
    # prefer longer real-estate style price strings
    matches = re.findall(r"\$\s?[\d,]{3,}(?:\.\d+)?", text)
    if matches:
        return normalize_text(matches[0])
    return ""


def find_size(text: str) -> str:
    patterns = [
        r"([\d,]+\s*(?:sq\.?\s*ft\.?|square\s*feet|SF))",
        r"(?:building\s*size|size)\s*[:\-]?\s*([\d,]+\s*(?:sq\.?\s*ft\.?|SF))",
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            return normalize_text(m.group(1))
    return ""
