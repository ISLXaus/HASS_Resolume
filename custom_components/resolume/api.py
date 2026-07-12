"""Data model and composition parsing for the Resolume Arena REST API.

This module has no Home Assistant dependencies so it can be unit tested in
isolation. It turns Resolume's composition JSON (see
https://resolume.com/docs/restapi/) into a flat map of fader states.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


class ResolumeError(Exception):
    """Base error for Resolume communication."""


class ResolumeConnectionError(ResolumeError):
    """Raised when the Resolume webserver cannot be reached."""


KIND_COMPOSITION = "composition"
KIND_LAYER = "layer"

COMPOSITION_MASTER_PATH = "/composition/master"


def layer_master_path(index: int) -> str:
    """Return the parameter path for a layer's master fader (1-based)."""
    return f"/composition/layers/{index}/master"


@dataclass(slots=True, frozen=True)
class FaderState:
    """State of one master fader (composition or layer)."""

    key: str  # stable key: "composition" or "layer:<layer-id>"
    kind: str
    name: str  # display name, e.g. "Layer 1"
    parameter_id: int | None  # Resolume's unique parameter id
    parameter_path: str  # e.g. /composition/layers/1/master
    layer_id: int | None  # Resolume's stable layer id
    layer_index: int | None  # current 1-based position
    value: float
    minimum: float
    maximum: float

    @property
    def percentage(self) -> float:
        """Return the value scaled to 0-100."""
        span = self.maximum - self.minimum
        if span <= 0:
            return 0.0
        return (self.value - self.minimum) / span * 100.0

    def value_from_percentage(self, percentage: float) -> float:
        """Return the raw parameter value for a 0-100 percentage."""
        percentage = min(max(percentage, 0.0), 100.0)
        return self.minimum + (self.maximum - self.minimum) * percentage / 100.0

    def with_value(self, value: float) -> FaderState:
        """Return a copy with an updated raw value."""
        return replace(self, value=value)


def _param_value(param: Any, default: str = "") -> str:
    """Extract the value of a string parameter object."""
    if isinstance(param, dict):
        value = param.get("value")
        if value is not None:
            return str(value)
    return default


def _parse_range(param: Any) -> tuple[int | None, float, float, float] | None:
    """Extract (id, value, min, max) from a RangeParameter object."""
    if not isinstance(param, dict):
        return None
    try:
        value = float(param["value"])
    except (KeyError, TypeError, ValueError):
        return None
    param_id = param.get("id")
    minimum = float(param.get("min", 0.0))
    maximum = float(param.get("max", 1.0))
    if maximum <= minimum:
        minimum, maximum = 0.0, 1.0
    return (
        int(param_id) if param_id is not None else None,
        value,
        minimum,
        maximum,
    )


def parse_composition(data: dict[str, Any]) -> dict[str, FaderState]:
    """Parse composition JSON into a map of fader states by stable key."""
    faders: dict[str, FaderState] = {}

    comp_master = _parse_range(data.get("master"))
    if comp_master is not None:
        param_id, value, minimum, maximum = comp_master
        faders[KIND_COMPOSITION] = FaderState(
            key=KIND_COMPOSITION,
            kind=KIND_COMPOSITION,
            name="Composition",
            parameter_id=param_id,
            parameter_path=COMPOSITION_MASTER_PATH,
            layer_id=None,
            layer_index=None,
            value=value,
            minimum=minimum,
            maximum=maximum,
        )

    layers = data.get("layers")
    if not isinstance(layers, list):
        return faders

    for position, layer in enumerate(layers, start=1):
        if not isinstance(layer, dict):
            continue
        master = _parse_range(layer.get("master"))
        if master is None:
            continue
        param_id, value, minimum, maximum = master
        layer_id = layer.get("id")
        key = f"layer:{layer_id}" if layer_id is not None else f"pos:{position}"
        faders[key] = FaderState(
            key=key,
            kind=KIND_LAYER,
            name=_param_value(layer.get("name"), f"Layer {position}"),
            parameter_id=param_id,
            parameter_path=layer_master_path(position),
            layer_id=int(layer_id) if layer_id is not None else None,
            layer_index=position,
            value=value,
            minimum=minimum,
            maximum=maximum,
        )
    return faders


def extract_parameter_update(
    message: dict[str, Any],
) -> tuple[str, float] | None:
    """Extract (parameter_path, raw_value) from a WebSocket push message.

    Resolume wraps parameter updates as
    ``{"type": "parameter_update", "path": ..., "value": ...}`` where value
    may be a scalar or a full parameter object. Returns None for messages
    that are not numeric parameter updates.
    """
    msg_type = message.get("type", "")
    if not str(msg_type).startswith("parameter_"):
        return None
    path = message.get("path") or message.get("parameter")
    if not isinstance(path, str):
        return None
    value: Any = message.get("value")
    if isinstance(value, dict):
        value = value.get("value")
    try:
        return path, float(value)
    except (TypeError, ValueError):
        return None
