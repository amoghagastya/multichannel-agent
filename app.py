from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict

import streamlit as st
from dotenv import load_dotenv

from core.config import list_dealers, load_dealer_config
from core.crm import read_mock_leads, clear_mock_leads
from sms_agent.agent import run_sms_turn, clear_agent_cache
import requests
import streamlit.components.v1 as components

LOG_PATH = Path(__file__).resolve().parent / "data" / "voice_logs.jsonl"
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
API_BASE_URL = os.getenv("PUBLIC_API_URL", "http://localhost:8000").rstrip("/")

load_dotenv()

st.set_page_config(
    page_title="DealSmart AI Demo",
    page_icon="/",
    layout="wide",
)

st.markdown(
    """
<style>
:root {
  --bg: #0b0f14;
  --panel: #141a22;
  --panel-2: #0f141b;
  --accent: #00e2a1;
  --accent-2: #4cc3ff;
  --text: #eef2f7;
  --muted: #9aa3b2;
  --border: #1f2633;
}
html, body, [class*="stApp"] {
  background: radial-gradient(900px circle at 10% -10%, #1f2937, #0b0f14 55%);
  color: var(--text);
}
header, [data-testid="stHeader"] {
  visibility: hidden;
  height: 0;
}
section[data-testid="stSidebar"] {
  background: #0a0e13;
  border-right: 1px solid var(--border);
}
.block-container {
  padding-top: 1.5rem;
  padding-bottom: 2rem;
}
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1.2rem;
}
.brand {
  font-size: 1.6rem;
  font-weight: 700;
  letter-spacing: -0.02em;
}
.tagline {
  color: var(--muted);
  margin-top: 0.2rem;
}
.badge {
  display: inline-block;
  padding: 0.25rem 0.7rem;
  border-radius: 999px;
  background: rgba(0, 226, 161, 0.14);
  color: var(--accent);
  font-size: 0.78rem;
  font-weight: 600;
  margin-right: 0.4rem;
}
.badge.alt {
  background: rgba(76, 195, 255, 0.14);
  color: var(--accent-2);
}
.muted { color: var(--muted); }
.stat-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.8rem;
}
.stat {
  background: #0f141b;
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 0.8rem;
}
</style>
""",
    unsafe_allow_html=True,
)

with st.sidebar:
    config_tab, crm_tab = st.tabs(["Config", "Mock CRM"])

    with config_tab:
        st.subheader("Dealership Config")
        dealers = list_dealers() or ["demo_bmw"]
        dealer_id = st.selectbox("Dealer", dealers, index=0)
        config = load_dealer_config(dealer_id)
        if config.logo_url:
            st.image(config.logo_url, width=160)
        st.markdown(f"**Dealer:** {config.dealer_name}")
        st.markdown(f"**Brand:** {config.brand}")
        st.markdown(f"**Tone:** {config.tone}")
        st.markdown("---")
        st.markdown("**Channels Enabled**")
        st.markdown("- SMS")
        st.markdown("- Voice (Inbound)")
        st.markdown("---")
        st.markdown("**OpenAI API Key**")
        st.caption("Set `OPENAI_API_KEY` in your shell or `.env`, then restart.")
        if not os.getenv("OPENAI_API_KEY"):
            st.warning("OPENAI_API_KEY is not set. SMS agent will not run until it is configured.")

    with crm_tab:
        st.subheader("Mock CRM Leads")
        if st.button("Clear Mock CRM"):
            clear_mock_leads()
            st.success("Mock CRM cleared.")
        leads = read_mock_leads(limit=25)
        if not leads:
            st.markdown("<span class='muted'>No leads yet.</span>", unsafe_allow_html=True)
        else:
            for lead in reversed(leads):
                st.json(lead)

