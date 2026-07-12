"""The Resolume Arena integration.

Exposes Resolume's master faders as slider entities and clips as button
entities with live thumbnails, kept in sync in real time over the Resolume
webserver's WebSocket push channel. Ships the resolume-clip-card Lovelace
card for a clip-grid dashboard.
"""

from __future__ import annotations

import logging
import secrets
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ResolumeConnectionError
from .client import ResolumeClient
from .const import (
    CARD_FILENAME,
    CARD_URL_BASE,
    DATA_FRONTEND,
    DATA_THUMBNAIL_TOKENS,
    DATA_VIEW,
    DOMAIN,
)
from .coordinator import ResolumeConfigEntry, ResolumeCoordinator
from .http import ResolumeThumbnailView

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BUTTON, Platform.NUMBER]

INTEGRATION_VERSION = "1.1.0"


async def async_setup_entry(
    hass: HomeAssistant, entry: ResolumeConfigEntry
) -> bool:
    """Set up a Resolume instance from a config entry."""
    data = hass.data.setdefault(DOMAIN, {})
    tokens: dict[str, str] = data.setdefault(DATA_THUMBNAIL_TOKENS, {})
    tokens.setdefault(entry.entry_id, secrets.token_urlsafe(16))

    if not data.get(DATA_VIEW):
        data[DATA_VIEW] = True
        hass.http.register_view(ResolumeThumbnailView(hass))
    await _async_register_frontend(hass)

    client = ResolumeClient(
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        async_get_clientsession(hass),
    )
    coordinator = ResolumeCoordinator(hass, entry, client)
    try:
        await client.async_validate()
        await coordinator.async_setup()
    except ResolumeConnectionError as err:
        await client.async_stop()
        raise ConfigEntryNotReady(str(err)) from err

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ResolumeConfigEntry
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    )
    if unload_ok:
        await entry.runtime_data.async_shutdown()
    return unload_ok


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Serve the bundled Lovelace card and register it as a resource."""
    if hass.data[DOMAIN].get(DATA_FRONTEND):
        return
    hass.data[DOMAIN][DATA_FRONTEND] = True

    card_dir = Path(__file__).parent / "www"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL_BASE, str(card_dir), cache_headers=False)]
    )
    card_url = f"{CARD_URL_BASE}/{CARD_FILENAME}?v={INTEGRATION_VERSION}"

    lovelace = hass.data.get("lovelace")
    resources = getattr(lovelace, "resources", None)
    if resources is None or getattr(lovelace, "mode", "storage") != "storage":
        _LOGGER.info(
            "Lovelace is not in storage mode; add %s as a Lovelace "
            "resource manually to use resolume-clip-card",
            card_url,
        )
        return
    try:
        if not resources.loaded:
            await resources.async_load()
            resources.loaded = True
        for item in resources.async_items():
            url = str(item.get("url", ""))
            if url.startswith(f"{CARD_URL_BASE}/{CARD_FILENAME}"):
                if url != card_url:  # bump cache-busting version
                    await resources.async_update_item(
                        item["id"], {"url": card_url}
                    )
                return
        await resources.async_create_item(
            {"res_type": "module", "url": card_url}
        )
        _LOGGER.info("Registered Lovelace resource %s", card_url)
    except Exception:  # noqa: BLE001 - never break setup over the card
        _LOGGER.warning(
            "Could not register the resolume-clip-card Lovelace resource "
            "automatically; add %s manually",
            card_url,
            exc_info=True,
        )
