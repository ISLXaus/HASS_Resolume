"""Switch entities for Resolume boolean parameters (bypass and solo)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import ToggleState
from .const import DOMAIN, MANUFACTURER
from .coordinator import ResolumeConfigEntry, ResolumeCoordinator

_LOGGER = logging.getLogger(__name__)

ICONS = {
    "bypassed": "mdi:eye-off",
    "solo": "mdi:alpha-s-circle",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ResolumeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up bypass/solo switches, adding new ones as layers appear."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _sync_entities() -> None:
        new = [
            ResolumeToggleSwitch(entry, coordinator, key)
            for key in coordinator.data.toggles
            if key not in known
        ]
        if new:
            known.update(entity.toggle_key for entity in new)
            async_add_entities(new)

    _sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_sync_entities))


class ResolumeToggleSwitch(
    CoordinatorEntity[ResolumeCoordinator], SwitchEntity
):
    """A Resolume boolean parameter (bypassed/solo) as a switch."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ResolumeConfigEntry,
        coordinator: ResolumeCoordinator,
        key: str,
    ) -> None:
        """Initialize the toggle switch."""
        super().__init__(coordinator)
        self.toggle_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer=MANUFACTURER,
            model=coordinator.client.product_name or "Arena",
            name=f"Resolume ({entry.data[CONF_HOST]})",
            sw_version=coordinator.client.product_version,
        )

    @property
    def _toggle(self) -> ToggleState | None:
        """Return this entity's toggle state."""
        return self.coordinator.data.toggles.get(self.toggle_key)

    @property
    def available(self) -> bool:
        """Available while the parameter exists in the composition."""
        return super().available and self._toggle is not None

    @property
    def name(self) -> str:
        """Follow the toggle's display name from Resolume."""
        toggle = self._toggle
        return toggle.name if toggle else "Toggle"

    @property
    def icon(self) -> str:
        """Return an icon matching the toggle type."""
        toggle = self._toggle
        return ICONS.get(toggle.toggle_type if toggle else "", "mdi:toggle-switch")

    @property
    def is_on(self) -> bool | None:
        """Return the current state."""
        toggle = self._toggle
        return toggle.value if toggle else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose parameter details."""
        toggle = self._toggle
        if toggle is None:
            return {}
        return {
            "toggle_type": toggle.toggle_type,
            "layer_index": toggle.layer_index,
            "parameter_path": toggle.parameter_path,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the parameter."""
        await self.coordinator.async_set_toggle(self.toggle_key, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the parameter."""
        await self.coordinator.async_set_toggle(self.toggle_key, False)
