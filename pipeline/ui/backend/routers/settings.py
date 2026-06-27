"""Settings router — read and update config.json."""

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Dict

router = APIRouter(prefix="/api/settings", tags=["settings"])

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent.parent / "config.json"


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise HTTPException(404, "config.json not found")
    return json.loads(CONFIG_PATH.read_text())


def _mask_key(val: str) -> str:
    """Mask API keys for display. Keep ${VAR} refs visible."""
    if val.startswith("${"):
        return val
    if len(val) > 8:
        return val[:4] + "•" * (len(val) - 8) + val[-4:]
    return "••••••••"


@router.get("")
def get_settings():
    """Return current configuration (API keys masked)."""
    cfg = _load_config()
    # Mask sensitive values
    for provider in ("openai",):
        if provider in cfg and "api_key" in cfg[provider]:
            cfg[provider]["api_key"] = _mask_key(cfg[provider]["api_key"])
    return cfg


class UpdateSettingsRequest(BaseModel):
    settings: Dict[str, Any]


@router.put("")
def update_settings(req: UpdateSettingsRequest):
    """Update configuration values (merges with existing)."""
    cfg = _load_config()
    _deep_merge(cfg, req.settings)

    # Don't allow overwriting api_key with masked value
    for provider in ("openai",):
        if provider in req.settings and "api_key" in req.settings.get(provider, {}):
            key_val = req.settings[provider]["api_key"]
            if "••" in key_val:
                # Restore the original
                orig = json.loads(CONFIG_PATH.read_text())
                cfg[provider]["api_key"] = orig.get(provider, {}).get("api_key", "")

    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    return {"status": "ok"}


def _deep_merge(base: dict, overlay: dict):
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
