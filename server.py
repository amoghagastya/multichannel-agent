from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant

from core.config import load_dealer_config

load_dotenv()

app = FastAPI()

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
FRONTEND_DIST = Path(__file__).resolve().parent / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/webrtc", StaticFiles(directory=FRONTEND_DIST, html=True), name="webrtc")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ULTRAVOX_API_KEY = os.getenv("ULTRAVOX_API_KEY", "")
ULTRAVOX_BASE_URL = os.getenv("ULTRAVOX_BASE_URL", "https://api.ultravox.ai/api")
DEFAULT_DEALER_ID = os.getenv("DEFAULT_DEALER_ID", "demo_bmw")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
API_BASE_PATH = os.getenv("API_BASE_PATH", "")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")
TWILIO_API_KEY_SID = os.getenv("TWILIO_API_KEY_SID", "")
TWILIO_API_KEY_SECRET = os.getenv("TWILIO_API_KEY_SECRET", "")
TWILIO_APP_SID = os.getenv("TWILIO_APP_SID", "")
LOG_PATH = Path(__file__).resolve().parent / "data" / "voice_logs.jsonl"


@app.get("/health")
async def health():
    return {"ok": True}

@app.get("/token")
async def token(identity: str = "web_user"):
    if not (TWILIO_ACCOUNT_SID and TWILIO_API_KEY_SID and TWILIO_API_KEY_SECRET and TWILIO_APP_SID):
        return PlainTextResponse("Missing Twilio API Key SID/Secret or TwiML App SID", status_code=500)

    access_token = AccessToken(
        TWILIO_ACCOUNT_SID,
        TWILIO_API_KEY_SID,
        TWILIO_API_KEY_SECRET,
        identity=identity,
    )
    voice_grant = VoiceGrant(outgoing_application_sid=TWILIO_APP_SID, incoming_allow=False)
    access_token.add_grant(voice_grant)
    log_event(
        {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "event": "token_issued",
            "identity": identity,
        }
    )
    token = access_token.to_jwt()
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return {"token": token}


@app.post("/twiml")
async def twiml(request: Request):
    form = await request.form()
    identity = form.get("Caller") or "web_user"
    dealer_id = DEFAULT_DEALER_ID
    log_event(
        {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "event": "twiml_request",
            "caller": identity,
            "form": dict(form),
        }
    )

    config = load_dealer_config(dealer_id)
    if not ULTRAVOX_API_KEY:
        return PlainTextResponse("Missing ULTRAVOX_API_KEY", status_code=500)

    payload: Dict = {
        "systemPrompt": (
            f"You are DealSmart AI for {config.dealer_name}. "
            "You are a polite dealership concierge. "
            "Qualify intent, timeline, budget, and trade-in status. "
            "Never invent inventory or pricing; ask to connect a human if unsure."
        ),
        "medium": {"twilio": {}},
        "recordingEnabled": True,
        "transcriptOptional": False,
        "firstSpeakerSettings": {
            "agent": {
                "text": "Thanks for calling! Are you calling about sales or service today?"
            }
        },
        "metadata": {
            "dealer_id": config.dealer_id,
            "caller": identity,
            "source": "webrtc",
        },
    }
    if PUBLIC_BASE_URL:
        payload["selectedTools"] = build_temporary_tools(PUBLIC_BASE_URL)
        base = f"{PUBLIC_BASE_URL}{API_BASE_PATH}"
        payload["callbacks"] = {
            "joined": {"url": f"{base}/ultravox/webhook"},
            "ended": {"url": f"{base}/ultravox/webhook"},
        }

    try:
        resp = requests.post(
            f"{ULTRAVOX_BASE_URL}/calls",
            headers={
                "Content-Type": "application/json",
                "X-API-Key": ULTRAVOX_API_KEY,
            },
            json=payload,
            timeout=30,
        )
    except requests.RequestException as exc:
        log_event(
            {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "event": "ultravox_error",
                "status": "timeout",
                "body": str(exc),
            }
        )
        fallback = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say>Sorry, we are having trouble connecting the assistant. Please try again.</Say>
  <Hangup/>
