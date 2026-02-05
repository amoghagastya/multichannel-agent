from __future__ import annotations

import re
from typing import Dict, Tuple

from .schema import Lead, Intent


def _detect_intent(message: str) -> Intent:
    lower = message.lower()
    if any(word in lower for word in ["service", "oil", "appointment", "repair"]):
        return Intent.service
    if "trade" in lower or "trade-in" in lower:
        return Intent.trade_in
    return Intent.sales


def _extract_budget(message: str):
    match = re.search(r"\$?\s?(\d{2,3})(?:,\d{3})?", message.replace(",", ""))
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


def _extract_vehicle(message: str):
    for model in ["x5", "x3", "x7", "3 series", "5 series", "m3", "m5"]:
        if model in message.lower():
            return model.upper()
    return None


def update_lead_from_message(lead: Lead, message: str) -> Lead:
    if not lead.intent:
        lead.intent = _detect_intent(message)
    budget = _extract_budget(message)
    if budget and not lead.budget_max:
        lead.budget_max = budget * 1000 if budget < 1000 else budget
    vehicle = _extract_vehicle(message)
    if vehicle and not lead.vehicle_interest:
        lead.vehicle_interest = vehicle
    if "trade" in message.lower() and lead.trade_in is None:
        lead.trade_in = True
    if "no trade" in message.lower() and lead.trade_in is None:
        lead.trade_in = False
    return lead


def next_question(lead: Lead) -> str:
    if lead.intent == Intent.service:
        if not lead.timeline:
            return "What day and time works best for service?"
        return "Got it. Would you like a call or text confirmation?"

    if lead.timeline is None:
        return "What timeline are you considering?"
    if lead.trade_in is None:
        return "Do you have a trade-in?"
    if lead.budget_max is None:
        return "Do you have a budget range in mind?"
    return "Thanks! What’s the best number to reach you?"


def fallback_sms_turn(state: Dict, message: str) -> Tuple[str, Lead]:
    lead = Lead.model_validate(state.get("lead") or {"intent": _detect_intent(message)})
    lead = update_lead_from_message(lead, message)
    state["lead"] = lead.model_dump()
    reply = next_question(lead)
    return reply, lead
