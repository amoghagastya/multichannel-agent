from __future__ import annotations

from abc import ABC, abstractmethod
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from .schema import Lead, ToolResult

CRM_LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "mock_crm.jsonl"

class CRMAdapter(ABC):
    @abstractmethod
    def create_lead(self, lead: Lead, metadata: Dict) -> ToolResult:
        raise NotImplementedError


class MockCRMAdapter(CRMAdapter):
    def create_lead(self, lead: Lead, metadata: Dict) -> ToolResult:
        payload = {
            "lead": lead.model_dump(),
            "metadata": metadata,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        # De-dupe: if last lead is identical, skip write
        if CRM_LOG_PATH.exists():
            lines = CRM_LOG_PATH.read_text().strip().splitlines()
            if lines and lines[-1].strip():
                last = json.loads(lines[-1])
                if last.get("lead") == payload["lead"] and last.get("metadata") == payload["metadata"]:
                    return ToolResult(ok=True, message="Duplicate lead ignored", data=payload)

        CRM_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CRM_LOG_PATH.write_text(
            (CRM_LOG_PATH.read_text() if CRM_LOG_PATH.exists() else "")
            + json.dumps(payload)
            + "\n"
        )
        return ToolResult(ok=True, message="Lead created in Mock CRM", data=payload)


def read_mock_leads(limit: int = 20) -> List[Dict]:
    if not CRM_LOG_PATH.exists():
        return []
    lines = CRM_LOG_PATH.read_text().strip().splitlines()
    if not lines or not lines[0].strip():
        return []
    return [json.loads(line) for line in lines[-limit:]]


def clear_mock_leads() -> None:
    if CRM_LOG_PATH.exists():
        CRM_LOG_PATH.write_text("")


def get_crm_adapter(provider: str) -> CRMAdapter:
    if provider == "mock":
        return MockCRMAdapter()
    # Placeholder: add adapters for GHL, Salesforce, DealerSocket, etc.
    raise ValueError(f"Unsupported CRM provider: {provider}")
