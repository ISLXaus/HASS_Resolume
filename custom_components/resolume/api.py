"""Data model and composition parsing for the Resolume Arena REST API.

This module has no Home Assistant dependencies so it can be unit tested in
isolation. It flattens Resolume's composition JSON (see
https://resolume.com/docs/restapi/) into maps of faders (RangeParameters),
toggles (BooleanParameters), triggers (one-shot actions) and clips.
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
    """State of one continuous fader (any RangeParameter)."""

    key: str  # stable key, e.g. "layer:5001" or "layer:5001:opacity"
    kind: str  # "composition"/"layer" for masters (legacy ids), else "fader"
    name: str  # full display name, e.g. "Background opacity"
    parameter_id: int | None  # Resolume's unique parameter id
    parameter_path: str  # e.g. /composition/layers/1/video/opacity
    layer_id: int | None  # Resolume's stable layer id, when applicable
    layer_index: int | None  # current 1-based position, when applicable
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


@dataclass(slots=True, frozen=True)
class ToggleState:
    """State of one boolean parameter (bypassed, solo, ...)."""

    key: str  # e.g. "layer:5001:solo"
    name: str  # e.g. "Background solo"
    toggle_type: str  # "bypassed" or "solo"
    parameter_id: int | None
    parameter_path: str
    layer_id: int | None
    layer_index: int | None
    value: bool

    def with_value(self, value: bool) -> ToggleState:
        """Return a copy with an updated value."""
        return replace(self, value=value)


@dataclass(slots=True, frozen=True)
class TriggerState:
    """A one-shot action: connect a column, disconnect all, tap tempo."""

    key: str  # e.g. "column:301", "disconnect_all", "tempo_tap"
    name: str
    trigger_type: str  # "column", "disconnect_all" or "parameter"
    column_index: int | None = None  # for column triggers (1-based)
    parameter_id: int | None = None  # for parameter (event) triggers


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
    """Flattened view of the composition, all keyed by stable ids."""

    faders: dict[str, FaderState]
    clips: dict[str, ClipState]
    toggles: dict[str, ToggleState]
    triggers: dict[str, TriggerState]


def empty_model() -> CompositionModel:
    """Return an empty composition model."""
    return CompositionModel(faders={}, clips={}, toggles={}, triggers={})


# Parameter object helpers


def _param_value(param: Any, default: str = "") -> str:
    """Extract the value of a string parameter object."""
    if isinstance(param, dict):
        value = param.get("value")
        if value is not None:
            return str(value)
    return default


def _param_id(param: Any) -> int | None:
    """Extract the id of a parameter object."""
    if isinstance(param, dict) and param.get("id") is not None:
        try:
            return int(param["id"])
        except (TypeError, ValueError):
            return None
    return None


def _parse_range(param: Any) -> tuple[int | None, float, float, float] | None:
    """Extract (id, value, min, max) from a RangeParameter object."""
    if not isinstance(param, dict):
        return None
    try:
        value = float(param["value"])
    except (KeyError, TypeError, ValueError):
        return None
    minimum = float(param.get("min", 0.0))
    maximum = float(param.get("max", 1.0))
    if maximum <= minimum:
        minimum, maximum = 0.0, 1.0
    return _param_id(param), value, minimum, maximum


def parse_bool_value(value: Any) -> bool:
    """Interpret a pushed/parsed parameter value as a boolean."""
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "on", "yes")
    return bool(value)


def _parse_bool(param: Any) -> tuple[int | None, bool] | None:
    """Extract (id, value) from a BooleanParameter object."""
    if not isinstance(param, dict) or "value" not in param:
        return None
    return _param_id(param), parse_bool_value(param["value"])


def _dig(data: Any, *keys: str) -> Any:
    """Safely walk nested dicts."""
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


# Composition parsing


class _ModelBuilder:
    """Accumulates flattened state while walking the composition."""

    def __init__(self) -> None:
        self.faders: dict[str, FaderState] = {}
        self.clips: dict[str, ClipState] = {}
        self.toggles: dict[str, ToggleState] = {}
        self.triggers: dict[str, TriggerState] = {}

    def add_fader(
        self,
        param: Any,
        *,
        key: str,
        kind: str,
        name: str,
        path: str,
        layer_id: int | None = None,
        layer_index: int | None = None,
    ) -> None:
        parsed = _parse_range(param)
        if parsed is None:
            return
        param_id, value, minimum, maximum = parsed
        self.faders[key] = FaderState(
            key=key,
            kind=kind,
            name=name,
            parameter_id=param_id,
            parameter_path=path,
            layer_id=layer_id,
            layer_index=layer_index,
            value=value,
            minimum=minimum,
            maximum=maximum,
        )

    def add_toggle(
        self,
        param: Any,
        *,
        key: str,
        name: str,
        toggle_type: str,
        path: str,
        layer_id: int | None = None,
        layer_index: int | None = None,
    ) -> None:
        parsed = _parse_bool(param)
        if parsed is None:
            return
        param_id, value = parsed
        self.toggles[key] = ToggleState(
            key=key,
            name=name,
            toggle_type=toggle_type,
            parameter_id=param_id,
            parameter_path=path,
            layer_id=layer_id,
            layer_index=layer_index,
            value=value,
        )


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


def _parse_layer(
    builder: _ModelBuilder, layer: dict[str, Any], position: int
) -> None:
    """Flatten one layer: master, opacity, volume, bypassed, solo, clips."""
    layer_name = _param_value(layer.get("name"), f"Layer {position}")
    layer_id_raw = layer.get("id")
    layer_id = int(layer_id_raw) if layer_id_raw is not None else None
    base_key = f"layer:{layer_id}" if layer_id is not None else f"pos:{position}"
    base_path = f"/composition/layers/{position}"
    common = {"layer_id": layer_id, "layer_index": position}

    builder.add_fader(
        layer.get("master"),
        key=base_key,  # legacy key kept for existing master entity ids
        kind=KIND_LAYER,
        name=f"{layer_name} master",
        path=f"{base_path}/master",
        **common,
    )
    builder.add_fader(
        _dig(layer, "video", "opacity"),
        key=f"{base_key}:opacity",
        kind="fader",
        name=f"{layer_name} opacity",
        path=f"{base_path}/video/opacity",
        **common,
    )
    builder.add_fader(
        _dig(layer, "audio", "volume"),
        key=f"{base_key}:volume",
        kind="fader",
        name=f"{layer_name} volume",
        path=f"{base_path}/audio/volume",
        **common,
    )
    builder.add_toggle(
        layer.get("bypassed"),
        key=f"{base_key}:bypassed",
        name=f"{layer_name} bypassed",
        toggle_type="bypassed",
        path=f"{base_path}/bypassed",
        **common,
    )
    builder.add_toggle(
        layer.get("solo"),
        key=f"{base_key}:solo",
        name=f"{layer_name} solo",
        toggle_type="solo",
        path=f"{base_path}/solo",
        **common,
    )

    layer_clips = layer.get("clips")
    if isinstance(layer_clips, list):
        for clip_position, clip in enumerate(layer_clips, start=1):
            state = _parse_clip(clip, layer_name, position, clip_position)
            if state is not None:
                builder.clips[state.key] = state


def parse_composition(data: dict[str, Any]) -> CompositionModel:
    """Parse composition JSON into flattened state maps."""
    builder = _ModelBuilder()

    # Composition-level faders.
    builder.add_fader(
        data.get("master"),
        key=KIND_COMPOSITION,  # legacy key kept for existing entity ids
        kind=KIND_COMPOSITION,
        name="Composition master",
        path=COMPOSITION_MASTER_PATH,
    )
    builder.add_fader(
        data.get("speed"),
        key="composition:speed",
        kind="fader",
        name="Composition speed",
        path="/composition/speed",
    )
    builder.add_fader(
        _dig(data, "video", "opacity"),
        key="composition:opacity",
        kind="fader",
        name="Composition opacity",
        path="/composition/video/opacity",
    )
    builder.add_fader(
        _dig(data, "audio", "volume"),
        key="composition:volume",
        kind="fader",
        name="Composition volume",
        path="/composition/audio/volume",
    )
    builder.add_fader(
        _dig(data, "crossfader", "phase"),
        key="crossfader",
        kind="fader",
        name="Crossfader",
        path="/composition/crossfader/phase",
    )

    builder.add_toggle(
        data.get("bypassed"),
        key="composition:bypassed",
        name="Composition bypassed",
        toggle_type="bypassed",
        path="/composition/bypassed",
    )

    # Layers (masters, opacity, volume, bypassed, solo, clips).
    layers = data.get("layers")
    if isinstance(layers, list):
        for position, layer in enumerate(layers, start=1):
            if isinstance(layer, dict):
                _parse_layer(builder, layer, position)

    # Layer group masters.
    groups = data.get("layergroups")
    if isinstance(groups, list):
        for position, group in enumerate(groups, start=1):
            if not isinstance(group, dict):
                continue
            group_id = group.get("id")
            group_key = (
                f"group:{group_id}"
                if group_id is not None
                else f"grouppos:{position}"
            )
            builder.add_fader(
                group.get("master"),
                key=f"{group_key}:master",
                kind="fader",
                name=(
                    f"{_param_value(group.get('name'), f'Group {position}')}"
                    " master"
                ),
                path=f"/composition/layergroups/{position}/master",
            )

    # Column trigger buttons.
    columns = data.get("columns")
    if isinstance(columns, list):
        for position, column in enumerate(columns, start=1):
            if not isinstance(column, dict):
                continue
            column_id = column.get("id")
            key = (
                f"column:{column_id}"
                if column_id is not None
                else f"columnpos:{position}"
            )
            custom_name = _param_value(column.get("name"))
            builder.triggers[key] = TriggerState(
                key=key,
                name=(
                    f"Column {custom_name}"
                    if custom_name
                    else f"Column {position}"
                ),
                trigger_type="column",
                column_index=position,
            )

    # Global actions.
    builder.triggers["disconnect_all"] = TriggerState(
        key="disconnect_all",
        name="Disconnect all",
        trigger_type="disconnect_all",
    )
    tap_id = _param_id(_dig(data, "tempocontroller", "tempo_tap"))
    if tap_id is not None:
        builder.triggers["tempo_tap"] = TriggerState(
            key="tempo_tap",
            name="Tap tempo",
            trigger_type="parameter",
            parameter_id=tap_id,
        )

    return CompositionModel(
        faders=builder.faders,
        clips=builder.clips,
        toggles=builder.toggles,
        triggers=builder.triggers,
    )


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
