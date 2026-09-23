from __future__ import annotations
import json
import uuid
from pathlib import Path
from .models import Lead
from .config import settings
from .storage import seen_key_set, make_run_dir, make_lead_dir, append_leads
from .lead_sources.bizbuysell import BizBuySellSource
from .lead_sources.google_places import GooglePlacesFallbackSource
from .lead_sources.housing import HousingSource
from .lead_sources.industrial import IndustrialSource
from .image_pipeline import OpenAIFloorRenderer
from .pdf_report import BrandedPDFReport
from .geography import search_zipcodes
from .lead_sources.web_research import WebResearchSource


def source_chain_for(property_type):
    if property_type not in {'houses','commercial properties','industrial properties'}:
        raise ValueError('Choose a supported property type.')
    return [WebResearchSource(property_type)]


def complete_lead(lead):
    rooms = lead.selected_rooms
    return (len(rooms) == 2 and len({r.before_local_path for r in rooms}) == 2
            and all(r.before_local_path and r.after_local_path
                    and Path(r.before_local_path).is_file() and Path(r.after_local_path).is_file()
                    for r in rooms))


def generate_leads(zipcode, property_type, lead_count, progress=None):
    import logging
    original_progress = progress
    def progress(message):
        logging.getLogger('chocoleads').info(message)
        if original_progress:
            original_progress(message)
    if lead_count not in range(5, 11):
        raise ValueError('Choose between 5 and 10 leads.')
    areas = iter(search_zipcodes(zipcode.strip()))
    first = next(areas)  # Validate location before creating a run or charging for renders.
    from itertools import chain
    run_id = uuid.uuid4().hex[:12]
    run_dir = make_run_dir(run_id)
    renderer = OpenAIFloorRenderer()
    sources = source_chain_for(property_type)
    seen = seen_key_set()
    processed = []
    searched = []
    errors = []
    consecutive_source_failures = 0
    consecutive_empty_areas = 0
    search_attempts = []

    def save_manifest():
        (run_dir / 'run.json').write_text(json.dumps({
            'run_id': run_id, 'requested_zipcode': zipcode, 'requested_count': lead_count,
            'searched_zipcodes': searched, 'errors': errors, 'search_attempts': search_attempts,
            'leads': [lead.model_dump() for lead in processed],
        }, indent=2))

    try:
        def batches():
            yield [first[0]], first[1]
            if any(callable(getattr(type(s), 'search_area', None)) for s in sources):
                from itertools import islice
                while batch := list(islice(areas, 12)):
                    yield [z for z, _ in batch], batch[-1][1]
            else:
                for z, distance in areas:
                    yield [z], distance
        for area_zips, miles in batches():
            search_zip=area_zips[0]
            searched.extend(area_zips)
            if progress:
                progress(f'{len(processed)} of {lead_count} leads ready. Searching ZIPs {", ".join(area_zips)}'
                         + (f' (about {miles:.0f} miles from {zipcode}).' if miles else '.'))
            successful_sources = 0
            area_candidates = 0
            for source in sources:
                if progress:
                    progress(f"{len(processed)} of {lead_count} leads ready. Trying {source.name} in ZIP {search_zip}...")
                try:
                    limit=max((lead_count-len(processed))*2, 5)
                    if callable(getattr(type(source), 'search_area', None)):
                        candidates = source.search_area(area_zips, limit=limit)
                    else:
                        candidates = source.search(search_zip, limit=limit, category=property_type)
                    successful_sources += 1
                    area_candidates += len(candidates)
                    search_attempts.append({'zip': search_zip, 'source': source.name,
                                            'candidates': len(candidates)})
                    save_manifest()
                except Exception as exc:
                    errors.append({'zip': search_zip, 'source': source.name, 'error': type(exc).__name__})
                    save_manifest()
                    if progress:
                        progress(f'{source.name} is unavailable in ZIP {search_zip}; trying the next source.')
                    continue
                for lead in candidates:
                    keys = {lead.address.strip().lower(), lead.source_url.strip().lower()} - {''}
                    if not keys or keys & seen:
                        continue
                    seen.update(keys)
                    if callable(getattr(type(source), 'hydrate', None)):
                        if progress:
                            progress(f'Fetching the original property gallery: {len(processed)} of {lead_count} ready.')
                        source.hydrate(lead)
                        if len(lead.images) < 2:
                            errors.append({'zip': search_zip, 'source': source.name, 'error': 'insufficient_property_photos', 'url': lead.source_url})
                            save_manifest()
                            continue
                    lead.run_id = run_id
                    lead.zipcode = lead.zipcode or search_zip
                    lead.property_type = property_type
                    # A unique suffix prevents two similarly named properties sharing image files.
                    lead_dir = make_lead_dir(run_id, lead.address + '-' + uuid.uuid4().hex[:8])
                    lead.asset_dir = str(lead_dir)
                    if progress:
                        progress(f'Preparing before/after images: {len(processed)} of {lead_count} leads ready.')
                    # API/authentication/render failures are surfaced immediately, not hidden by
                    # searching and charging for more properties with the same broken configuration.
                    lead.selected_rooms = renderer.select_room_images(lead, lead_dir)
                    if len(lead.selected_rooms) != 2:
                        errors.append({'zip': search_zip, 'source': source.name, 'error': 'no_eligible_indoor_pair', 'url': lead.source_url})
                        save_manifest()
                        continue
                    lead.status = 'selected'
                    processed.append(lead)
                    save_manifest()
                    if len(processed) == lead_count:
                        break
                if len(processed) == lead_count:
                    break
            if len(processed) == lead_count:
                break
            consecutive_empty_areas = consecutive_empty_areas + 1 if not area_candidates else 0
            if consecutive_empty_areas >= 3:
                raise RuntimeError('No accessible property candidates were found after three search areas. The sources could not supply the requested properties; completed work was saved.')
            consecutive_source_failures = consecutive_source_failures + 1 if not successful_sources else 0
            if consecutive_source_failures >= 3:
                raise RuntimeError('Property sources are unavailable in three successive ZIP searches. Please retry later.')
        if len(processed) != lead_count:
            raise RuntimeError(f'Only {len(processed)} of {lead_count} usable leads were found after expanding the search. No incomplete report was marked successful.')
        if progress:
            progress(f'All {lead_count} properties verified. Generating {lead_count*2} epoxy after-images...')
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {pool.submit(renderer.render_after_images, lead, Path(lead.asset_dir)): lead for lead in processed}
            finished = 0
            for future in as_completed(futures):
                lead = future.result()
                if not complete_lead(lead):
                    raise RuntimeError('An image pair could not be completed. The run was saved for diagnosis.')
                finished += 1
                save_manifest()
                if progress:
                    progress(f'Finished epoxy images for {finished} of {lead_count} properties.')
        pdf_path = run_dir / f'chocoleads_{property_type.replace(" ", "_")}_{zipcode}_{run_id}.pdf'
        BrandedPDFReport().build(processed, run_id, pdf_path)
        for lead in processed:
            lead.pdf_path = str(pdf_path)
            lead.status = 'completed'
        append_leads(processed, run_id)
        save_manifest()
        return run_id, processed, str(pdf_path)
    except Exception:
        # Preserve completed image work and record its status even if a later lead fails.
        for lead in processed:
            lead.status = 'incomplete_run'
        if processed:
            append_leads(processed, run_id)
        save_manifest()
        raise
