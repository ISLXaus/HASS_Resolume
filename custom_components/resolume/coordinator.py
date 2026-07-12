"""Coordinator for Resolume Arena composition state.

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
    CompositionModel,
    ResolumeConnectionError,
    empty_model,
    extract_parameter_update,
    parse_bool_value,
    parse_composition,
)
from .client import ResolumeClient
from .const import DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)

type ResolumeConfigEntry = ConfigEntry[ResolumeCoordinator]


class ResolumeCoordinator(DataUpdateCoordinator[CompositionModel]):
    """Maintains fader and clip state for one Resolume instance."""

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
        self._model = empty_model()
        self._fader_paths: dict[str, str] = {}  # parameter path -> fader key
        self._clip_paths: dict[str, str] = {}  # connected path -> clip key
        self._toggle_paths: dict[str, str] = {}  # path -> toggle key

        client.on_message = self._on_ws_message
        client.on_ws_connected = self._async_on_ws_connected
        client.on_ws_disconnected = self._async_on_ws_disconnected

    async def async_setup(self) -> None:
        """Fetch initial state and start the push channel.

        Raises ResolumeConnectionError when Resolume is unreachable.
        """
        self._apply_composition(await self.client.async_get_composition())
        self.data = self._snapshot()
        await self.client.async_start_ws()

    async def async_shutdown(self) -> None:
        """Stop the client and the coordinator."""
        await self.client.async_stop()
        await super().async_shutdown()

    async def _async_update_data(self) -> CompositionModel:
        """Periodic REST resync (WebSocket handles real-time updates)."""
        try:
            self._apply_composition(await self.client.async_get_composition())
        except ResolumeConnectionError as err:
            raise UpdateFailed(str(err)) from err
        return self._snapshot()

    def _snapshot(self) -> CompositionModel:
        """Return a fresh copy of the model for listeners."""
        return CompositionModel(
            faders=dict(self._model.faders),
            clips=dict(self._model.clips),
            toggles=dict(self._model.toggles),
            triggers=dict(self._model.triggers),
        )

    def _apply_composition(self, data: dict[str, Any]) -> None:
        """Replace the model from a full composition JSON."""
        self._model = parse_composition(data)
        self._fader_paths = {
            fader.parameter_path: key
            for key, fader in self._model.faders.items()
        }
        self._clip_paths = {
            clip.connected_path: key
            for key, clip in self._model.clips.items()
        }
        self._toggle_paths = {
            toggle.parameter_path: key
            for key, toggle in self._model.toggles.items()
        }

    # WebSocket push handling

    async def _async_on_ws_connected(self) -> None:
        """Resync and resubscribe whenever the push channel (re)connects."""
        try:
            self._apply_composition(await self.client.async_get_composition())
        except ResolumeConnectionError as err:
            _LOGGER.debug("Resync after WS connect failed: %s", err)
        for path in (
            *self._fader_paths,
            *self._clip_paths,
            *self._toggle_paths,
        ):
            await self.client.async_subscribe(path)
        self.async_set_updated_data(self._snapshot())

    async def _async_on_ws_disconnected(self) -> None:
        """Notify listeners so entities can reflect degraded state."""
        self.async_update_listeners()

    @callback
    def _on_ws_message(self, message: dict[str, Any]) -> None:
        """Handle a pushed WebSocket message."""
        # A full composition push (sent on connect and on structural
        # changes) refreshes everything, including names and thumbnails.
        if "layers" in message and "master" in message:
            self._apply_composition(message)
            self.async_set_updated_data(self._snapshot())
            return

        update = extract_parameter_update(message)
        if update is None:
            return
        path, value = update

        if (fader_key := self._fader_paths.get(path)) is not None:
            fader = self._model.faders.get(fader_key)
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                return
            if fader is None or fader.value == numeric:
                return
            self._model.faders[fader_key] = fader.with_value(numeric)
            self.async_set_updated_data(self._snapshot())
        elif (clip_key := self._clip_paths.get(path)) is not None:
            clip = self._model.clips.get(clip_key)
            connected = str(value)
            if clip is None or clip.connected == connected:
                return
            self._model.clips[clip_key] = clip.with_connected(connected)
            self.async_set_updated_data(self._snapshot())
        elif (toggle_key := self._toggle_paths.get(path)) is not None:
            toggle = self._model.toggles.get(toggle_key)
            boolean = parse_bool_value(value)
            if toggle is None or toggle.value == boolean:
                return
            self._model.toggles[toggle_key] = toggle.with_value(boolean)
            self.async_set_updated_data(self._snapshot())

    # Commands

    async def async_set_fader_percentage(
        self, key: str, percentage: float
    ) -> None:
        """Set a fader to a 0-100 percentage value."""
        fader = self._model.faders.get(key)
        if fader is None or fader.parameter_id is None:
            raise ResolumeConnectionError(f"Unknown fader {key}")
        value = fader.value_from_percentage(percentage)
        await self.client.async_set_parameter(fader.parameter_id, value)
        # Optimistic local update; Resolume will confirm via push/resync.
        self._model.faders[key] = fader.with_value(value)
        self.async_set_updated_data(self._snapshot())

    async def async_connect_clip(self, key: str) -> None:
        """Trigger (connect) a clip by its stable key."""
        clip = self._model.clips.get(key)
        if clip is None:
            raise ResolumeConnectionError(f"Unknown clip {key}")
        await self.client.async_connect_clip(
            clip.layer_index, clip.clip_index
        )

    async def async_set_toggle(self, key: str, value: bool) -> None:
        """Set a boolean parameter (bypass/solo) by its stable key."""
        toggle = self._model.toggles.get(key)
        if toggle is None or toggle.parameter_id is None:
            raise ResolumeConnectionError(f"Unknown toggle {key}")
        await self.client.async_set_parameter(toggle.parameter_id, value)
        # Optimistic local update; Resolume will confirm via push/resync.
        self._model.toggles[key] = toggle.with_value(value)
        self.async_set_updated_data(self._snapshot())

    async def async_run_trigger(self, key: str) -> None:
        """Run a one-shot trigger (column, disconnect all, tap tempo)."""
        trigger = self._model.triggers.get(key)
        if trigger is None:
            raise ResolumeConnectionError(f"Unknown trigger {key}")
        if trigger.trigger_type == "column" and trigger.column_index:
            await self.client.async_connect_column(trigger.column_index)
        elif trigger.trigger_type == "disconnect_all":
            await self.client.async_disconnect_all()
        elif (
            trigger.trigger_type == "parameter"
            and trigger.parameter_id is not None
        ):
            await self.client.async_trigger_parameter(trigger.parameter_id)
        else:
            raise ResolumeConnectionError(f"Trigger {key} is not actionable")
