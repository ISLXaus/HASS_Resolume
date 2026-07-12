"""Coordinator for Resolume Arena fader state.

Owns the client. Baseline state comes from REST composition fetches (at
setup and every UPDATE_INTERVAL as a safety net); real-time changes arrive
over the WebSocket push channel. Entities never talk to Resolume directly.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import (
    FaderState,
    ResolumeConnectionError,
    extract_parameter_update,
    parse_composition,
)
from .client import ResolumeClient
from .const import DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)

type ResolumeConfigEntry = ConfigEntry[ResolumeCoordinator]


class ResolumeCoordinator(DataUpdateCoordinator[dict[str, FaderState]]):
    """Maintains composition and layer master fader state."""

    config_entry: ResolumeConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ResolumeConfigEntry,
        client: ResolumeClient,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.data[CONF_HOST]}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self.client = client
        self._faders: dict[str, FaderState] = {}
        self._paths: dict[str, str] = {}  # parameter path -> fader key

        client.on_message = self._on_ws_message
        client.on_ws_connected = self._async_on_ws_connected
        client.on_ws_disconnected = self._async_on_ws_disconnected

    async def async_setup(self) -> None:
        """Fetch initial state and start the push channel.

        Raises ResolumeConnectionError when Resolume is unreachable.
        """
        self._apply_composition(await self.client.async_get_composition())
        self.data = dict(self._faders)
        await self.client.async_start_ws()

    async def async_shutdown(self) -> None:
        """Stop the client and the coordinator."""
        await self.client.async_stop()
        await super().async_shutdown()

    async def _async_update_data(self) -> dict[str, FaderState]:
        """Periodic REST resync (WebSocket handles real-time updates)."""
        try:
            self._apply_composition(await self.client.async_get_composition())
        except ResolumeConnectionError as err:
            raise UpdateFailed(str(err)) from err
        return dict(self._faders)

    def _apply_composition(self, data: dict[str, Any]) -> None:
        """Replace the fader model from a full composition JSON."""
        self._faders = parse_composition(data)
        self._paths = {
            fader.parameter_path: key for key, fader in self._faders.items()
        }

    # WebSocket push handling

    async def _async_on_ws_connected(self) -> None:
        """Resync and resubscribe whenever the push channel (re)connects."""
        try:
            self._apply_composition(await self.client.async_get_composition())
        except ResolumeConnectionError as err:
            _LOGGER.debug("Resync after WS connect failed: %s", err)
        for fader in self._faders.values():
            await self.client.async_subscribe(fader.parameter_path)
        self.async_set_updated_data(dict(self._faders))

    async def _async_on_ws_disconnected(self) -> None:
        """Notify listeners so entities can reflect degraded state."""
        self.async_update_listeners()

    @callback
    def _on_ws_message(self, message: dict[str, Any]) -> None:
        """Handle a pushed WebSocket message."""
        # A full composition push (sent on connect and on structural
        # changes) refreshes everything, including layer names/order.
        if "layers" in message and "master" in message:
            self._apply_composition(message)
            self.async_set_updated_data(dict(self._faders))
            return

        update = extract_parameter_update(message)
        if update is None:
            return
        path, value = update
        key = self._paths.get(path)
        if key is None or key not in self._faders:
            return
        fader = self._faders[key]
        if fader.value == value:
            return
        self._faders[key] = fader.with_value(value)
        self.async_set_updated_data(dict(self._faders))

    # Commands

    async def async_set_fader_percentage(
        self, key: str, percentage: float
    ) -> None:
        """Set a fader to a 0-100 percentage value."""
        fader = self._faders.get(key)
        if fader is None or fader.parameter_id is None:
            raise ResolumeConnectionError(f"Unknown fader {key}")
        value = fader.value_from_percentage(percentage)
        await self.client.async_set_parameter(fader.parameter_id, value)
        # Optimistic local update; Resolume will confirm via push/resync.
        self._faders[key] = fader.with_value(value)
        self.async_set_updated_data(dict(self._faders))
