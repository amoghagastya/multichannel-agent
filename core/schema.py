from __future__ import annotations

from enum import Enum
from typing import Optional, Literal

from pydantic import BaseModel, Field


class Intent(str, Enum):
    sales = "sales"
    service = "service"
    trade_in = "trade_in"
    nurture = "nurture"


class Lead(BaseModel):
    intent: Intent
    timeline: Optional[Literal["asap", "1-3 months", "3-6 months", "later"]] = None
    budget_max: Optional[int] = None
    trade_in: Optional[bool] = None
    trade_in_vehicle: Optional[str] = None
    vehicle_interest: Optional[str] = None
    contact_preference: Optional[Literal["sms", "phone", "email"]] = None
    customer_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None
    lead_type: Optional[Literal["urgent", "medium", "cold"]] = None


class ToolResult(BaseModel):
    ok: bool = True
    message: str
    data: Optional[dict] = None


class InventoryQuery(BaseModel):
    year: Optional[int] = None
    make: Optional[str] = None
    model: Optional[str] = None
    trim: Optional[str] = None


class InventoryItem(BaseModel):
    vin: str
    year: int
    make: str
    model: str
    trim: str
    price: int
    status: str
    color: str


class DealershipConfig(BaseModel):
    dealer_id: str
    dealer_name: str
    brand: str
    logo_url: Optional[str] = None
    timezone: str
    tone: str
    qualifying_questions: dict
    routing: dict
    crm: dict
    compliance: dict
