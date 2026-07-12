"""Button entities for triggering Resolume clips.

Each non-empty clip slot becomes a button; pressing it connects the clip
(exactly like clicking it in Arena). The clip's thumbnail is exposed as
the entity picture via the thumbnail proxy view, and the connected state
is available as attributes for the bundled resolume-clip-card.
"""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import ClipState
from .const import DATA_THUMBNAIL_TOKENS, DOMAIN, MANUFACTURER
from .coordinator import ResolumeConfigEntry, ResolumeCoordinator
from .http import thumbnail_url

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ResolumeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up clip buttons, adding new clips as they appear."""
    coordinator = entry.runtime_data
    token: str = hass.data[DOMAIN][DATA_THUMBNAIL_TOKENS][entry.entry_id]
    known: set[str] = set()

    @callback
    def _sync_entities() -> None:
        new = [
            ResolumeClipButton(entry, coordinator, key, token)
            for key in coordinator.data.clips
            if key not in known
        ]
        if new:
            known.update(entity.clip_key for entity in new)
            async_add_entities(new)

    _sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_sync_entities))


class ResolumeClipButton(
    CoordinatorEntity[ResolumeCoordinator], ButtonEntity
):
    """A Resolume clip: press to connect (trigger) it."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:movie-play"

    def __init__(
        self,
        entry: ResolumeConfigEntry,
        coordinator: ResolumeCoordinator,
        key: str,
        token: str,
    ) -> None:
        """Initialize the clip button."""
        super().__init__(coordinator)
        self.clip_key = key
        self._entry_id = entry.entry_id
        self._token = token
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer=MANUFACTURER,
            model=coordinator.client.product_name or "Arena",
            name=f"Resolume ({entry.data[CONF_HOST]})",
            sw_version=coordinator.client.product_version,
        )

    @property
    def _clip(self) -> ClipState | None:
        """Return this entity's clip state."""
        return self.coordinator.data.clips.get(self.clip_key)

    @property
    def available(self) -> bool:
        """Available while the clip exists in the composition."""
        return super().available and self._clip is not None

    @property
    def name(self) -> str:
        """Follow the clip name from Resolume."""
        clip = self._clip
        return clip.name if clip else "Clip"

    @property
    def entity_picture(self) -> str | None:
        """Return the proxied thumbnail URL."""
        clip = self._clip
        if clip is None:
            return None
        return thumbnail_url(
            self._entry_id,
            self._token,
            clip.layer_index,
            clip.clip_index,
            clip.thumbnail_last_update,
        )

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose clip details for cards and automations."""
        clip = self._clip
        if clip is None:
            return {}
        return {
            "clip_name": clip.name,
            "layer_name": clip.layer_name,
            "layer_index": clip.layer_index,
            "clip_index": clip.clip_index,
            "connected": clip.connected,
            "playing": clip.playing,
        }

    async def async_press(self) -> None:
        """Connect (trigger) the clip."""
        await self.coordinator.async_connect_clip(self.clip_key)
