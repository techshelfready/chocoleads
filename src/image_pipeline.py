from __future__ import annotations
import json
from pathlib import Path
from typing import List
from openai import OpenAI
from tenacity import retry, wait_random_exponential, stop_after_attempt
from .config import settings
from .models import Lead, RoomSelection, CandidateImage
from .utils import image_to_data_url, download_file, guess_ext

STYLE_LABELS = [
    "Bold Fusion",
    "Royal Current",
    "Modern Marble",
    "Coastal Escape",
    "Signature Pink",
]

class OpenAIFloorRenderer:
    def __init__(self):
        self.client = OpenAI(api_key=settings.openai_api_key)

    @retry(wait=wait_random_exponential(min=1, max=20), stop=stop_after_attempt(3))
    def _vision_json(self, prompt: str, image_paths: List[str]) -> dict:
        content = [{"type": "input_text", "text": prompt}]
        for p in image_paths:
            content.append({"type": "input_image", "image_url": image_to_data_url(p)})
        resp = self.client.responses.create(
            model=settings.openai_vision_model,
            reasoning={"effort": settings.openai_reasoning_effort},
            input=[{"role": "user", "content": content}],
            text={"format": {"type": "json_object"}},
        )
        text = getattr(resp, "output_text", "") or "{}"
        return json.loads(text)

    @retry(wait=wait_random_exponential(min=1, max=20), stop=stop_after_attempt(3))
    def _generate_image(self, room_image_path: str, style_path: str, prompt: str, out_path: Path) -> str:
        import hashlib, shutil
        cache_dir = settings.data_dir / 'render_cache'
        cache_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(Path(room_image_path).read_bytes() + Path(style_path).read_bytes()
                                + (settings.openai_image_model + prompt + 'high-fidelity-v1').encode()).hexdigest()
        cached = cache_dir / (digest + '.png')
        if cached.exists():
            shutil.copy2(cached, out_path)
            return str(out_path)
        with open(room_image_path, "rb") as room, open(style_path, "rb") as style:
            resp = self.client.images.edit(
                model=settings.openai_image_model,
                image=[room, style],
                prompt=prompt,
                **({'input_fidelity':'high'} if settings.openai_image_model in {'gpt-image-1','gpt-image-1.5'} else {}),
            )
        b64 = resp.data[0].b64_json if resp.data else None
        if not b64:
            raise RuntimeError("No image was returned by OpenAI image editing.")
        import base64
        out_path.write_bytes(base64.b64decode(b64))
        shutil.copy2(out_path, cached)
        return str(out_path)

    def select_room_images(self, lead: Lead, lead_dir: Path) -> List[RoomSelection]:
        from concurrent.futures import ThreadPoolExecutor
        from PIL import Image, ImageOps, ImageDraw
        import hashlib
        downloaded = []
        image_hashes = set()
        def download_candidate(pair):
            idx, img = pair
            try:
                local = lead_dir / f"candidate_{idx+1}{guess_ext(img.url)}"
                if not local.exists():
                    if img.local_path:
                        import shutil
                        shutil.copy2(img.local_path, local)
                    else:
                        download_file(img.url, local)
                with Image.open(local) as photo:
                    photo.verify()
                return img, str(local)
            except Exception:
                return None
        with ThreadPoolExecutor(max_workers=6) as pool:
            for item in pool.map(download_candidate, enumerate(lead.images)):
                if not item:
                    continue
                img, path = item
                digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
                if digest in image_hashes:
                    continue
                image_hashes.add(digest)
                downloaded.append(item)
        if len(downloaded) < 2:
            raise RuntimeError("The property photos could not be downloaded. Please retry; this home has not been marked used.")

        # Vision must positively verify the room; never fill missing selections blindly.
        paths = [p for _, p in downloaded]
        using_sheets = len(paths) > 12
        if using_sheets:
            paths = []
            for start in range(0, len(downloaded), 24):
                batch = downloaded[start:start+24]
                sheet = Image.new('RGB', (1024, 216*((len(batch)+3)//4)), 'white')
                draw = ImageDraw.Draw(sheet)
                for j, (_, path) in enumerate(batch):
                    with Image.open(path) as photo:
                        preview = ImageOps.contain(ImageOps.exif_transpose(photo).convert('RGB'), (250,190))
                    x=(j%4)*256; y=(j//4)*216
                    sheet.paste(preview,(x,y))
                    draw.text((x+5,y+194),f'PHOTO {start+j+1}',fill='black')
                sheet_path=lead_dir/f'gallery_{start//24+1}.jpg'
                sheet.save(sheet_path,quality=90)
                paths.append(str(sheet_path))
        prompt = (
            "Select exactly two DISTINCT indoor rooms for epoxy-floor concepts. "
            "Each must be an enclosed room with visible walls and clearly visible usable floor. "
            "NEVER choose outdoors, patios, decks, driveways, yards, porches, exterior views, "
            "open carports, or covered outdoor areas, even when a wall is visible. "
            "Select actual room photographs only; reject floor plans, diagrams, maps, and collages. "
            "An enclosed garage is allowed. Reject ambiguous photos. "
            "For each selected image return index (1-based), room_label, rationale, "
            "is_indoor (boolean), has_walls (boolean), visible_floor (boolean), "
            "and room_kind ('garage' or 'interior'). "
            + ("This is a house: you MUST choose one enclosed garage AND one other interior room. "
               if lead.property_type == "houses" else "Choose two different enclosed rooms/areas. ")
            + ("This is an INDUSTRIAL property: at least one selection must be an actual warehouse, factory, industrial workshop or loading-area INTERIOR; the other can be an attached industrial office or another industrial room. Never choose residential living rooms, bedrooms, kitchens or home garages for an industrial lead. " if lead.property_type == "industrial properties" else "")
            + "If a valid pair is unavailable return {\"selected\": []}. Return JSON only."
        )
        if using_sheets:
            prompt += (" The supplied images are numbered contact sheets of ORIGINAL property photos. "
                       "Return the PHOTO NUMBER printed below the selected original photo, not the sheet index. "
                       "The contact sheets are only an index; select individual original photographs from them.")
        result = self._vision_json(prompt, paths)
        (lead_dir/'room_selection.json').write_text(json.dumps(result,indent=2))
        selected = result.get("selected", [])
        if not isinstance(selected, list) or len(selected) != 2:
            if lead.source_site.startswith("Imported ") and len(downloaded) < len({img.url for img in lead.images}):
                raise RuntimeError("Some imported property photos were unavailable. Please retry so the complete gallery can be checked.")
            return []
        out = []
        indices = set()
        kinds = []
        for i, item in enumerate(selected):
            if not isinstance(item, dict):
                return []
            idx = item.get("index")
            if type(idx) is not int or not 1 <= idx <= len(downloaded) or idx in indices:
                return []
            if any(item.get(key) is not True for key in ["is_indoor", "has_walls", "visible_floor"]):
                return []
            kind = item.get("room_kind")
            if kind not in {"garage", "interior"}:
                return []
            indices.add(idx)
            kinds.append(kind)
            img, path = downloaded[idx-1]
            out.append(RoomSelection(before_image_url=img.url, before_local_path=path,
                room_label=str(item.get("room_label") or f"Room {i+1}"),
                style_label=STYLE_LABELS[i], rationale=str(item.get("rationale", ""))))
        if lead.property_type == "houses" and set(kinds) != {"garage", "interior"}:
            return []
        if using_sheets:
            verification = self._vision_json(
                "Verify these two full-size original property photographs. Return JSON with valid_pair boolean. "
                "Both MUST be actual distinct indoor rooms with visible walls and usable floors. "
                "Reject outdoor/covered outdoor spaces, floor plans, computer renderings, and photos of the same room. "
                + ("Exactly one MUST be an enclosed garage and the other an interior room. " if lead.property_type == "houses" else "")
                + "Return {\"valid_pair\": true} only if all requirements are met.",
                [room.before_local_path for room in out])
            (lead_dir/'room_verification.json').write_text(json.dumps(verification,indent=2))
            if verification.get('valid_pair') is not True:
                return []
        return out

    def render_after_images(self, lead: Lead, lead_dir: Path) -> Lead:
        if not settings.style_ref_paths:
            raise RuntimeError("No epoxy style samples found in assets/styles.")
        selections = lead.selected_rooms or self.select_room_images(lead, lead_dir)
        lead.selected_rooms = selections
        if not selections:
            lead.status = "no_suitable_images"
            return lead
        def render_room(pair):
            idx, sel = pair
            style_path = settings.style_ref_paths[idx % len(settings.style_ref_paths)] if settings.style_ref_paths else None
            if not style_path:
                raise RuntimeError("Missing epoxy reference sample.")
            out_path = lead_dir / f"after_{idx+1}.png"
            prompt = (
                "Edit the first reference image (the target room photo) into a polished conceptual epoxy-floor after image. "
                "Preserve the room layout, perspective, walls, ceiling, windows, doors, fixtures, cabinetry, furniture, appliances, decor, equipment, and lighting. "
                "Transform only the visible floor surfaces. Use the second reference image only as a style inspiration for the epoxy pattern. "
                f"Apply a {sel.style_label} style. Make the result glossy and premium, suitable for a sales prospecting deck. "
                "Do not add or remove objects. Keep the composition matching the original room photo."
            )
            if not out_path.exists():
                self._generate_image(sel.before_local_path, str(style_path), prompt, out_path)
            sel.after_local_path = str(out_path)
            from PIL import Image
            with Image.open(out_path) as generated:
                generated.verify()
            return sel
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            selections = list(pool.map(render_room, enumerate(selections)))
        lead.selected_rooms = selections
        lead.status = "rendered"
        return lead
