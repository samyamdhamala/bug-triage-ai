import streamlit as st
import requests
import json
from pathlib import Path

BACKEND_URL = "http://localhost:8000"

st.set_page_config(page_title="Bug Triage AI", layout="wide")

if "access_token" not in st.session_state:
    st.session_state.access_token = None
    st.session_state.email = None


def auth_headers() -> dict:
    return {"Authorization": f"Bearer {st.session_state.access_token}"}


def login_signup_screen():
    st.title("🤖 AI Bug Triage")
    st.markdown("Sign in or create an org to get started.")

    tab_login, tab_signup = st.tabs(["Log in", "Sign up"])

    with tab_login:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Log in", type="primary")
        if submitted:
            try:
                r = requests.post(f"{BACKEND_URL}/auth/login", json={"email": email, "password": password}, timeout=15)
                if r.status_code == 200:
                    st.session_state.access_token = r.json()["access_token"]
                    st.session_state.email = email
                    st.rerun()
                else:
                    st.error(r.json().get("detail", "Login failed"))
            except requests.exceptions.RequestException as e:
                st.error(f"Backend not running? Start with: `uvicorn backend.main:app --reload --port 8000`\n\nError: {e}")

    with tab_signup:
        with st.form("signup_form"):
            org_name = st.text_input("Org name")
            name = st.text_input("Your name", value="")
            email = st.text_input("Email", key="signup_email")
            password = st.text_input("Password (min 8 chars)", type="password", key="signup_password")
            submitted = st.form_submit_button("Create org + account", type="primary")
        if submitted:
            try:
                r = requests.post(
                    f"{BACKEND_URL}/auth/signup",
                    json={"org_name": org_name, "name": name, "email": email, "password": password},
                    timeout=15,
                )
                if r.status_code == 200:
                    st.session_state.access_token = r.json()["access_token"]
                    st.session_state.email = email
                    st.rerun()
                else:
                    st.error(r.json().get("detail", "Signup failed"))
            except requests.exceptions.RequestException as e:
                st.error(f"Backend not running? Start with: `uvicorn backend.main:app --reload --port 8000`\n\nError: {e}")


def get_connect_redirect_url(path: str, params: dict) -> str | None:
    """Hits a /connect endpoint with our auth header (a plain <a href> can't carry
    one) and returns the Location it redirects to, so we can hand the USER that
    URL to click through to Atlassian/Slack directly."""
    try:
        r = requests.get(f"{BACKEND_URL}{path}", params=params, headers=auth_headers(), timeout=15, allow_redirects=False)
        if r.status_code in (302, 307):
            return r.headers.get("location")
        st.error(f"Could not start connect flow: {r.status_code} {r.text}")
    except requests.exceptions.RequestException as e:
        st.error(f"Backend not running? {e}")
    return None


def integrations_tab():
    st.subheader("Jira")
    project_key = st.text_input("Jira project key", value="BT")
    if st.button("Connect Jira"):
        url = get_connect_redirect_url("/integrations/jira/connect", {"project_key": project_key})
        if url:
            st.link_button("Continue to Atlassian →", url)

    st.markdown("---")
    st.subheader("Slack")
    bugs_channel = st.text_input("Bugs channel name (no #)", value="bugs")
    if st.button("Connect Slack"):
        url = get_connect_redirect_url("/integrations/slack/connect", {"bugs_channel": bugs_channel})
        if url:
            st.link_button("Continue to Slack →", url)


def triage_tab():
    sample_dir = Path(__file__).parent.parent / "sample_data"
    samples = list(sample_dir.glob("*.txt")) if sample_dir.exists() else []

    col1, col2 = st.columns([3, 1])

    with col1:
        selected_sample = st.selectbox("Load Sample", ["Custom"] + [f.stem for f in samples])
        if selected_sample != "Custom" and samples:
            default_text = (sample_dir / f"{selected_sample}.txt").read_text()
        else:
            default_text = ""

        raw_bug = st.text_area(
            "Raw Bug Report",
            value=default_text,
            height=200,
            placeholder="Paste Slack message, email, or note here...",
        )

    with col2:
        st.info("**Confidence Guide**")
        st.markdown("- 🟢 High: Safe for automation")
        st.markdown("- 🟡 Medium: Quick review recommended")
        st.markdown("- 🔴 Low: **Human review required**")

    if st.button("🚀 Triage Bug", type="primary"):
        if not raw_bug.strip():
            st.error("Please enter a bug report.")
        else:
            try:
                response = requests.post(
                    f"{BACKEND_URL}/triage",
                    json={"bug": raw_bug},
                    headers=auth_headers(),
                    timeout=120,
                )
                if response.status_code == 200:
                    triage = response.json()
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

                    with st.expander("📋 Structured Ticket", expanded=True):
                        for key, value in triage.items():
                            if isinstance(value, list):
                                st.write(f"**{key.replace('_', ' ').title()}:**")
                                for item in value:
                                    st.write(f"  - {item}")
                            else:
                                st.write(f"**{key.replace('_', ' ').title()}:** {value}")

                    json_str = json.dumps(triage, indent=2)
                    st.download_button("💾 Download JSON", json_str, file_name="triaged_bug.json", mime="application/json")

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
                elif response.status_code == 401:
                    st.error("Session expired — please log in again.")
                    st.session_state.access_token = None
                    st.rerun()
                else:
                    st.error(f"Backend error: {response.text}")
            except requests.exceptions.RequestException as e:
                st.error(f"Backend not running? Start with: `uvicorn backend.main:app --reload --port 8000`\n\nError: {e}")


if not st.session_state.access_token:
    login_signup_screen()
else:
    st.sidebar.write(f"Logged in as **{st.session_state.email}**")
    if st.sidebar.button("Log out"):
        st.session_state.access_token = None
        st.session_state.email = None
        st.rerun()

    st.title("🤖 AI Bug Triage MVP")
    st.markdown("---")

    tab_triage, tab_integrations = st.tabs(["Triage", "Integrations"])
    with tab_triage:
        triage_tab()
    with tab_integrations:
        integrations_tab()

    st.markdown("---")
