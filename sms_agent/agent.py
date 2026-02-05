from __future__ import annotations

import os
from typing import Dict, List, Tuple

from agents import Agent, Runner, function_tool

from core.config import load_dealer_config
from core.crm import get_crm_adapter
from core.inventory import search_inventory
from core.schema import DealershipConfig, InventoryQuery, Lead, ToolResult
from core.orchestrator import fallback_sms_turn

_AGENTS: Dict[str, Agent] = {}
_AGENT_CONFIG_HASH: Dict[str, str] = {}


def _normalize_intent(raw: str) -> str:
    text = (raw or "").lower()
    if "service" in text:
        return "service"
    if "trade" in text:
        return "trade_in"
    return "sales"


def _normalize_timeline(raw: str | None) -> str | None:
    if not raw:
        return None
    text = raw.lower()
    if any(x in text for x in ["asap", "now", "today", "this week", "next week"]):
        return "asap"
    if any(x in text for x in ["1-3", "few months", "next month"]):
        return "1-3 months"
    if any(x in text for x in ["3-6", "quarter"]):
        return "3-6 months"
    if any(x in text for x in ["later", "not sure", "someday"]):
        return "later"
    return None


def _lead_hotness(timeline: str | None, budget_max: int | None) -> str:
    if timeline == "asap":
        return "urgent"
    if timeline in {"1-3 months", "3-6 months"}:
        return "medium"
    if budget_max and budget_max >= 70000:
        return "medium"
    return "cold"
_SESSIONS: Dict[str, dict] = {}


def _build_agent(config: DealershipConfig) -> Agent:
    crm_adapter = get_crm_adapter(config.crm.get("provider", "mock"))

    @function_tool
    def inventory_lookup(year: int | None = None,
                         make: str | None = None,
                         model: str | None = None,
                         trim: str | None = None) -> Dict:
        """Lookup inventory. Only use this tool to share availability or pricing."""
        query = InventoryQuery(year=year, make=make, model=model, trim=trim)
        results = search_inventory(query)
        return {
            "count": len(results),
            "results": [item.model_dump() for item in results],
        }

    @function_tool
    def create_lead(intent: str,
                    timeline: str | None = None,
                    budget_max: int | None = None,
                    trade_in: bool | None = None,
                    trade_in_vehicle: str | None = None,
                    vehicle_interest: str | None = None,
                    contact_preference: str | None = None,
                    customer_name: str | None = None,
                    phone: str | None = None,
                    email: str | None = None,
                    notes: str | None = None) -> Dict:
        """Create or update a lead in the CRM."""
        norm_intent = _normalize_intent(intent)
        norm_timeline = _normalize_timeline(timeline)
        lead = Lead(
            intent=norm_intent,
            timeline=norm_timeline,
            budget_max=budget_max,
            trade_in=trade_in,
            trade_in_vehicle=trade_in_vehicle,
            vehicle_interest=vehicle_interest,
            contact_preference=contact_preference,
            customer_name=customer_name,
            phone=phone,
            email=email,
            notes=notes,
            lead_type=_lead_hotness(norm_timeline, budget_max),
        )
        metadata = {
            "dealer_id": config.dealer_id,
            "dealer_name": config.dealer_name,
            "lead_source": config.crm.get("lead_source", "AI Concierge"),
        }
        result = crm_adapter.create_lead(lead, metadata)
        return result.model_dump()

    @function_tool
    def route_lead(intent: str) -> Dict:
        """Return routing queue for intent."""
        routing = config.routing
        queue = routing.get("nurture_queue")
        if intent == "sales":
            queue = routing.get("sales_queue")
        elif intent == "service":
            queue = routing.get("service_queue")
        return {"queue": queue}

    instructions = f"""
You are DealSmart AI, a dealership concierge for {config.dealer_name} ({config.brand}).
Tone: {config.tone}.

Goal: Qualify the customer and capture intent, timeline, budget, trade-in status, and vehicle interest.
Rules:
- Ask 1 question at a time.
- Keep qualification to the minimum needed: aim to capture intent + 2-3 key fields, then offer a handoff.
- Do not invent inventory or pricing. Only share availability/pricing if you used inventory_lookup.
- If the customer asks for specifics you cannot verify, offer to connect a human specialist.
- When you have enough details to create a lead, call create_lead.
- Use route_lead once intent is clear and mention that you will connect them to the right team.
Constraints:
- For create_lead.intent use one of: sales, service, trade_in, nurture.
- For create_lead.timeline use one of: asap, 1-3 months, 3-6 months, later.
""".strip()

    return Agent(
        name="SMS Qualifier",
        instructions=instructions,
        tools=[inventory_lookup, create_lead, route_lead],
    )


def _config_hash(config: DealershipConfig) -> str:
    return str(hash(config.model_dump_json()))


def get_agent(dealer_id: str) -> Agent:
    config = load_dealer_config(dealer_id)
    cfg_hash = _config_hash(config)
    if dealer_id not in _AGENTS or _AGENT_CONFIG_HASH.get(dealer_id) != cfg_hash:
        _AGENTS[dealer_id] = _build_agent(config)
        _AGENT_CONFIG_HASH[dealer_id] = cfg_hash
    return _AGENTS[dealer_id]


def clear_agent_cache(dealer_id: str) -> None:
    _AGENTS.pop(dealer_id, None)
    _AGENT_CONFIG_HASH.pop(dealer_id, None)


def get_session(session_id: str) -> dict:
    if session_id not in _SESSIONS:
        _SESSIONS[session_id] = {}
    return _SESSIONS[session_id]


def run_sms_turn(
    message: str,
    dealer_id: str,
    session_id: str,
    state: Dict | None = None,
    history: List[Dict] | None = None,
) -> Tuple[str, Dict]:
    if not os.getenv("OPENAI_API_KEY"):
        state = state or {}
        reply, lead = fallback_sms_turn(state, message)
        return reply, {"lead": lead.model_dump(), "note": "Fallback mode (no OPENAI_API_KEY set).", "state": state}

    agent = get_agent(dealer_id)
    # The current Agents SDK Session is a Protocol in some versions.
    # Use stateless runs for compatibility.
    history = history or []
    history_text = "\n".join(
        [f"{m['role'].upper()}: {m['content']}" for m in history[-12:]]
    )
    full_input = f"{history_text}\nUSER: {message}".strip()
    result = Runner.run_sync(agent, input=full_input)
    output_text = result.final_output or ""

    new_items = getattr(result, "new_items", []) or []
    tool_calls = []
    for item in new_items:
        name = item.__class__.__name__
        if name in ("ToolCallItem", "ToolCallOutputItem"):
            tool_calls.append(
                {
                    "type": name,
                    "raw_item": getattr(item, "raw_item", None),
                    "output": getattr(item, "output", None),
                }
            )

    trace = {
        "output": output_text,
        "new_items": [item.__class__.__name__ for item in new_items],
        "tool_calls": tool_calls,
    }
    return output_text, trace
