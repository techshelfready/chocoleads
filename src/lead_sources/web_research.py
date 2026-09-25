"""Grounded property and gallery discovery through OpenAI hosted web search."""
from __future__ import annotations
import hashlib, json, re, time
from urllib.parse import urlparse
from openai import OpenAI
from ..config import settings
from ..models import Lead, CandidateImage
from .scraper_utils import fetch_soup

PRIORITIES = {
 'houses': 'Zillow, then Redfin, then Realtor.com, then local brokerage listing pages',
 'commercial properties': 'BizBuySell first, then actual business websites and commercial brokerage listings; restaurants, shops, offices and gyms',
 'industrial properties': 'Crexi first, then CommercialCafe, then local industrial brokerage listings for warehouses, workshops and flex space',
}

def parse_json(text):
    return json.loads(re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip()))


def zillow_property(soup, url):
    match=re.search(r'/(\d+)_zpid',url)
    tag=soup.find('script',id='__NEXT_DATA__')
    if not match or not tag:return None
    candidates=[]
    def visit(value):
        if isinstance(value,dict):
            if str(value.get('zpid'))==match[1] and isinstance(value.get('responsivePhotos'),list):
                candidates.append(value)
            for key,item in value.items():
                if key=='gdpClientCache' and isinstance(item,str):
                    try:visit(json.loads(item))
                    except (ValueError,TypeError):pass
                elif isinstance(item,(dict,list)):visit(item)
        elif isinstance(value,list):
            for item in value:visit(item)
    visit(json.loads(tag.string or tag.get_text()))
    return max(candidates,key=lambda p:len(p['responsivePhotos']),default=None)


def zillow_images(prop,url):
    images=[]
    for photo in prop.get('responsivePhotos',[]):
        sources=photo.get('mixedSources',{}).get('jpeg',[])
        source=max(sources,key=lambda p:p.get('width',0),default={}).get('url') or photo.get('url')
        if source:images.append(CandidateImage(url=source,source=url,caption=photo.get('caption') or ''))
    return images


