from __future__ import annotations

import json
from pathlib import Path
from typing import List

from .schema import DealershipConfig

CONFIG_DIR = Path(__file__).resolve().parent.parent / "data" / "dealer_configs"


def list_dealers() -> List[str]:
    if not CONFIG_DIR.exists():
        return []
    return sorted(p.stem for p in CONFIG_DIR.glob("*.json"))


def load_dealer_config(dealer_id: str) -> DealershipConfig:
    path = CONFIG_DIR / f"{dealer_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Dealer config not found: {path}")
    data = json.loads(path.read_text())
    return DealershipConfig.model_validate(data)
