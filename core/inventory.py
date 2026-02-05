from __future__ import annotations

import json
from pathlib import Path
from typing import List

from .schema import InventoryItem, InventoryQuery

INVENTORY_PATH = Path(__file__).resolve().parent.parent / "data" / "mock_inventory.json"


def load_inventory() -> List[InventoryItem]:
    if not INVENTORY_PATH.exists():
        return []
    data = json.loads(INVENTORY_PATH.read_text())
    return [InventoryItem.model_validate(item) for item in data]


def search_inventory(query: InventoryQuery) -> List[InventoryItem]:
    items = load_inventory()
    def matches(item: InventoryItem) -> bool:
        if query.year and item.year != query.year:
            return False
        if query.make and item.make.lower() != query.make.lower():
            return False
        if query.model and item.model.lower() != query.model.lower():
            return False
        if query.trim and item.trim.lower() != query.trim.lower():
            return False
        return True

    return [item for item in items if matches(item)]