class WebResearchSource:
    name='Web research'
    def __init__(self, property_type):
        self.property_type=property_type
        self.name='Web research: '+PRIORITIES[property_type].split(';')[0]
        self.client=OpenAI(api_key=settings.openai_api_key,timeout=240,max_retries=1)
        self.cache=settings.data_dir/'web_cache'
        self.cache.mkdir(parents=True,exist_ok=True)
        self.last_search={}
        self.anchor_zip=None

    def research(self,prompt,cache_key,max_tokens=7000):
        path=self.cache/(hashlib.sha256(f'{settings.openai_text_model}:{settings.openai_reasoning_effort}:{cache_key}'.encode()).hexdigest()+'.json')
        if path.exists() and time.time()-path.stat().st_mtime < 86400:return json.loads(path.read_text())
        response=self.client.responses.create(model=settings.openai_text_model,reasoning={'effort':settings.openai_reasoning_effort},
            tools=[{'type':'web_search'}],tool_choice='required',
            include=['web_search_call.results','web_search_call.action.sources'],input=prompt,max_output_tokens=max_tokens)
        if response.status!='completed':raise RuntimeError('Web research did not complete. Please retry.')
        result=parse_json(response.output_text)
        result['_response_id']=response.id
        result['_web_calls']=[i.model_dump() for i in response.output if i.type=='web_search_call']
        path.write_text(json.dumps(result,indent=2))
        return result

    def search(self,zipcode,limit,category=None):
        return self.search_area([zipcode], limit)

    def search_area(self, zipcodes, limit):
        zipcode=zipcodes[0]
        self.anchor_zip=self.anchor_zip or zipcode
        area_description = f'US ZIP {zipcode}' if len(zipcodes)==1 else f'these US ZIPs in nearest-first order: {", ".join(zipcodes)}'
        prompt=(f'Find up to {limit} distinct real {self.property_type} in {area_description}. '
            f'Try sources in this order: {PRIORITIES[self.property_type]}. '
            'Use live web search and open listing pages. Return individual properties, never search-result/category pages. '
            'Verify the actual full street address and postal ZIP from the listing, not a street number matching the ZIP. '
            'Stay inside the supplied ZIP list. Prioritize the closest ZIP and exhaust the preferred source sequence within a ZIP before moving farther. '
            + ('Only detached single-family houses with an ACTUAL PHOTOGRAPH of the ENCLOSED GARAGE INTERIOR plus indoor living-room photos. A garage mentioned in the description or an exterior garage-door photo is NOT enough. Search specifically for garage-interior photographs and return the observed garage_photo_url. Sales, rentals and off-market homes with original listing photos are all eligible; accurately include listing_status. No apartments, condos, vacant lots or new-construction renderings. ' if self.property_type=='houses' else 'Favor actual properties with multiple original indoor photos showing walls and floors. ')
            + ('INDUSTRIAL means actual warehouse, manufacturing, logistics or workshop space. Do not substitute retail stores, residential homes, restaurants or pure office buildings. ' if self.property_type=='industrial properties' else '')
            + 'Return JSON only: {"leads":[{"address":"full street address, city, state and ZIP", "zipcode":"five digits", "source_url":"actual individual listing URL", "source_site":"name", "title":"name", "price":"if known", "size":"if known", "garage_photo_url":"observed original garage interior image URL for houses", "listing_status":"sale/rental/off-market/unknown"}]}. '
            'Never fabricate properties or URLs. Return an empty leads list if none can be verified. Do not ask questions.')
        if self.property_type=='houses' and len(zipcodes)>1:
            prompt=(f'Find single-family house listings near US ZIP {self.anchor_zip} that specifically have PHOTOGRAPHS of an ENCLOSED GARAGE INTERIOR '
                    '(not an exterior garage door) as well as indoor living-room photos. Use web search, Zillow, Redfin, Realtor and brokers. '
                    'A garage described in the listing without an actual garage interior photo is not enough. '
                    f'Search broadly within these nearby ZIPs: {zipcodes}. Need up to {limit} real properties. '
                    'Sales, rentals and off-market properties with real photos are eligible. '
                    'Return JSON {"leads":[{"address":"full address", "zipcode":"actual ZIP", "source_url":"individual listing URL", '
                    '"source_site":"site", "garage_photo_url":"observed original enclosed garage interior photo URL or empty if unavailable", '
                    '"listing_status":"sale/rental/off-market/unknown"}]}. Do not invent URLs or properties. Exclude condos and apartments. No questions.')
        data=self.research(prompt,f'discovery-v6-{self.property_type}-{zipcodes}-{limit}' if self.property_type=='houses' else f'discovery-v4-{self.property_type}-{zipcodes}-{limit}')
        observed=json.dumps(data.get('_web_calls',[]))
        out=[]
        for item in data.get('leads',[]):
            url=item.get('source_url') or ''
            if not url.startswith('https://') or url not in observed or item.get('zipcode') not in zipcodes:continue
            if not re.search(r'\d',item.get('address') or ''):continue
            out.append(Lead(lead_id=hashlib.sha256(url.encode()).hexdigest()[:16],property_type=self.property_type,
                address=item['address'],zipcode=item['zipcode'],source_site=item.get('source_site') or urlparse(url).netloc,
                source_url=url,title=str(item.get('title') or ''),price=str(item.get('price') or ''),size=str(item.get('size') or ''),
                notes=f"Listing status: {item.get('listing_status','unknown')}. Hosted web search response {data['_response_id']}",
                images=[CandidateImage(url=item['garage_photo_url'],source=url,caption='Enclosed garage interior')] if str(item.get('garage_photo_url') or '').startswith('https://') else []))
        self.last_search={'verified_candidates':len(out),'response_id':data['_response_id']}
        return out

    def brochure_images(self, lead, url):
        import requests, io
        from pypdf import PdfReader
        from PIL import Image
        response=requests.get(url,timeout=settings.request_timeout)
        response.raise_for_status()
        if not response.content.startswith(b'%PDF-'):
            return []
        folder=self.cache / ('brochure-'+hashlib.sha256(url.encode()).hexdigest()[:20])
        folder.mkdir(exist_ok=True)
        (folder/'source.pdf').write_bytes(response.content)
        reader=PdfReader(io.BytesIO(response.content))
        # The exact street number and street-name words must occur in the brochure.
        text=' '.join(page.extract_text() or '' for page in reader.pages).lower()
        tokens=re.findall(r'[a-z0-9]+',lead.address.lower().split(',')[0])
        meaningful=[t for t in tokens if len(t)>2 or t.isdigit()][:3]
        if not meaningful or not all(t in text for t in meaningful):
            return []
        images=[]
        for page_number,page in enumerate(reader.pages[:20],1):
            for i,embedded in enumerate(page.images):
                im=embedded.image
                if im.width<240 or im.height<160:
                    continue
                target=folder/f'page-{page_number}-photo-{i}.png'
                im.save(target)
                images.append(CandidateImage(url=f'{url}#page={page_number}&image={i}',source=url,
                    local_path=str(target),caption=f'Original brochure photo, page {page_number}'))
        return images

    def hydrate(self,lead):
        if urlparse(lead.source_url).path.lower().endswith('.pdf'):
            try:
                lead.images += self.brochure_images(lead,lead.source_url)
                if len(lead.images)>1:return lead
            except Exception:pass
        try:
            soup=fetch_soup(lead.source_url)
            if 'zillow.com' in urlparse(lead.source_url).netloc:
                prop=zillow_property(soup,lead.source_url)
                if prop:
                    if str(prop.get('zipcode'))!=lead.zipcode or prop.get('homeType')!='SINGLE_FAMILY':return lead
                    lead.address=', '.join(str(prop.get(k,'')) for k in ['streetAddress','city','state','zipcode'])
                    lead.images=lead.images + zillow_images(prop,lead.source_url)
                    return lead
        except Exception:pass
        prompt=(f'Open this exact property listing: {lead.source_url}\nTarget property: {lead.address}. '
            'Extract original gallery photo URLs for THIS property only. Click photo links and read gallery sections if needed. '
            'Do not select photos from recommended/nearby properties, stock photos, floor plans, or rendered designs. '
            'Retrieve up to 30 images, prioritizing indoor rooms showing walls and floors. '
            + ('Include the enclosed garage interior if available. ' if self.property_type=='houses' else '')
            + 'Return JSON only {"images":[{"url":"exact observed original image URL", "caption":"listing caption", "source_url":"listing/gallery page containing this image"}], "brochure_urls":["observed PDF brochure URL for this exact property"]}. '
            'For commercial/industrial properties also retrieve the original listing PDF brochure URL if available; it may contain interior photographs. Never construct or guess image URLs. If blocked, find the same full address on another public listing site and read that gallery; include its actual source_url. '
            'No questions. If photos cannot be retrieved return an empty images list.')
        data=self.research(prompt,'gallery-v4-'+lead.source_url if self.property_type=='industrial properties' else 'gallery-v3-'+lead.source_url,max_tokens=6500)
        observed=json.dumps(data.get('_web_calls',[]))
        images=list(lead.images)
        for item in data.get('images',[]):
            url=item.get('url','');source=item.get('source_url') or lead.source_url
            if not url.startswith('https://') or source not in observed:continue
            caption=item.get('caption') or ''
            if any(word in caption.lower() for word in ['rendering','visual purposes','artist','floor plan','stock photo']):continue
            images.append(CandidateImage(url=url,source=source,caption=caption))
        for brochure in data.get('brochure_urls',[])[:2]:
            if isinstance(brochure,str) and brochure.startswith('https://') and brochure in observed:
                try:images += self.brochure_images(lead,brochure)
                except Exception:pass
        lead.images=images
        return lead
