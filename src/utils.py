from __future__ import annotations
import base64
import mimetypes
import os
import re
from pathlib import Path
from urllib.parse import urlparse
import requests
from .config import settings

HEADERS = {"User-Agent": "Mozilla/5.0 (ChocoLeadsAI/1.0)"}


def normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def download_file(url: str, out_path: str | Path) -> str:
    out_path = Path(out_path)
    resp = requests.get(url, timeout=settings.request_timeout, headers=HEADERS)
    resp.raise_for_status()
    out_path.write_bytes(resp.content)
    return str(out_path)


def guess_ext(url: str) -> str:
    path = urlparse(url).path.lower()
    for ext in [".jpg", ".jpeg", ".png", ".webp"]:
        if path.endswith(ext):
            return ext
    return ".jpg"


def image_to_data_url(path: str | Path) -> str:
    path = Path(path)
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    data = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{data}"
