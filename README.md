# ChocoLeads AI

Streamlit app for creating property-lead PDF reports with listing photos and conceptual epoxy-floor edits. The ZIP field is locked while imported datasets supply the leads. Downloading a report leaves it visible until inputs change or a new generation starts.

## Inventory

- Houses: `data/imports/zillow_houses.json` has 200 unique Zillow listings.
- Crexi: `data/imports/commercial_listings.json` and `data/imports/crexi_property_galleries.json` hold the same 290 unique listing IDs, merged from three captures. Of these, 199 have a supported commercial tag, 45 have an industrial tag, and 46 are outside the app's commercial/industrial categories. `data/imports/crexi_extra_galleries.json` supplies additional listing-specific image links.

The app requires at least two listing-specific photos and a valid address before considering a property. It then checks for distinct indoor rooms with visible floors; industrial leads must include an industrial interior, and house leads need an enclosed garage. Portfolio listings with multiple locations are skipped. Photos and listing details are snapshot data, not a live availability check.

## Local setup

Use Python 3.12. Install dependencies with `pip install -r requirements.txt`, copy `.env.example` to `.env`, and set unique values for `APP_PASSWORD` and `OPENAI_API_KEY`. Then run `streamlit run app.py` or `./start-local.command`.

The text and vision model defaults to `gpt-6-sol` with medium reasoning; image editing uses `gpt-image-1`. Override them through the environment variables in `.env.example` if needed.

## Streamlit Community Cloud

Deploy `app.py` from a **private GitHub repository**. The imported JSON files are committed with the app. In Community Cloud's Advanced settings, add root-level secrets:

```toml
APP_PASSWORD = "replace_with_a_unique_password"
OPENAI_API_KEY = "replace_with_your_openai_api_key"
```

Add optional model or service settings there only when changing the defaults. Do not commit `.env` or `.streamlit/secrets.toml`. Root-level Community Cloud secrets are exposed as environment variables and are read by the app.

The SQLite usage databases, `data/leads.csv`, images, and generated PDFs are runtime files and are excluded from Git. Community Cloud does not guarantee persistence of local files across restarts, so used-property tracking there is suitable for inspection only. A durable database is needed before depending on cross-restart deduplication.

## Tracking and outputs

`data/zillow_usage.sqlite3` and `data/crexi_usage.sqlite3` track reserved, used, and ineligible listing IDs. `data/leads.csv` tracks completed reports. The Crexi tracker uses one numeric ID across commercial and industrial categories. Generated images and PDFs stay under `data/assets/` and `runs/`; the imported datasets remain under `data/imports/`.
