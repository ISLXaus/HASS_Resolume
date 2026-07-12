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


@dataclass(slots=True, frozen=True)
class ClipState:
    """State of one clip slot in the composition grid."""

    key: str  # stable key: "clip:<clip-id>"
    clip_id: int | None
    name: str
    layer_name: str
    layer_index: int  # 1-based
    clip_index: int  # 1-based column position
    connected: str  # raw ChoiceParameter value, e.g. "Connected"
    thumbnail_last_update: str  # opaque timestamp, used for cache busting
    thumbnail_is_default: bool

    @property
    def playing(self) -> bool:
        """Return whether the clip is currently connected (playing)."""
        return self.connected.lower().startswith("connected")

    @property
    def connected_path(self) -> str:
        """Return the parameter path of the clip's connected state."""
        return (
            f"/composition/layers/{self.layer_index}"
            f"/clips/{self.clip_index}/connected"
        )

    def with_connected(self, connected: str) -> ClipState:
        """Return a copy with an updated connected state."""
        return replace(self, connected=connected)


@dataclass(slots=True, frozen=True)
class CompositionModel:
    """Flattened view of the composition: faders and clips by stable key."""

    faders: dict[str, FaderState]
    clips: dict[str, ClipState]


def _parse_clip(
    clip: Any,
    layer_name: str,
    layer_index: int,
    clip_index: int,
) -> ClipState | None:
    """Parse one clip slot; returns None for empty or malformed slots."""
    if not isinstance(clip, dict):
        return None
    name = _param_value(clip.get("name"))
    thumbnail = clip.get("thumbnail")
    thumbnail = thumbnail if isinstance(thumbnail, dict) else {}
    is_default = bool(thumbnail.get("is_default", thumbnail.get("default", True)))
    # Empty grid slots have no name and only the default thumbnail.
    if not name and is_default:
        return None
    clip_id = clip.get("id")
    connected = clip.get("connected")
    connected_value = (
        str(connected.get("value", "")) if isinstance(connected, dict) else ""
    )
    return ClipState(
        key=(
            f"clip:{clip_id}"
            if clip_id is not None
            else f"clippos:{layer_index}:{clip_index}"
        ),
        clip_id=int(clip_id) if clip_id is not None else None,
        name=name or f"Clip {clip_index}",
        layer_name=layer_name,
        layer_index=layer_index,
        clip_index=clip_index,
        connected=connected_value,
        thumbnail_last_update=str(thumbnail.get("last_update", "0")),
        thumbnail_is_default=is_default,
    )


def parse_composition(data: dict[str, Any]) -> CompositionModel:
    """Parse composition JSON into fader and clip states by stable key."""
    faders: dict[str, FaderState] = {}
    clips: dict[str, ClipState] = {}

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
        return CompositionModel(faders=faders, clips=clips)

    for position, layer in enumerate(layers, start=1):
        if not isinstance(layer, dict):
            continue
        layer_name = _param_value(layer.get("name"), f"Layer {position}")
        master = _parse_range(layer.get("master"))
        if master is not None:
            param_id, value, minimum, maximum = master
            layer_id = layer.get("id")
            key = (
                f"layer:{layer_id}" if layer_id is not None else f"pos:{position}"
            )
            faders[key] = FaderState(
                key=key,
                kind=KIND_LAYER,
                name=layer_name,
                parameter_id=param_id,
                parameter_path=layer_master_path(position),
                layer_id=int(layer_id) if layer_id is not None else None,
                layer_index=position,
                value=value,
                minimum=minimum,
                maximum=maximum,
            )

        layer_clips = layer.get("clips")
        if not isinstance(layer_clips, list):
            continue
        for clip_position, clip in enumerate(layer_clips, start=1):
            state = _parse_clip(clip, layer_name, position, clip_position)
            if state is not None:
                clips[state.key] = state

    return CompositionModel(faders=faders, clips=clips)


def extract_parameter_update(
    message: dict[str, Any],
) -> tuple[str, Any] | None:
    """Extract (parameter_path, scalar_value) from a WebSocket push message.

    Resolume wraps parameter updates as
    ``{"type": "parameter_update", "path": ..., "value": ...}`` where value
    may be a scalar or a full parameter object. Returns None for messages
    that are not scalar parameter updates.
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
    if isinstance(value, (int, float, str, bool)):
        return path, value
    return None
