# ChocoLeads AI – Streamlit Lead Generation App

A branded Streamlit application that:
- accepts a **zipcode**, **property type**, and **lead count (5–10)**
- finds leads from public listing / business sources
- avoids duplicates by tracking all generated leads in a CSV registry
- selects **2 room photos** with visible floors for each lead
- generates conceptual **before / after epoxy floor** images using OpenAI
- assembles a branded **PDF report** with your logo on every page

## Supported source order

### Commercial properties
1. **BizBuySell** (preferred)
2. **Google Places** fallback (if `GOOGLE_PLACES_API_KEY` is configured and BizBuySell does not return enough results)

### Houses
1. **Zillow**, then **Redfin**, then **Realtor.com** within the same ZIP via search + page parsing
   - the room selector is instructed to choose **one garage** and **one interior room**

### Industrial properties
1. **Crexi**
2. **CommercialCafe**

## Project structure

```text
chocoleads_ai_app/
├── app.py
├── requirements.txt
├── .env.example
├── README.md
├── assets/
│   └── logo.png
├── data/
│   └── leads.csv
├── runs/
└── src/
    ├── auth.py
    ├── config.py
    ├── image_pipeline.py
    ├── lead_sources/
    ├── models.py
    ├── pdf_report.py
    ├── pipeline.py
    ├── storage.py
    └── utils.py
```

## Environment variables

Copy `.env.example` to `.env` and fill in values.

Required:
- `APP_PASSWORD=guveki1234!`
- `OPENAI_API_KEY=...`

Optional:
- `GOOGLE_PLACES_API_KEY=...`
- `OPENAI_VISION_MODEL=gpt-6-astra`
- `OPENAI_IMAGE_MODEL=gpt-image-1`
- `OPENAI_TEXT_MODEL=gpt-6-astra`

## Running locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploying to Streamlit Community Cloud

1. Push this project to GitHub.
2. In Streamlit Community Cloud, create a new app pointing to `app.py`.
3. Add your secrets either as environment variables or Streamlit secrets. Recommended values:
   - `APP_PASSWORD`
   - `OPENAI_API_KEY`
   - `GOOGLE_PLACES_API_KEY` (optional)
4. Ensure writable storage is available for:
   - `data/leads.csv`
   - `data/assets/...`
   - `runs/...`

## Notes / implementation details

- The app is intentionally designed to use **publicly available listing / business photos** and then produce conceptual after-renders.
- CSV tracking prevents duplicate generation by checking source URLs and addresses.
- Every lead stores:
  - source URL
  - property address
  - selected rooms
  - PDF path
  - asset directory
  - run metadata
- The PDF report is **one PDF per run**.
- Every page is branded with the **ChocoLeads AI** logo.

## Important caveat

Public listing sites can change HTML structure at any time. The source adapters are organized per source so you can refine extraction logic as needed.

## Local workflow updates

- Inputs and the report download are on the main page. Lead details and the saved registry are kept out of the UI.
- Completed report bytes remain in the browser session across reruns and downloads. Editing ZIP, property type, or count, or starting another generation, clears the displayed result only; saved files are retained.
- Discovery searches the requested ZIP first, then geographic ZIP centroids in increasing distance order until the selected count (5-10) is ready. There is no fixed neighboring-ZIP cap. Distances are approximate; data attribution is in `assets/ZIP_DATA_LICENSE.txt`.
- Only distinct leads with two complete before/after pairs count toward the report. Outdoor photos and photos without visible walls/floors are rejected. Houses require an enclosed garage and another interior room. Vision classification is used; ambiguous or incomplete selections are rejected without a fallback.
- A source outage or image API failure stops the run with an error instead of publishing an incomplete report. Completed image work is retained in the run manifest and CSV with `incomplete_run` status.
- PDFs reserve a separate header, metadata area, two bounded image-pair blocks, and footer. Original property sources are clickable.
- Tests: `.venv/bin/python -m unittest discover -s tests -v`. The tests use mocked external services and do not incur image-generation charges.

### Housing discovery and default location

The default ZIP is Miami **33130**. Each ZIP is attempted in this order: Zillow, Redfin, Realtor.com. Only after all sources have been tried (unless the requested count is already complete) does discovery move to the nearest ZIP. The progress line identifies the source and ZIP. Search-result landing pages are followed for individual listing links and are never emitted as leads. The maintained `ddgs` package replaces `duckduckgo-search`.

After all sources return no accessible candidates in three consecutive ZIP codes, the app stops with a clear error rather than continuing indefinitely. This does not guarantee access to listing sites that block automated requests. Run manifests record source attempts and candidate counts for diagnosis.
