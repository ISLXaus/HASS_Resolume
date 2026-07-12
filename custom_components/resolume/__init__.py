"""The Resolume Arena integration.

Exposes Resolume's composition and layer master faders as Home Assistant
number entities (sliders), kept in sync in real time over the Resolume
webserver's WebSocket push channel.
"""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ResolumeConnectionError
from .client import ResolumeClient
from .coordinator import ResolumeConfigEntry, ResolumeCoordinator

PLATFORMS = [Platform.NUMBER]


async def async_setup_entry(
    hass: HomeAssistant, entry: ResolumeConfigEntry
) -> bool:
    """Set up a Resolume instance from a config entry."""
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
