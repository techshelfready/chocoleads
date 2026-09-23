from __future__ import annotations
import csv
import os
from pathlib import Path
from typing import Iterable
import pandas as pd
from slugify import slugify
from .config import settings
from .models import Lead

CSV_COLUMNS = [
    "lead_id","date_generated","run_id","zipcode","property_type","source_site","property_name_or_address",
    "source_url","price","size","notes","rooms_selected","pdf_path","asset_folder","status"
]


def ensure_csv() -> Path:
    path = settings.leads_csv
    if not path.exists():
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writeheader()
    return path


def load_existing_df() -> pd.DataFrame:
    path = ensure_csv()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=CSV_COLUMNS)


def seen_key_set() -> set[str]:
    df = load_existing_df()
    keys = set()
    for _, row in df.iterrows():
        addr = str(row.get("property_name_or_address", "")).strip().lower()
        src = str(row.get("source_url", "")).strip().lower()
        if src:
            keys.add(src)
        if addr:
            keys.add(addr)
    return keys


def append_leads(leads: Iterable[Lead], run_id: str):
    path = ensure_csv()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        for lead in leads:
            writer.writerow({
                "lead_id": lead.lead_id,
                "date_generated": pd.Timestamp.utcnow().isoformat(),
                "run_id": run_id,
                "zipcode": lead.zipcode,
                "property_type": lead.property_type,
                "source_site": lead.source_site,
                "property_name_or_address": lead.address,
                "source_url": lead.source_url,
                "price": lead.price,
                "size": lead.size,
                "notes": lead.notes,
                "rooms_selected": "; ".join([r.room_label for r in lead.selected_rooms]),
                "pdf_path": lead.pdf_path,
                "asset_folder": lead.asset_dir,
                "status": lead.status,
            })


def make_run_dir(run_id: str) -> Path:
    d = settings.runs_dir / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def make_lead_dir(run_id: str, address: str) -> Path:
    slug = slugify(address)[:80] or "lead"
    d = settings.assets_dir / run_id / slug
    d.mkdir(parents=True, exist_ok=True)
    return d
