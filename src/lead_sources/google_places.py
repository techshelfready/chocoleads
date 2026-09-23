from __future__ import annotations
from typing import List
import requests
from ..config import settings
from ..models import Lead, CandidateImage
from .base import LeadSource

class GooglePlacesFallbackSource(LeadSource):
    name = "Google Places"

    def search(self, zipcode: str, limit: int, category: str = "commercial") -> List[Lead]:
        if not settings.google_places_api_key:
            return []
        # Google Places Text Search (new) endpoint.
        query = f"{category} in {zipcode}"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": settings.google_places_api_key,
            "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.id,places.websiteUri,places.photos,places.types"
        }
        payload = {"textQuery": query, "pageSize": min(limit, 10)}
        resp = requests.post(
            "https://places.googleapis.com/v1/places:searchText",
            json=payload,
            headers=headers,
            timeout=settings.request_timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        out: List[Lead] = []
        for p in data.get("places", []):
            imgs = []
            for photo in p.get("photos", [])[:10]:
                photo_name = photo.get("name")
                if photo_name:
                    img_url = f"https://places.googleapis.com/v1/{photo_name}/media?maxHeightPx=1200&maxWidthPx=1200&key={settings.google_places_api_key}"
                    imgs.append(CandidateImage(url=img_url, source=self.name, caption=photo.get("authorAttributions", [{}])[0].get("displayName", "")))
            out.append(Lead(
                lead_id=(p.get("id") or p.get("formattedAddress", "")).replace("/", "-"),
                property_type="commercial",
                address=p.get("formattedAddress", ""),
                zipcode=zipcode,
                title=p.get("displayName", {}).get("text", ""),
                source_site=self.name,
                source_url=p.get("websiteUri") or f"https://www.google.com/maps/place/?q=place_id:{p.get('id','')}",
                notes=f"Fallback lead via Google Places; types={', '.join(p.get('types', []))}",
                category=category,
                images=imgs,
            ))
        return out
