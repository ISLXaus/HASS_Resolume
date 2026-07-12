"""Number entities exposing Resolume master faders as sliders."""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import CONF_HOST, PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import KIND_COMPOSITION, FaderState
from .const import DOMAIN, MANUFACTURER
from .coordinator import ResolumeConfigEntry, ResolumeCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ResolumeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up fader sliders, adding new layers as they appear."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _sync_entities() -> None:
        new = [
            ResolumeFaderNumber(entry, coordinator, key)
            for key in coordinator.data
            if key not in known
        ]
        if new:
            known.update(entity.fader_key for entity in new)
            async_add_entities(new)

    _sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_sync_entities))


class ResolumeFaderNumber(
    CoordinatorEntity[ResolumeCoordinator], NumberEntity
):
    """A Resolume master fader as a 0-100% slider."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 0.0
    _attr_native_max_value = 100.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:tune-vertical"

    def __init__(
        self,
        entry: ResolumeConfigEntry,
        coordinator: ResolumeCoordinator,
        key: str,
    ) -> None:
        """Initialize the fader entity."""
        super().__init__(coordinator)
        self.fader_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}_master"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer=MANUFACTURER,
            model=coordinator.client.product_name or "Arena",
            name=f"Resolume ({entry.data[CONF_HOST]})",
            sw_version=coordinator.client.product_version,
            configuration_url=coordinator.client.base_url.removesuffix(
                "/api/v1"
            ),
        )

    @property
    def _fader(self) -> FaderState | None:
        """Return this entity's fader state."""
        return self.coordinator.data.get(self.fader_key)

    @property
    def available(self) -> bool:
        """Available while the fader exists in the composition."""
        return super().available and self._fader is not None

    @property
    def name(self) -> str:
        """Follow the layer name from Resolume."""
        fader = self._fader
        if fader is None:
            return "Master"
        if fader.kind == KIND_COMPOSITION:
            return "Composition master"
        return f"{fader.name} master"

    @property
    def native_value(self) -> float | None:
        """Return the fader position as a percentage."""
        fader = self._fader
        return round(fader.percentage, 1) if fader else None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose the raw parameter details."""
        fader = self._fader
        if fader is None:
            return {}
        return {
            "raw_value": fader.value,
            "layer_index": fader.layer_index,
            "layer_id": fader.layer_id,
            "parameter_path": fader.parameter_path,
        }

    async def async_set_native_value(self, value: float) -> None:
        """Move the fader in Resolume."""
        await self.coordinator.async_set_fader_percentage(
            self.fader_key, value
        )
