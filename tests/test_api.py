"""Tests for composition parsing (no Home Assistant needed)."""

from __future__ import annotations

from custom_components.resolume.api import (
    KIND_COMPOSITION,
    KIND_LAYER,
    extract_parameter_update,
    parse_composition,
)


def make_composition() -> dict:
    """Return a realistic minimal composition JSON."""
    return {
        "name": {"value": "My Comp"},
        "master": {
            "id": 100,
            "valuetype": "ParamRange",
            "value": 1.0,
            "min": 0.0,
            "max": 1.0,
        },
        "layers": [
            {
                "id": 5001,
                "name": {"value": "Background"},
                "master": {"id": 101, "value": 0.5, "min": 0.0, "max": 1.0},
                "clips": [
                    {
                        "id": 9001,
                        "name": {"value": "Intro Loop"},
                        "connected": {"value": "Connected"},
                        "thumbnail": {
                            "last_update": "1700000000123",
                            "size": 1234,
                            "is_default": False,
                        },
                    },
                    {  # empty slot: default thumbnail, no name
                        "id": 9002,
                        "name": {"value": ""},
                        "connected": {"value": ""},
                        "thumbnail": {"last_update": "0", "is_default": True},
                    },
                ],
            },
            {
                "id": 5002,
                "name": {"value": "FX"},
                "master": {"id": 102, "value": 0.25, "min": 0.0, "max": 1.0},
            },
        ],
    }


class TestParseComposition:
    def test_composition_and_layers(self) -> None:
        faders = parse_composition(make_composition()).faders
        assert set(faders) == {"composition", "layer:5001", "layer:5002"}

        comp = faders["composition"]
        assert comp.kind == KIND_COMPOSITION
        assert comp.parameter_id == 100
        assert comp.parameter_path == "/composition/master"
        assert comp.percentage == 100.0

        layer = faders["layer:5001"]
        assert layer.kind == KIND_LAYER
        assert layer.name == "Background"
        assert layer.layer_index == 1
        assert layer.parameter_path == "/composition/layers/1/master"
        assert layer.percentage == 50.0

    def test_layer_order_is_positional(self) -> None:
        data = make_composition()
        data["layers"].reverse()
        faders = parse_composition(data).faders
        # Stable keys follow layer ids; paths follow position.
        assert faders["layer:5002"].layer_index == 1
        assert faders["layer:5002"].parameter_path == (
            "/composition/layers/1/master"
        )

    def test_missing_or_malformed_bits_are_skipped(self) -> None:
        faders = parse_composition(
            {
                "master": {"value": "not-a-number"},
                "layers": [
                    {"id": 1},  # no master
                    "garbage",
                    {"id": 2, "master": {"value": 0.5}},  # defaults 0..1
                ],
            }
        ).faders
        assert set(faders) == {"layer:2"}
        assert faders["layer:2"].percentage == 50.0

    def test_layer_without_name_gets_positional_name(self) -> None:
        data = make_composition()
        del data["layers"][0]["name"]
        faders = parse_composition(data).faders
        assert faders["layer:5001"].name == "Layer 1"

    def test_percentage_roundtrip(self) -> None:
        fader = parse_composition(make_composition()).faders["layer:5001"]
        assert fader.value_from_percentage(fader.percentage) == fader.value
        assert fader.value_from_percentage(150.0) == fader.maximum
        assert fader.value_from_percentage(-5.0) == fader.minimum


class TestParseClips:
    def test_clip_parsed_and_empty_slot_skipped(self) -> None:
        clips = parse_composition(make_composition()).clips
        assert set(clips) == {"clip:9001"}

        clip = clips["clip:9001"]
        assert clip.name == "Intro Loop"
        assert clip.layer_name == "Background"
        assert clip.layer_index == 1
        assert clip.clip_index == 1
        assert clip.playing is True
        assert clip.thumbnail_last_update == "1700000000123"
        assert clip.connected_path == (
            "/composition/layers/1/clips/1/connected"
        )

    def test_connected_states(self) -> None:
        data = make_composition()
        data["layers"][0]["clips"][0]["connected"]["value"] = "Disconnected"
        clip = parse_composition(data).clips["clip:9001"]
        assert clip.playing is False
        assert clip.with_connected("Connected").playing is True

    def test_clip_with_custom_thumbnail_but_no_name_included(self) -> None:
        data = make_composition()
        data["layers"][0]["clips"][0]["name"]["value"] = ""
        clips = parse_composition(data).clips
        assert clips["clip:9001"].name == "Clip 1"


class TestExtractParameterUpdate:
    def test_scalar_value(self) -> None:
        assert extract_parameter_update(
            {
                "type": "parameter_update",
                "path": "/composition/layers/1/master",
                "value": 0.7,
            }
        ) == ("/composition/layers/1/master", 0.7)

    def test_object_value_and_parameter_key(self) -> None:
        assert extract_parameter_update(
            {
                "type": "parameter_set",
                "parameter": "/composition/master",
                "value": {"id": 100, "value": 0.3, "min": 0, "max": 1},
            }
        ) == ("/composition/master", 0.3)

    def test_string_values_pass_through(self) -> None:
        # Clip connected states are ChoiceParameter strings.
        assert extract_parameter_update(
            {"type": "parameter_update", "path": "/x", "value": "Connected"}
        ) == ("/x", "Connected")

    def test_irrelevant_messages(self) -> None:
        assert extract_parameter_update({"type": "sources_update"}) is None
        assert extract_parameter_update({}) is None
        assert (
            extract_parameter_update(
                {"type": "parameter_update", "path": "/x", "value": [1, 2]}
            )
            is None
        )
