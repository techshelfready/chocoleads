from __future__ import annotations

import re
from typing import List

from ..config import settings
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


class BizBuySellSource(LeadSource):
    name = "BizBuySell"

    def search(self, zipcode: str, limit: int, category: str = "commercial") -> List[Lead]:
        queries = [
            f"site:bizbuysell.com {zipcode} restaurant for sale",
            f"site:bizbuysell.com {zipcode} business for sale",
            f"site:bizbuysell.com {zipcode} cafe for sale",
            f"site:bizbuysell.com {zipcode} retail business for sale",
        ]
        results = run_queries(queries, max_results_per_query=max(limit * 2, 8))
        urls = collect_search_urls(results, ["bizbuysell.com"])
        urls = [u for u in urls if re.search(r"/business-opportunity/[^/]+/\d+", u, re.I)]
        leads: List[Lead] = []
        for u in urls[: limit * 3]:
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
        title = normalize_text((soup.title.text if soup.title else "BizBuySell Listing"))
        text = soup.get_text(" ", strip=True)
        structured = parse_json_ld(soup)
        address = extract_address_from_structured(structured) or find_best_address(text, title)
        price = extract_price_from_structured(structured) or find_price(text)
        size = extract_size_from_structured(structured) or find_size(text)
        images = extract_candidate_images(soup, url, max_images=30)
        lead_id = re.sub(r"\W+", "-", address.lower())[:60]
        return Lead(
            lead_id=lead_id,
            property_type="commercial properties",
            address=address,
            zipcode=zipcode,
            title=title,
            source_site=self.name,
            source_url=url,
            price=price,
            size=size,
            notes="Business-for-sale prospect from BizBuySell",
            category="business",
            images=images,
        )
