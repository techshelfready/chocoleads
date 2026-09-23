from __future__ import annotations
import os
import streamlit as st
from .config import settings


def require_login():
    st.session_state.setdefault("authenticated", False)
    if st.session_state["authenticated"]:
        return True

    if settings.logo_path.exists():
        st.image(str(settings.logo_path), width=240)
    st.markdown("## 🔒 ChocoLeads AI Login")
    with st.form("login_form"):
        pwd = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Enter")
        if submitted:
            if pwd and pwd == settings.app_password:
                st.session_state["authenticated"] = True
                st.success("Access granted.")
                st.rerun()
            else:
                st.error("Invalid password.")
    return False