</Response>"""
        return Response(content=fallback, media_type="text/xml")
    if resp.status_code >= 400:
        log_event(
            {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "event": "ultravox_error",
                "status": resp.status_code,
                "body": resp.text,
            }
        )
        fallback = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say>Sorry, we are having trouble connecting the assistant. Please try again.</Say>
  <Hangup/>
</Response>"""
        return Response(content=fallback, media_type="text/xml")
    data = resp.json()
    join_url = data.get("joinUrl")

    if not join_url:
        return PlainTextResponse("Ultravox joinUrl missing", status_code=500)

    log_event(
        {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "event": "ultravox_join_url",
            "join_url": join_url,
            "caller": identity,
        }
    )

    twiml = f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<Response>
  <Connect>
    <Stream url=\"{join_url}\" />
  </Connect>
</Response>"""
    return Response(content=twiml, media_type="text/xml")


@app.get("/webrtc")
async def webrtc_page():
    if FRONTEND_DIST.exists():
        return PlainTextResponse("Use /webrtc/ from the built frontend.", status_code=302)
    html = """<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>DealSmart AI WebRTC Dialer</title>
    <script>
      window.TWILIO_SDK_READY = false;
      function onTwilioLoad() {
        window.TWILIO_SDK_READY = true;
        console.log("[DealSmart] Twilio SDK loaded");
      }
      function onTwilioError() {
        console.log("[DealSmart] Twilio SDK failed to load");
      }
    </script>
    <script src="/static/twilio.min.js"
            onload="onTwilioLoad()"
            onerror="onTwilioError()"></script>
    <style>
      body { font-family: ui-sans-serif, system-ui, -apple-system; background:#0b0f14; color:#eef2f7; }
      .card { max-width:560px; margin:40px auto; background:#141a22; border:1px solid #1f2633; border-radius:12px; padding:20px; }
      .row { display:flex; gap:12px; align-items:center; }
      .btn { padding:8px 14px; border-radius:8px; border:1px solid #2a3344; background:#141a22; color:#e6e8ee; cursor:pointer; }
      .btn.primary { background:#00e2a1; color:#03140c; border:none; }
      .status { color:#9aa3b2; font-size:0.95rem; margin-top:10px; }
      .log { background:#0f141b; border:1px solid #1f2633; border-radius:10px; padding:10px; margin-top:12px; font-size:0.85rem; max-height:140px; overflow:auto; }
    </style>
  </head>
  <body>
    <div class="card">
      <h2>DealSmart AI — WebRTC Call</h2>
      <p>Call the AI agent using your browser mic (no phone required).</p>
      <div class="row">
        <button class="btn primary" id="callBtn">Call Agent</button>
        <button class="btn" id="hangupBtn" disabled>Hang Up</button>
      </div>
      <div class="status" id="status">Ready</div>
      <div class="log" id="log"></div>
    </div>
    <script>
      let device;
      let activeCall;
      const statusEl = document.getElementById("status");
      const logEl = document.getElementById("log");
      const callBtn = document.getElementById("callBtn");
      const hangupBtn = document.getElementById("hangupBtn");
      let initializing = false;

      function log(msg) {
        statusEl.textContent = msg;
        const line = document.createElement("div");
        line.textContent = msg;
        logEl.prepend(line);
        console.log("[DealSmart] " + msg);
      }

      window.addEventListener("error", (e) => {
        log("Window error: " + (e.message || e.type));
      });

      async function initDevice() {
        if (initializing) return false;
        initializing = true;
        try {
          await navigator.mediaDevices.getUserMedia({ audio: true });
        } catch (err) {
          log("Mic permission denied");
          initializing = false;
          return false;
        }
        if (!window.TWILIO_SDK_READY || !window.Twilio || !window.Twilio.Device) {
          log("Twilio SDK not loaded (check network/CSP)");
          initializing = false;
          return false;
        }
        const resp = await fetch("/token");
        if (!resp.ok) {
          log("Token error: " + (await resp.text()));
          initializing = false;
          return false;
        }
        const data = await resp.json();
        log("Token OK (len=" + (data.token ? data.token.length : "na") + "), initializing device...");
        device = new Twilio.Device(data.token, { debug: true });
        device.on("registered", () => log("Registered (for inbound)"));
        device.on("registering", () => log("Registering device..."));
        device.on("error", (err) => log("Error: " + err.message));
        device.on("connect", () => log("Call connected"));
        device.on("disconnect", () => log("Call disconnected"));
        log("Device initialized");
        initializing = false;
        return true;
      }

      callBtn.onclick = async () => {
        log("Call button clicked");
        if (!device) {
          const ok = await initDevice();
          if (!ok || !device) {
            log("Device not ready");
            return;
          }
        }
        log("Calling... (device state: " + (device ? device.state : "no-device") + ")");
        try {
          if (!device.connect) {
            log("Device.connect is undefined");
            return;
          }
          activeCall = await device.connect({ params: { To: "agent" } });
          activeCall.on("error", (err) => log("Call error: " + err.message));
          activeCall.on("accept", () => log("Call accepted"));
        } catch (err) {
          log("Connect failed: " + (err && err.message ? err.message : String(err)));
          return;
        }
        hangupBtn.disabled = false;
        callBtn.disabled = true;
        activeCall.on("disconnect", () => {
          log("Call ended");
          callBtn.disabled = false;
          hangupBtn.disabled = true;
        });
      };

      hangupBtn.onclick = () => {
        if (activeCall) {
          activeCall.disconnect();
        }
      };
    </script>
  </body>
</html>"""
    return Response(content=html, media_type="text/html")


@app.post("/incoming")
async def incoming(request: Request):
    form = await request.form()
    call_sid = form.get("CallSid")
    from_number = form.get("From")

    config = load_dealer_config(DEFAULT_DEALER_ID)

    if not ULTRAVOX_API_KEY:
        return PlainTextResponse("Missing ULTRAVOX_API_KEY", status_code=500)

    payload: Dict = {
        "systemPrompt": (
            f"You are DealSmart AI for {config.dealer_name}. "
            "You are a polite dealership concierge. "
            "Qualify intent, timeline, budget, and trade-in status. "
            "Never invent inventory or pricing; ask to connect a human if unsure."
        ),
        "medium": {"twilio": {}},
        "recordingEnabled": True,
        "transcriptOptional": False,
        "firstSpeakerSettings": {
            "agent": {
                "text": "Thanks for calling! Are you calling about sales or service today?"
            }
        },
        "metadata": {
            "dealer_id": config.dealer_id,
            "call_sid": call_sid,
            "from": from_number,
        },
    }
    if PUBLIC_BASE_URL:
        payload["selectedTools"] = build_temporary_tools(PUBLIC_BASE_URL)
        base = f"{PUBLIC_BASE_URL}{API_BASE_PATH}"
        payload["callbacks"] = {
            "joined": {"url": f"{base}/ultravox/webhook"},
            "ended": {"url": f"{base}/ultravox/webhook"},
        }

    # Note: Adjust endpoint/payload per Ultravox inbound quickstart if needed.
    resp = requests.post(
        f"{ULTRAVOX_BASE_URL}/calls",
        headers={
            "Content-Type": "application/json",
            "X-API-Key": ULTRAVOX_API_KEY,
        },
        json=payload,
        timeout=15,
    )
    if resp.status_code >= 400:
        return PlainTextResponse(f"Ultravox error ({resp.status_code}): {resp.text}", status_code=500)
    data = resp.json()
    join_url = data.get("joinUrl")
    call_id = data.get("callId")

    if not join_url:
        return PlainTextResponse("Ultravox joinUrl missing", status_code=500)

    twiml = f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<Response>
  <Connect>
    <Stream url=\"{join_url}\" />
  </Connect>
</Response>"""

    log_event(
        {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "call_sid": call_sid,
            "from": from_number,
            "join_url": join_url,
            "call_id": call_id,
        }
    )

    return Response(content=twiml, media_type="text/xml")


@app.post("/outbound")
async def outbound(request: Request):
    body = await request.json()
    to_number = body.get("to")
    dealer_id = body.get("dealer_id", DEFAULT_DEALER_ID)

    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER):
        return PlainTextResponse("Missing Twilio credentials", status_code=500)
    if not ULTRAVOX_API_KEY:
        return PlainTextResponse("Missing ULTRAVOX_API_KEY", status_code=500)
    if not to_number:
        return PlainTextResponse("Missing 'to' phone number", status_code=400)

    config = load_dealer_config(dealer_id)

    payload: Dict = {
        "systemPrompt": (
            f"You are DealSmart AI for {config.dealer_name}. "
            "You are a polite dealership concierge. "
            "Qualify intent, timeline, budget, and trade-in status. "
            "Never invent inventory or pricing; ask to connect a human if unsure."
        ),
        "medium": {"twilio": {}},
        "recordingEnabled": True,
        "transcriptOptional": False,
        "firstSpeakerSettings": {"user": {}},
        "metadata": {
            "dealer_id": config.dealer_id,
            "to": to_number,
        },
    }
    if PUBLIC_BASE_URL:
        payload["selectedTools"] = build_temporary_tools(PUBLIC_BASE_URL)
        base = f"{PUBLIC_BASE_URL}{API_BASE_PATH}"
        payload["callbacks"] = {
            "joined": {"url": f"{base}/ultravox/webhook"},
            "ended": {"url": f"{base}/ultravox/webhook"},
        }

    resp = requests.post(
        f"{ULTRAVOX_BASE_URL}/calls",
        headers={
            "Content-Type": "application/json",
            "X-API-Key": ULTRAVOX_API_KEY,
        },
        json=payload,
        timeout=15,
    )
    if resp.status_code >= 400:
        return PlainTextResponse(f"Ultravox error ({resp.status_code}): {resp.text}", status_code=500)
    data = resp.json()
    join_url = data.get("joinUrl")
    call_id = data.get("callId")
    if not join_url:
        return PlainTextResponse("Ultravox joinUrl missing", status_code=500)

    twiml = f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<Response>
  <Connect>
    <Stream url=\"{join_url}\" />
  </Connect>
</Response>"""

    twilio_resp = requests.post(
        f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Calls.json",
        auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
        data={
            "To": to_number,
            "From": TWILIO_FROM_NUMBER,
            "Twiml": twiml,
        },
        timeout=15,
    )
    twilio_resp.raise_for_status()
    twilio_data = twilio_resp.json()

    log_event(
        {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "direction": "outbound",
            "to": to_number,
            "from": TWILIO_FROM_NUMBER,
            "join_url": join_url,
            "call_id": call_id,
            "twilio_call_sid": twilio_data.get("sid"),
        }
    )

    return {
        "ok": True,
        "twilio_call_sid": twilio_data.get("sid"),
        "join_url": join_url,
        "call_id": call_id,
    }


@app.get("/ultravox/calls/{call_id}/messages")
async def ultravox_call_messages(call_id: str):
    if not ULTRAVOX_API_KEY:
        return PlainTextResponse("Missing ULTRAVOX_API_KEY", status_code=500)
    resp = requests.get(
        f"{ULTRAVOX_BASE_URL}/calls/{call_id}/messages",
        headers={"X-API-Key": ULTRAVOX_API_KEY},
        timeout=15,
    )
    if resp.status_code >= 400:
        return PlainTextResponse(f"Ultravox error ({resp.status_code}): {resp.text}", status_code=500)
    return resp.json()


@app.get("/ultravox/calls/{call_id}")
async def ultravox_call_detail(call_id: str):
    if not ULTRAVOX_API_KEY:
        return PlainTextResponse("Missing ULTRAVOX_API_KEY", status_code=500)
    resp = requests.get(
        f"{ULTRAVOX_BASE_URL}/calls/{call_id}",
        headers={"X-API-Key": ULTRAVOX_API_KEY},
        timeout=15,
    )
    if resp.status_code >= 400:
        return PlainTextResponse(f"Ultravox error ({resp.status_code}): {resp.text}", status_code=500)
    return resp.json()


@app.post("/ultravox/webhook")
async def ultravox_webhook(request: Request):
    payload = await request.json()
    event = payload.get("event")
    call_id = payload.get("callId")
    log_event(
        {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "event": "ultravox_webhook",
            "payload": payload,
        }
    )
    if event == "call.ended" and call_id:
        try:
            messages_resp = requests.get(
                f"{ULTRAVOX_BASE_URL}/calls/{call_id}/messages",
                headers={"X-API-Key": ULTRAVOX_API_KEY},
                timeout=15,
            )
            if messages_resp.status_code < 400:
                log_event(
                    {
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "event": "ultravox_transcript",
                        "call_id": call_id,
                        "messages": messages_resp.json(),
                    }
                )
        except requests.RequestException:
            pass
    return {"ok": True}


def build_temporary_tools(base_url: str) -> list[dict]:
    return [
        {"toolName": "hangUp"},
        {
            "temporaryTool": {
                "modelToolName": "inventory_lookup",
                "description": "Lookup vehicle inventory and availability.",
                "dynamicParameters": [
                    {
                        "name": "year",
                        "location": "PARAMETER_LOCATION_BODY",
                        "schema": {"type": "integer"},
                        "required": False,
                    },
                    {
                        "name": "make",
                        "location": "PARAMETER_LOCATION_BODY",
                        "schema": {"type": "string"},
                        "required": False,
                    },
                    {
                        "name": "model",
                        "location": "PARAMETER_LOCATION_BODY",
                        "schema": {"type": "string"},
                        "required": False,
                    },
                    {
                        "name": "trim",
                        "location": "PARAMETER_LOCATION_BODY",
                        "schema": {"type": "string"},
                        "required": False,
                    },
                ],
                "http": {
                    "baseUrlPattern": f"{base_url}/tools/inventory_lookup",
                    "httpMethod": "POST",
                },
            }
        },
        {
            "temporaryTool": {
                "modelToolName": "create_lead",
                "description": "Create or update a lead in the CRM.",
                "dynamicParameters": [
                    {
                        "name": "intent",
                        "location": "PARAMETER_LOCATION_BODY",
                        "schema": {"type": "string"},
                        "required": True,
                    },
                    {"name": "timeline", "location": "PARAMETER_LOCATION_BODY", "schema": {"type": "string"}, "required": False},
                    {"name": "budget_max", "location": "PARAMETER_LOCATION_BODY", "schema": {"type": "integer"}, "required": False},
                    {"name": "trade_in", "location": "PARAMETER_LOCATION_BODY", "schema": {"type": "boolean"}, "required": False},
                    {"name": "trade_in_vehicle", "location": "PARAMETER_LOCATION_BODY", "schema": {"type": "string"}, "required": False},
                    {"name": "vehicle_interest", "location": "PARAMETER_LOCATION_BODY", "schema": {"type": "string"}, "required": False},
                    {"name": "contact_preference", "location": "PARAMETER_LOCATION_BODY", "schema": {"type": "string"}, "required": False},
                    {"name": "customer_name", "location": "PARAMETER_LOCATION_BODY", "schema": {"type": "string"}, "required": False},
                    {"name": "phone", "location": "PARAMETER_LOCATION_BODY", "schema": {"type": "string"}, "required": False},
                    {"name": "email", "location": "PARAMETER_LOCATION_BODY", "schema": {"type": "string"}, "required": False},
                    {"name": "notes", "location": "PARAMETER_LOCATION_BODY", "schema": {"type": "string"}, "required": False},
                ],
                "http": {
                    "baseUrlPattern": f"{base_url}/tools/create_lead",
                    "httpMethod": "POST",
                },
            }
        },
        {
            "temporaryTool": {
                "modelToolName": "route_lead",
                "description": "Route lead to the appropriate queue based on intent.",
                "dynamicParameters": [
                    {
                        "name": "intent",
                        "location": "PARAMETER_LOCATION_BODY",
                        "schema": {"type": "string"},
                        "required": True,
                    }
                ],
                "http": {
                    "baseUrlPattern": f"{base_url}/tools/route_lead",
                    "httpMethod": "POST",
                },
            }
        },
    ]


def log_event(event: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(
        (LOG_PATH.read_text() if LOG_PATH.exists() else "")
        + json.dumps(event)
        + "\n"
    )


@app.post("/tools/inventory_lookup")
async def tool_inventory_lookup(request: Request):
    body = await request.json()
    log_event(
        {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "event": "tool_inventory_lookup",
            "body": body,
        }
    )
    year = body.get("year")
    make = body.get("make")
    model = body.get("model")
    trim = body.get("trim")
    from core.inventory import search_inventory
    from core.schema import InventoryQuery
    results = search_inventory(InventoryQuery(year=year, make=make, model=model, trim=trim))
    return {"count": len(results), "results": [r.model_dump() for r in results]}


@app.post("/tools/create_lead")
async def tool_create_lead(request: Request):
    body = await request.json()
    log_event(
        {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "event": "tool_create_lead",
            "body": body,
        }
    )
    from core.crm import get_crm_adapter
    from core.schema import Lead
    from sms_agent.agent import _normalize_intent, _normalize_timeline, _lead_hotness
    config = load_dealer_config(DEFAULT_DEALER_ID)
    adapter = get_crm_adapter(config.crm.get("provider", "mock"))
    norm_intent = _normalize_intent(body.get("intent"))
    norm_timeline = _normalize_timeline(body.get("timeline"))
    lead = Lead(
        intent=norm_intent,
        timeline=norm_timeline,
        budget_max=body.get("budget_max"),
        trade_in=body.get("trade_in"),
        trade_in_vehicle=body.get("trade_in_vehicle"),
        vehicle_interest=body.get("vehicle_interest"),
        contact_preference=body.get("contact_preference"),
        customer_name=body.get("customer_name"),
        phone=body.get("phone"),
        email=body.get("email"),
        notes=body.get("notes"),
        lead_type=_lead_hotness(norm_timeline, body.get("budget_max")),
    )
    metadata = {
        "dealer_id": config.dealer_id,
        "dealer_name": config.dealer_name,
        "lead_source": config.crm.get("lead_source", "AI Concierge"),
    }
    try:
        return adapter.create_lead(lead, metadata).model_dump()
    except Exception as exc:
        log_event(
            {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "event": "tool_create_lead_error",
                "error": str(exc),
            }
        )
        return {"ok": False, "message": f"create_lead failed: {exc}"}


@app.post("/tools/route_lead")
async def tool_route_lead(request: Request):
    body = await request.json()
    log_event(
        {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "event": "tool_route_lead",
            "body": body,
        }
    )
    intent = body.get("intent", "sales")
    config = load_dealer_config(DEFAULT_DEALER_ID)
    routing = config.routing
    queue = routing.get("nurture_queue")
    if intent == "sales":
        queue = routing.get("sales_queue")
    elif intent == "service":
        queue = routing.get("service_queue")
    return {"queue": queue}
