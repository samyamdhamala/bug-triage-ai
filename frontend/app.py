import streamlit as st
import requests
import json
from pathlib import Path
import os

BACKEND_URL = "http://localhost:8000"

st.set_page_config(page_title="Bug Triage AI", layout="wide")

st.title("🤖 AI Bug Triage MVP")
st.markdown("---")

# Sidebar for config
st.sidebar.header("Config")
sample_dir = Path(__file__).parent.parent / "sample_data"
samples = list(sample_dir.glob("*.txt")) if sample_dir.exists() else []

selected_sample = st.sidebar.selectbox(
    "Load Sample",
    ["Custom"] + [f.stem for f in samples]
)

# Main input
col1, col2 = st.columns([3, 1])

with col1:
    if selected_sample != "Custom" and samples:
        sample_path = sample_dir / f"{selected_sample}.txt"
        default_text = sample_path.read_text()
    else:
        default_text = ""

    raw_bug = st.text_area(
        "Raw Bug Report",
        value=default_text,
        height=200,
        placeholder="Paste Slack message, email, or note here..."
    )

with col2:
    st.info("**Confidence Guide**")
    st.markdown("- 🟢 High: Safe for automation")
    st.markdown("- 🟡 Medium: Quick review recommended")
    st.markdown("- 🔴 Low: **Human review required**")

# Triage button
if st.button("🚀 Triage Bug", type="primary"):
    if not raw_bug.strip():
        st.error("Please enter a bug report.")
    else:
        try:
            response = requests.post(
                f"{BACKEND_URL}/triage",
                json={"bug": raw_bug},
                timeout=120
            )
            if response.status_code == 200:
                triage = response.json()
                # Display
                col_a, col_b, col_c = st.columns(3)
                
                with col_a:
                    st.metric("Severity", triage["severity"])
                    conf_emoji = {"High": "🟢", "Medium": "🟡", "Low": "🔴"}.get(triage["confidence"], "⚪")
                    st.metric("Confidence", f"{conf_emoji} {triage['confidence']}")
                
                with col_b:
                    st.subheader("Assignee")
                    st.write(triage["suggested_assignee_team"])
                
                with col_c:
                    st.subheader("Labels")
                    labels = ", ".join(triage["suggested_labels"])
                    st.write(labels or "None")
                
                # Full output
                with st.expander("📋 Structured Ticket", expanded=True):
                    for key, value in triage.items():
                        if isinstance(value, list):
                            st.write(f"**{key.replace('_', ' ').title()}:**")
                            for item in value:
                                st.write(f"  - {item}")
                        else:
                            st.write(f"**{key.replace('_', ' ').title()}:** {value}")
                
                # Raw JSON download
                json_str = json.dumps(triage, indent=2)
                st.download_button(
                    "💾 Download JSON",
                    json_str,
                    file_name="triaged_bug.json",
                    mime="application/json"
                )
                
                # Human-in-loop
                st.markdown("---")
                st.header("👥 Human-in-the-loop Decision Points")
                st.markdown("""
                **AI automates**:
                - Standardizes intake & formatting
                - Applies severity rubric consistently
                - Flags uncertainty via confidence
                
                **Always review**:
                - Low confidence (needs human context)
                - P1 severity (high stakes)
                - Generated repro steps (validate)
                
                **Final call**: Prioritization + assignee still benefits from human judgment.
                """)
            else:
                st.error(f"Backend error: {response.text}")
        except requests.exceptions.RequestException as e:
            st.error(f"Backend not running? Start with: `uvicorn backend.main:app --reload --port 8000`\n\nError: {e}")

# Footer
st.markdown("---")
