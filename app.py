from __future__ import annotations
import os
from pathlib import Path
import streamlit as st
from src.config import settings
from src.auth import require_login
from src.pipeline import generate_leads

st.set_page_config(page_title="ChocoLeads AI", layout="wide")

CSS = """
<style>
.block-container {padding-top: 1rem; padding-bottom: 2rem;}
.hero {background: linear-gradient(135deg, #0E2242 0%, #122E59 65%, #1b437b 100%); padding: 1.4rem 1.6rem; border-radius: 18px; color: white;}
.metric-card {background: #f8f9fb; padding: 1rem; border-radius: 14px; border: 1px solid #e9ecf2;}
.small-muted {color: #6b7280; font-size: 0.9rem;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

if not require_login():
    st.stop()

cols = st.columns([1, 3])
with cols[0]:
    if settings.logo_path.exists():
        st.image(str(settings.logo_path), width="stretch")
with cols[1]:
    st.markdown("<div class='hero'><h1>ChocoLeads AI</h1><h3>Floors Today. Bigger Tomorrow.</h3><p>Generate branded lead decks with before/after epoxy concepts.</p></div>", unsafe_allow_html=True)

def clear_result():
    st.session_state.pop("report_result", None)
    st.session_state.pop("report_error", None)


with st.container(border=True):
    st.subheader("Generate leads")
    zip_col, type_col, count_col = st.columns([1, 2, 1])
    with zip_col:
        zipcode = st.text_input("Zipcode", max_chars=5, value="33130", placeholder="33130", key="zipcode", on_change=clear_result)
    with type_col:
        property_type = st.selectbox("Property type", ["commercial properties", "houses", "industrial properties"], key="property_type", on_change=clear_result)
    with count_col:
        lead_count = st.selectbox("Number of leads", [5, 6, 7, 8, 9, 10], key="lead_count", on_change=clear_result)
    start = st.button("Generate Leads", type="primary", width="stretch", on_click=clear_result)
    st.caption("For houses, we try Zillow, Redfin, then Realtor.com in each ZIP before searching nearby ZIP codes.")

if not settings.openai_api_key:
    st.warning("Lead generation needs an OpenAI API key. Set OPENAI_API_KEY in the project .env file, then restart the app.")

if start:
    if not zipcode or len(zipcode) != 5 or not zipcode.isdigit():
        st.error("Enter a valid five-digit US ZIP code.")
    elif not settings.openai_api_key:
        st.error("Configure the OpenAI API key before generating leads.")
    else:
        with st.status("Finding properties and preparing your report...", expanded=True) as status:
            progress_text = st.empty()
            try:
                run_id, leads, pdf_path = generate_leads(zipcode, property_type, int(lead_count), progress=progress_text.write)
                report = Path(pdf_path)
                st.session_state.report_result = {
                    "count": len(leads), "filename": report.name, "pdf": report.read_bytes()
                }
                status.update(label="Report ready", state="complete", expanded=False)
            except Exception as exc:
                import logging
                logging.exception("Lead generation failed")
                status.update(label="The requested report could not be completed", state="error", expanded=False)
                st.session_state.report_error = (str(exc) if isinstance(exc, (RuntimeError, ValueError)) else "The search or image service could not complete all requested leads. Any completed work has been saved. Please try again.")

if st.session_state.get("report_error"):
    st.error(st.session_state.report_error)

result = st.session_state.get("report_result")
if result:
    st.success(f"Your report with {result['count']} leads is ready.")
    st.download_button("Download PDF Report", result["pdf"], file_name=result["filename"],
                       mime="application/pdf", on_click="ignore", key="report_download")
