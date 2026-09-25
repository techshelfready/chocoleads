"""Finite, local Zillow inventory. No listing searches or gallery scraping."""
import json
import sqlite3
import time
from pathlib import Path
from ..config import settings
from ..models import Lead, CandidateImage

HOUSE_DATASET_LABEL = 'Miami dataset'

class ZillowDatasetSource:
    name = 'Imported Zillow dataset'
    finite_inventory = True

    def __init__(self, dataset_path=None, usage_path=None):
        self.dataset_path = Path(dataset_path or settings.data_dir / 'imports/zillow_houses.json')
        self.usage_path = Path(usage_path or settings.data_dir / 'zillow_usage.sqlite3')
        self.usage_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS usage (zpid TEXT PRIMARY KEY, status TEXT NOT NULL, run_id TEXT, updated REAL, reason TEXT)')

    def connect(self):
        return sqlite3.connect(self.usage_path, timeout=30)

    def search(self, zipcode, limit, category=None):
        if not self.dataset_path.exists():
            raise ValueError('The imported Zillow dataset is missing. Restore data/imports/zillow_houses.json.')
        rows = json.loads(self.dataset_path.read_text())
        if not isinstance(rows, list):
            raise ValueError('The Zillow dataset must contain a list of listings.')
        with self.connect() as db:
            # Recover abandoned reservations after a crashed process; used IDs never expire.
            db.execute("DELETE FROM usage WHERE status='reserved' AND updated < ?", (time.time()-21600,))
            blocked = {r[0] for r in db.execute('SELECT zpid FROM usage')}
        leads = []
        for row in rows:
            zpid = str(row.get('zpid') or '')
            if not zpid or zpid in blocked or row.get('homeType') != 'SINGLE_FAMILY':
                continue
            blocked.add(zpid)
            address = row.get('listingAddress') or {}
            url = row.get('propertyUrl') or ''
            photos = list(dict.fromkeys(p.get('url') for p in (row.get('listingPhotos') or [])
                                       if isinstance(p, dict) and str(p.get('url') or '').startswith('https://')))
            if not address.get('full') or not url.startswith('https://') or len(photos) < 2:
                continue
            leads.append(Lead(lead_id='zillow-'+zpid, property_type='houses',
                address=address['full'], city=address.get('city') or '', state=address.get('state') or '',
                zipcode=str(address.get('zipCode') or ''), source_site=self.name, source_url=url,
                price=str((row.get('listingPrice') or {}).get('formatted') or ''),
                size=f"{row.get('livingArea', '')} {row.get('livingAreaUnit', '')}".strip(),
                notes=f"Imported Zillow ID {zpid}; listing status: {row.get('listingStatus', 'unknown')}; captured: {row.get('scrapedAt', 'unknown')}",
                images=[CandidateImage(url=p, source=url) for p in photos]))
        # The finite inventory is scanned once, until enough eligible homes qualify.
        return leads

    def claim(self, lead, run_id):
        with self.connect() as db:
            return db.execute('INSERT OR IGNORE INTO usage VALUES (?, ?, ?, ?, ?)',
                (lead.lead_id.removeprefix('zillow-'), 'reserved', run_id, time.time(), '')).rowcount == 1

    def reject(self, lead, run_id):
        with self.connect() as db:
            db.execute("UPDATE usage SET status='ineligible', reason='No enclosed garage and indoor room pair', updated=? WHERE zpid=? AND run_id=? AND status='reserved'",
                       (time.time(), lead.lead_id.removeprefix('zillow-'), run_id))

    def finish(self, run_id, success):
        with self.connect() as db:
            if success:
                db.execute("UPDATE usage SET status='used', updated=? WHERE run_id=? AND status='reserved'", (time.time(), run_id))
            else:
                db.execute("DELETE FROM usage WHERE run_id=? AND status='reserved'", (run_id,))
