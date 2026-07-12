"""Diagnostics support for the Resolume Arena integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .coordinator import ResolumeConfigEntry

TO_REDACT = {CONF_HOST, "unique_id", "title"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ResolumeConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    client = coordinator.client
    return {
        "entry": async_redact_data(
            {
                "title": entry.title,
                "unique_id": entry.unique_id,
                "data": dict(entry.data),
            },
            TO_REDACT,
        ),
        "connection": {
            "product_name": client.product_name,
            "product_version": client.product_version,
            "websocket_connected": client.ws_connected,
            "last_update_success": coordinator.last_update_success,
        },
        "faders": [asdict(fader) for fader in (coordinator.data or {}).values()],
    }
