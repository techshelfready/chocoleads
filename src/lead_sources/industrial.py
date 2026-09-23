from __future__ import annotations

import re
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


class IndustrialSource(LeadSource):
    name = "Industrial"

    def search(self, zipcode: str, limit: int, category: str = "industrial") -> List[Lead]:
        queries = [
            f"site:crexi.com {zipcode} warehouse for sale",
            f"site:commercialcafe.com {zipcode} industrial",
            f"site:crexi.com {zipcode} industrial property",
            f"site:commercialcafe.com {zipcode} warehouse",
            f"site:crexi.com {zipcode} flex space",
        ]
        results = run_queries(queries, max_results_per_query=max(limit * 3, 10))
        urls = collect_search_urls(results, ["crexi.com", "commercialcafe.com"])
        urls = [u for u in urls if re.search(r"/properties/\d+|/commercial-property/", u, re.I)]
        leads = []
        for u in urls[: limit * 4]:
            try:
                lead = self._parse_listing(u, zipcode)
                if lead.images:
                    leads.append(lead)
            except Exception:
                continue
            if len(leads) >= limit:
                break
        return leads

    def _parse_listing(self, url: str, zipcode: str) -> Lead:
        soup = fetch_soup(url)
        title = normalize_text((soup.title.text if soup.title else "Industrial Listing"))
        text = soup.get_text(" ", strip=True)
        structured = parse_json_ld(soup)
        address = extract_address_from_structured(structured) or find_best_address(text, title)
        price = extract_price_from_structured(structured) or find_price(text)
        size = extract_size_from_structured(structured) or find_size(text)
        imgs = extract_candidate_images(soup, url, max_images=40)
        source_site = "Crexi" if "crexi.com" in url else "CommercialCafe"
        lead_id = re.sub(r"\W+", "-", address.lower())[:60]
        return Lead(
            lead_id=lead_id,
            property_type="industrial properties",
            address=address,
            zipcode=zipcode,
            title=title,
            source_site=source_site,
            source_url=url,
            price=price,
            size=size,
            notes="Industrial/commercial property lead",
            category="industrial",
            images=imgs,
        )
