from __future__ import annotations

import re
from urllib.parse import urljoin
from typing import List

from ..models import Lead
from ..utils import normalize_text
from .base import LeadSource
from .search_helpers import run_queries
from .scraper_utils import (
    collect_search_urls,
    extract_address_from_structured,
    extract_candidate_images,
    extract_price_from_structured,
    extract_size_from_structured,
    fetch_soup,
    find_best_address,
    find_price,
    find_size,
    parse_json_ld,
)


class HousingSource(LeadSource):
    SOURCES = {
        "Zillow": ("zillow.com", r"/homedetails/[^/]+/\d+_zpid"),
        "Redfin": ("redfin.com", r"/home/\d+"),
        "Realtor.com": ("realtor.com", r"/realestateandhomes-detail/[^/]+_M[\d-]+"),
    }

    def __init__(self, name="Zillow"):
        self.name = name
        self.domain, self.listing_pattern = self.SOURCES[name]
        self.last_search = {}

    def search(self, zipcode: str, limit: int, category: str = "houses") -> List[Lead]:
        path = {"Zillow": "homedetails", "Redfin": "home", "Realtor.com": "realestateandhomes-detail"}[self.name]
        queries = [
            f'site:{self.domain} inurl:{path} "{zipcode}" house garage',
            f'site:{self.domain} "{zipcode}" single family house for sale',
        ]
        results = run_queries(queries, max_results_per_query=max(limit * 2, 12))
        discovered = collect_search_urls(results, [self.domain])
        urls = [u for u in discovered if re.search(self.listing_pattern, u, re.I)]
        # Search engines commonly return ZIP landing pages; follow their listing
        # links, but never treat the landing page itself as a property.
        landing_failures = 0
        landing_pages = [u for u in discovered if u not in urls][:2]
        if len(urls) < limit:
            for landing_url in landing_pages:
                try:
                    landing = fetch_soup(landing_url)
                    links = [{"href": urljoin(landing_url, a["href"])} for a in landing.select("a[href]")]
                    for url in collect_search_urls(links, [self.domain]):
                        if re.search(self.listing_pattern, url, re.I) and url not in urls:
                            urls.append(url)
                except Exception:
                    landing_failures += 1
        if not urls and landing_pages and landing_failures == len(landing_pages):
            raise RuntimeError(f"{self.name} search pages could not be accessed.")
        self.last_search = {"search_results": len(results), "listing_urls": len(urls), "fetch_failures": 0, "leads": 0}
        leads = []
        for url in urls[:limit * 3]:
            try:
                lead = self._parse_listing(url, zipcode)
                if len(lead.images) >= 2:
                    leads.append(lead)
            except Exception:
                self.last_search["fetch_failures"] += 1
                continue
            if len(leads) >= limit:
                break
        self.last_search["leads"] = len(leads)
        if urls and self.last_search["fetch_failures"] == min(len(urls),limit*3):
            raise RuntimeError(f"{self.name} listings could not be accessed.")
        return leads

    def _parse_listing(self, url: str, zipcode: str) -> Lead:
        soup = fetch_soup(url)
        title = normalize_text((soup.title.text if soup.title else "Property Listing"))
        text = soup.get_text(" ", strip=True)
        structured = parse_json_ld(soup)
        address = extract_address_from_structured(structured) or find_best_address(text, title)
        price = extract_price_from_structured(structured) or find_price(text)
        size = extract_size_from_structured(structured) or find_size(text)
        imgs = extract_candidate_images(soup, url, max_images=40)
        # enrich room hints based on title and captions for housing-specific uses
        for img in imgs:
            caption_blob = f"{img.caption} {img.url}".lower()
            if not img.room_type_hint:
                if "garage" in caption_blob:
                    img.room_type_hint = "garage"
                elif any(k in caption_blob for k in ["living", "family", "kitchen", "bedroom", "bathroom"]):
                    img.room_type_hint = "interior"
        source_site = self.name
        lead_id = re.sub(r"\W+", "-", address.lower())[:60]
        return Lead(
            lead_id=lead_id,
            property_type="houses",
            address=address,
            zipcode=zipcode,
            title=title,
            source_site=source_site,
            source_url=url,
            price=price,
            size=size,
            notes="Residential lead",
            category="house",
            images=imgs,
        )
