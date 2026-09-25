"""Imported Crexi listings and listing-specific photo galleries."""
from __future__ import annotations
import json
import sqlite3
import time
from pathlib import Path
from ..config import settings
from ..geography import search_zipcodes
from ..models import CandidateImage, Lead

COMMERCIAL_TYPES = {'Retail', 'Office', 'Hospitality', 'Mixed Use', 'Self Storage', 'Special Purpose'}

class CrexiDatasetSource:
    finite_inventory = True

    def __init__(self, property_type, listings_path=None, galleries_path=None, extra_path=None, usage_path=None):
        if property_type not in {'commercial properties', 'industrial properties'}:
            raise ValueError('Unsupported Crexi property type')
        self.property_type = property_type
        self.name = 'Imported Crexi listings'
        imports = settings.data_dir / 'imports'
        self.listings_path = Path(listings_path or imports / 'commercial_listings.json')
        self.galleries_path = Path(galleries_path or imports / 'crexi_property_galleries.json')
        self.extra_path = Path(extra_path or imports / 'crexi_extra_galleries.json')
        self.usage_path = Path(usage_path or settings.data_dir / 'crexi_usage.sqlite3')
        self.usage_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS usage (listing_id TEXT PRIMARY KEY, status TEXT NOT NULL, run_id TEXT, updated REAL, reason TEXT)')

    def connect(self):
        return sqlite3.connect(self.usage_path, timeout=30)

    def search(self, zipcode, limit, category=None):
        if not self.listings_path.exists() or not self.galleries_path.exists():
            raise ValueError('An imported Crexi dataset is missing from data/imports.')
        rows = json.loads(self.listings_path.read_text())
        detailed = {str(row['id']): row for row in json.loads(self.galleries_path.read_text())}
        extra = json.loads(self.extra_path.read_text()) if self.extra_path.exists() and self.extra_path.stat().st_size else {}
        if not isinstance(rows, list) or not isinstance(extra, dict):
            raise ValueError('The imported Crexi files have an unexpected format.')
        with self.connect() as db:
            db.execute("DELETE FROM usage WHERE status='reserved' AND updated < ?", (time.time()-21600,))
            blocked = {row[0] for row in db.execute('SELECT listing_id FROM usage')}
        distances = dict(search_zipcodes('33130'))
        leads = []
        local_seen = set()
        for row in rows:
            listing_id = str(row.get('id') or '')
            if not listing_id or listing_id in blocked or listing_id in local_seen:
                continue
            local_seen.add(listing_id)
            kinds = set(row.get('types') or [])
            if self.property_type == 'industrial properties':
                if 'Industrial' not in kinds:
                    continue
            elif 'Industrial' in kinds or not kinds.intersection(COMMERCIAL_TYPES):
                continue
            rich = detailed.get(listing_id) or {}
            if len(rich.get('locations') or []) > 1 or 'portfolio' in str(row.get('name') or '').lower():
                continue
            raw_photos = rich.get('image_urls') or (extra.get(listing_id) or {}).get('images') or []
            photos = list(dict.fromkeys(url for url in raw_photos
                                        if isinstance(url, str) and url.startswith('https://crexi.com/images/')
                                        and f'/assets/{listing_id}/' in url))
            if len(photos) < 2:
                continue
            address = str(row.get('fullAddress') or row.get('address') or '').strip()
            listing_zip = str(row.get('zip') or '')[:5]
            if not address or not (len(listing_zip) == 5 and listing_zip.isdigit()):
                continue
            # The scrape's generic /properties/<slug> links can open a search page.
            # Numeric-ID URLs were verified on Crexi and redirect to individual listings.
            source_url = str(rich.get('url') or (extra.get(listing_id) or {}).get('url') or f'https://www.crexi.com/properties/{listing_id}')
            price_value = row.get('askingPrice')
            price = f'${price_value:,.0f}' if isinstance(price_value, (int, float)) and price_value > 1 else ''
            size = next((str(value.get('value')) for value in row.get('listingSummaryDetails') or []
                         if isinstance(value, dict) and value.get('type') == 'SquareFootage'), '')
            size = size or str(rich.get('metric_line') or '')
            leads.append(Lead(lead_id='crexi-'+listing_id,property_type=self.property_type,
                address=address,city=str(row.get('city') or ''),state=str(row.get('state') or ''),
                zipcode=listing_zip,title=str(row.get('name') or ''),source_site=self.name,
                source_url=source_url,price=price,size=size,
                notes=f"Imported Crexi ID {listing_id}; status: {row.get('status') or 'unknown'}; captured: {row.get('scrapedAt') or 'unknown'}",
                category=', '.join(row.get('types') or []),
                images=[CandidateImage(url=url, source=source_url) for url in photos]))
        leads.sort(key=lambda lead: (distances.get(lead.zipcode, 9999), -len(lead.images), lead.lead_id))
        return leads

    def claim(self, lead, run_id):
        with self.connect() as db:
            return db.execute('INSERT OR IGNORE INTO usage VALUES (?, ?, ?, ?, ?)',
                (lead.lead_id.removeprefix('crexi-'), 'reserved', run_id, time.time(), '')).rowcount == 1

    def reject(self, lead, run_id):
        with self.connect() as db:
            db.execute("UPDATE usage SET status='ineligible', reason='No suitable distinct indoor room pair', updated=? WHERE listing_id=? AND run_id=? AND status='reserved'",
                       (time.time(), lead.lead_id.removeprefix('crexi-'), run_id))

    def finish(self, run_id, success):
        with self.connect() as db:
            if success:
                db.execute("UPDATE usage SET status='used', updated=? WHERE run_id=? AND status='reserved'", (time.time(), run_id))
            else:
                db.execute("DELETE FROM usage WHERE run_id=? AND status='reserved'", (run_id,))