st.markdown(
    """
<div class="header">
  <div>
    <div class="brand">DealSmart AI — Max Concierge</div>
    <div class="tagline">Where AI meets your dealership.</div>
  </div>
  <div>
    <span class="badge">Multi-Channel</span>
    <span class="badge alt">CRM-Agnostic</span>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

st.markdown(
    """
<div class="stat-grid">
  <div class="stat">
    <div class="muted">Active Dealer</div>
    <div style="font-size:1.1rem; font-weight:700;">{dealer}</div>
  </div>
  <div class="stat">
    <div class="muted">Primary Channels</div>
    <div style="font-size:1.1rem; font-weight:700;">SMS + Voice</div>
  </div>
  <div class="stat">
    <div class="muted">Status</div>
    <div style="font-size:1.1rem; font-weight:700;">Live Prototype</div>
  </div>
</div>
""".format(dealer=config.dealer_name),
    unsafe_allow_html=True,
)

sms_tab, voice_tab, config_tab = st.tabs(["SMS", "Voice", "Customization"])

with sms_tab:
    st.subheader("SMS Agent")
    st.markdown("<span class='badge'>OpenAI Agents SDK</span>", unsafe_allow_html=True)
    st.markdown("Qualify intent, timeline, budget, and trade-in status in a natural flow.")
    if not os.getenv("OPENAI_API_KEY"):
        st.error("OPENAI_API_KEY is missing. Add it to `.env` or your shell, then restart Streamlit.")

    if "sms_messages" not in st.session_state:
        st.session_state.sms_messages = []

    for msg in st.session_state.sms_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    def _send_sms():
        if not os.getenv("OPENAI_API_KEY"):
            st.toast("Set OPENAI_API_KEY first to enable the SMS agent.", icon="⚠️")
            return
        user_input = st.session_state.get("sms_input", "").strip()
        if not user_input:
            return
        st.session_state.sms_messages.append({"role": "user", "content": user_input})
        fallback_state = st.session_state.get("fallback_state") or {}
        reply, trace = run_sms_turn(
            user_input,
            dealer_id,
            session_id="demo",
            state=fallback_state,
            history=st.session_state.sms_messages,
        )
        st.session_state.sms_messages.append({"role": "assistant", "content": reply})
        st.session_state["sms_trace"] = trace
        if trace.get("state"):
            st.session_state["fallback_state"] = trace["state"]
        st.session_state["sms_input"] = ""

    with st.form("sms_form", clear_on_submit=False):
        st.text_input("Message", placeholder="Type a customer message", key="sms_input")
        st.form_submit_button("Send", on_click=_send_sms, disabled=not bool(os.getenv("OPENAI_API_KEY")))

    with st.expander("Latest Trace"):
        trace: Dict | None = st.session_state.get("sms_trace")
        if trace:
            st.json(trace)
        else:
            st.markdown("<span class='muted'>No trace yet.</span>", unsafe_allow_html=True)

with voice_tab:
    st.subheader("Voice Inbound")
    st.markdown("<span class='badge alt'>Ultravox + Twilio</span>", unsafe_allow_html=True)
    st.markdown("Inbound calls hit your FastAPI webhook, which connects the caller to the Ultravox agent.")
    if PUBLIC_BASE_URL:
        st.markdown(f"**Webhook URL:** `{PUBLIC_BASE_URL}/incoming`")
        st.markdown(f"**TwiML App Voice URL:** `{PUBLIC_BASE_URL}/twiml`")
    else:
        st.markdown("**Webhook URL:** `https://<your-ngrok>/incoming`")
        st.markdown("**TwiML App Voice URL:** `https://<your-ngrok>/twiml`")
    st.markdown("**Twilio Voice Webhook:** Point your number to `/incoming` (POST)")

    agent_number = os.getenv("TWILIO_FROM_NUMBER", "")
    if agent_number:
        st.info(f"Call the agent at: {agent_number}")
    else:
        st.warning("Set TWILIO_FROM_NUMBER to display the agent's phone number.")

    with st.expander("Optional: Trigger an outbound demo call"):
        st.markdown("Use this if you want the agent to call you first.")
        with st.form("voice_call_form", clear_on_submit=False):
            to_number = st.text_input("Phone number", placeholder="+14155551234", key="voice_to_number")
            call_submit = st.form_submit_button("Call Me")
        if call_submit and to_number:
            try:
                resp = requests.post(
                    f"{API_BASE_URL}/outbound",
                    json={"to": to_number, "dealer_id": dealer_id},
                    timeout=10,
                )
                if resp.status_code >= 400:
                        st.error(f"Call failed: {resp.text}")
                else:
                        data = resp.json()
                        st.success(f"Calling {to_number} (Call SID: {data.get('twilio_call_sid')})")
            except requests.RequestException as exc:
                st.error(f"Could not reach FastAPI server on :8000 ({exc})")

    st.subheader("In-App WebRTC Call")
    st.markdown("Call the agent directly from your browser (no phone required).")
    webrtc_src = f"{API_BASE_URL}/webrtc/"
    st.markdown(
        f"""
<iframe
  src="{webrtc_src}"
  style="width: 100%; height: 260px; border: 1px solid #1f2633; border-radius: 12px;"
  allow="microphone; autoplay"
></iframe>
""",
        unsafe_allow_html=True,
    )

    st.subheader("Recent Voice Calls")
    if LOG_PATH.exists():
        lines = LOG_PATH.read_text().strip().splitlines()[-5:]
        if lines and lines[0].strip():
            auto_fetch = st.checkbox("Auto-fetch transcripts", value=True)
            refresh_now = st.button("Refresh Transcripts")
            for line in reversed(lines):
                entry = json.loads(line)
                # Highlight summary if available in webhook payloads
                if entry.get("event") == "ultravox_webhook":
                    call = entry.get("payload", {}).get("call", {})
                    summary = call.get("summary") or call.get("shortSummary")
                    if summary:
                        st.markdown(f"**Summary:** {summary}")
                st.json(entry)
                call_id = entry.get("call_id")
                if call_id:
                    with st.expander(f"Transcript for {call_id}"):
                        try:
                            if auto_fetch:
                                # Live-ish poll of transcript if available
                                detail = requests.get(
                                    f"{API_BASE_URL}/ultravox/calls/{call_id}",
                                    timeout=10,
                                )
                                if detail.status_code < 400:
                                    detail_json = detail.json()
                                    summary = detail_json.get("summary") or detail_json.get("shortSummary")
                                    end_reason = detail_json.get("endReason")
                                    if summary:
                                        st.markdown(f"**Summary:** {summary}")
                                    if end_reason:
                                        st.markdown(f"**End Reason:** {end_reason}")
                                    with st.expander("Raw Call Detail"):
                                        st.json(detail_json)
                                resp = requests.get(
                                    f"{API_BASE_URL}/ultravox/calls/{call_id}/messages",
                                    timeout=10,
                                )
                                if resp.status_code >= 400:
                                    st.error(resp.text)
                                else:
                                    payload = resp.json()
                                    messages = payload.get("messages") if isinstance(payload, dict) else payload
                                    if messages is None:
                                        messages = []
                                    cleaned = []
                                    for msg in messages:
                                        role = msg.get("role") or msg.get("sender") or "unknown"
                                        text = msg.get("text") or msg.get("content") or msg.get("message") or ""
                                        if text:
                                            cleaned.append(f"{role}: {text}")
                                    if cleaned:
                                        st.text("\\n".join(cleaned))
                                    else:
                                        st.markdown("_No transcript messages yet. Try Refresh or wait for call end._")
                                        st.json(messages)
                            else:
                                st.markdown("Enable auto-fetch to load transcripts.")
                        except requests.RequestException as exc:
                            st.error(f"Could not reach FastAPI server on :8000 ({exc})")
        else:
            st.markdown("<span class='muted'>No voice logs yet.</span>", unsafe_allow_html=True)
    else:
        st.markdown("<span class='muted'>No voice logs yet.</span>", unsafe_allow_html=True)

with config_tab:
    st.subheader("Customization & CRM")

    st.markdown("Edit the active dealership settings and save to config.")
    with st.form("config_form"):
        tone = st.text_input("Tone/Persona", value=config.tone)
        sales_qs = st.text_area(
            "Sales Qualifying Questions (one per line)",
            value="\\n".join(config.qualifying_questions.get("sales", [])),
            height=140,
        )
        service_qs = st.text_area(
            "Service Qualifying Questions (one per line)",
            value="\\n".join(config.qualifying_questions.get("service", [])),
            height=100,
        )
        sales_queue = st.text_input("Sales Queue", value=config.routing.get("sales_queue", "sales-bdc"))
        service_queue = st.text_input("Service Queue", value=config.routing.get("service_queue", "service-advisors"))
        nurture_queue = st.text_input("Nurture Queue", value=config.routing.get("nurture_queue", "nurture"))
        crm_provider = st.text_input("CRM Provider", value=config.crm.get("provider", "mock"))
        lead_source = st.text_input("Lead Source", value=config.crm.get("lead_source", "AI Concierge"))
        require_sms_opt_in = st.checkbox(
            "Require SMS Opt-in", value=config.compliance.get("require_sms_opt_in", True)
        )
        require_voice_consent = st.checkbox(
            "Require Voice Consent", value=config.compliance.get("require_voice_consent", True)
        )
        saved = st.form_submit_button("Save Config")

    if saved:
        updated = config.model_copy(deep=True)
        updated.tone = tone
        updated.qualifying_questions["sales"] = [q.strip() for q in sales_qs.splitlines() if q.strip()]
        updated.qualifying_questions["service"] = [q.strip() for q in service_qs.splitlines() if q.strip()]
        updated.routing["sales_queue"] = sales_queue
        updated.routing["service_queue"] = service_queue
        updated.routing["nurture_queue"] = nurture_queue
        updated.crm["provider"] = crm_provider
        updated.crm["lead_source"] = lead_source
        updated.compliance["require_sms_opt_in"] = require_sms_opt_in
        updated.compliance["require_voice_consent"] = require_voice_consent

        config_path = Path(__file__).resolve().parent / "data" / "dealer_configs" / f"{dealer_id}.json"
        config_path.write_text(json.dumps(updated.model_dump(), indent=2))
        clear_agent_cache(dealer_id)
        st.success("Config saved and applied. New SMS runs will use updated tone.")

    st.markdown("**CRM Agnostic Connector**")
    st.markdown("Swap adapters without changing the agent. Implement `CRMAdapter` for GHL, DealerSocket, Salesforce, etc.")
