from __future__ import annotations
import os
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Settings:
    app_password: str = os.getenv("APP_PASSWORD", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_vision_model: str = os.getenv("OPENAI_VISION_MODEL", "gpt-6-astra")
    openai_image_model: str = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
    openai_text_model: str = os.getenv("OPENAI_TEXT_MODEL", "gpt-6-astra")
    google_places_api_key: str = os.getenv("GOOGLE_PLACES_API_KEY", "")
    request_timeout: int = int(os.getenv("REQUEST_TIMEOUT", "25"))
    max_candidates_per_source: int = int(os.getenv("MAX_CANDIDATES_PER_SOURCE", "20"))

    project_root: Path = Path(__file__).resolve().parent.parent
    data_dir: Path = project_root / os.getenv("DATA_DIR", "data")
    runs_dir: Path = project_root / os.getenv("RUNS_DIR", "runs")
    leads_csv: Path = project_root / os.getenv("LEADS_CSV", "data/leads.csv")
    assets_dir: Path = project_root / os.getenv("ASSETS_DIR", "data/assets")
    logo_path: Path = project_root / "assets" / "logo.png"
    style_ref_paths: list[Path] = None

    def __post_init__(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.leads_csv.parent.mkdir(parents=True, exist_ok=True)
        style_dir = self.project_root / os.getenv("STYLE_REF_DIR", "assets/styles")
        self.style_ref_paths = sorted(
            p for p in style_dir.glob("*")
            if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
        )

settings = Settings()
