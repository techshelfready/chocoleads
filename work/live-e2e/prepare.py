from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import json,sys
from src.lead_sources.web_research import WebResearchSource
from src.models import Lead
from src.image_pipeline import OpenAIFloorRenderer
kind=sys.argv[1];items=json.loads(Path(sys.argv[2]).read_text())
def prepare(item):
 lead=Lead(**item);folder=Path('work/live-e2e/prepared')/lead.lead_id;folder.mkdir(parents=True,exist_ok=True)
 if (folder/'lead.json').exists():
  saved=Lead(**json.loads((folder/'lead.json').read_text()))
  if len(saved.selected_rooms)==2:return saved.address,len(saved.images),[r.room_label for r in saved.selected_rooms]
 source=WebResearchSource(kind);source.hydrate(lead)
 (folder/'lead.json').write_text(lead.model_dump_json(indent=2))
 print('GALLERY',lead.address,len(lead.images),flush=True)
 if len(lead.images)>1:
  lead.selected_rooms=OpenAIFloorRenderer().select_room_images(lead,folder)
  (folder/'lead.json').write_text(lead.model_dump_json(indent=2))
 return lead.address,len(lead.images),[r.room_label for r in lead.selected_rooms]
with ThreadPoolExecutor(max_workers=3) as pool:
 for f in as_completed([pool.submit(prepare,item) for item in items]):
  try:print('PREPARED',f.result(),flush=True)
  except Exception as e:print('ERROR',type(e).__name__,str(e)[:250],flush=True)
