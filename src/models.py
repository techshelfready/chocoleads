from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field

class CandidateImage(BaseModel):
    url: str
    local_path: str = ""
    source: str = ""
    caption: str = ""
    room_type_hint: str = ""

class RoomSelection(BaseModel):
    before_image_url: str
    before_local_path: str = ""
    after_local_path: str = ""
    room_label: str
    style_label: str
    rationale: str = ""

class Lead(BaseModel):
    lead_id: str
    property_type: str
    address: str
    city: str = ""
    state: str = ""
    zipcode: str = ""
    title: str = ""
    source_site: str
    source_url: str
    price: str = ""
    size: str = ""
    notes: str = ""
    category: str = ""
    images: List[CandidateImage] = Field(default_factory=list)
    selected_rooms: List[RoomSelection] = Field(default_factory=list)
    asset_dir: str = ""
    pdf_path: str = ""
    run_id: str = ""
    status: str = "new"
