"""End-to-end tests against a fake Resolume webserver.

Covers config flow, entity creation, slider set -> REST PUT, and WebSocket
parameter pushes -> entity state. Requires
pytest-homeassistant-custom-component; skipped when unavailable.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from aiohttp import WSMsgType, web  # noqa: E402
from aiohttp.test_utils import TestServer  # noqa: E402
from homeassistant.config_entries import SOURCE_USER  # noqa: E402
from homeassistant.const import CONF_HOST, CONF_PORT  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402
from pytest_homeassistant_custom_component.common import (  # noqa: E402
    MockConfigEntry,
)

from custom_components.resolume.const import DOMAIN  # noqa: E402

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _enable(enable_custom_integrations, socket_enabled):
    """Allow the custom integration and localhost sockets."""
    return


FAKE_PNG = b"\x89PNG\r\n\x1a\nfakepng"


def make_composition(layer1_value: float = 0.5) -> dict:
    return {
        "name": {"value": "My Comp"},
        "master": {"id": 100, "value": 1.0, "min": 0.0, "max": 1.0},
        "layers": [
            {
                "id": 5001,
                "name": {"value": "Background"},
                "master": {
                    "id": 101,
                    "value": layer1_value,
                    "min": 0.0,
                    "max": 1.0,
                },
                "clips": [
                    {
                        "id": 9001,
                        "name": {"value": "Intro Loop"},
                        "connected": {"value": "Disconnected"},
                        "thumbnail": {
                            "last_update": "1700000000123",
                            "is_default": False,
                        },
                    },
                ],
            },
        ],
    }


@dataclass
class FakeResolume:
    """A minimal Resolume webserver: REST + WebSocket."""

    composition: dict = field(default_factory=make_composition)
    puts: list[tuple[int, dict]] = field(default_factory=list)
    connects: list[tuple[int, int]] = field(default_factory=list)
    subscriptions: list[str] = field(default_factory=list)
    ws: web.WebSocketResponse | None = None

    async def product(self, request: web.Request) -> web.Response:
        return web.json_response(
            {"name": "Arena", "major": 7, "minor": 21, "micro": 0, "revision": 1}
        )

    async def get_composition(self, request: web.Request) -> web.Response:
        return web.json_response(self.composition)

    async def put_parameter(self, request: web.Request) -> web.Response:
        param_id = int(request.match_info["param_id"])
        self.puts.append((param_id, await request.json()))
        return web.Response(status=204)

    async def connect_clip(self, request: web.Request) -> web.Response:
        self.connects.append(
            (
                int(request.match_info["layer"]),
                int(request.match_info["clip"]),
            )
        )
        return web.Response(status=204)

    async def thumbnail(self, request: web.Request) -> web.Response:
        return web.Response(body=FAKE_PNG, content_type="image/png")

    async def websocket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.ws = ws
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                break
            data = json.loads(msg.data)
            if data.get("action") == "subscribe":
                self.subscriptions.append(data["parameter"])
        return ws

    async def push(self, path: str, value: object) -> None:
        assert self.ws is not None
        await self.ws.send_json(
            {"type": "parameter_update", "path": path, "value": value}
        )


@contextlib.asynccontextmanager
async def fake_resolume() -> AsyncIterator[tuple[FakeResolume, int]]:
    fake = FakeResolume()
    app = web.Application()
    app.router.add_get("/api/v1/product", fake.product)
    app.router.add_get("/api/v1/composition", fake.get_composition)
    app.router.add_put(
        "/api/v1/parameter/by-id/{param_id}", fake.put_parameter
    )
    app.router.add_post(
        "/api/v1/composition/layers/{layer}/clips/{clip}/connect",
        fake.connect_clip,
    )
    app.router.add_get(
        "/api/v1/composition/layers/{layer}/clips/{clip}/thumbnail",
        fake.thumbnail,
    )
    app.router.add_get("/api/v1", fake.websocket)
    server = TestServer(app)
    await server.start_server()
    try:
        yield fake, server.port
    finally:
        await server.close()


async def _wait_for(condition, timeout=5.0):
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.01)


async def test_config_flow(hass: HomeAssistant) -> None:
    async with fake_resolume() as (_fake, port):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "127.0.0.1", CONF_PORT: port}
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert "Arena 7.21.0" in result["title"]
        await hass.async_block_till_done()


async def test_config_flow_cannot_connect(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "127.0.0.1", CONF_PORT: 1}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def _setup(hass: HomeAssistant, port: int) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_HOST: "127.0.0.1", CONF_PORT: port}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_sliders_created_and_set(hass: HomeAssistant) -> None:
    async with fake_resolume() as (fake, port):
        entry = await _setup(hass, port)

        comp = hass.states.get("number.resolume_127_0_0_1_composition_master")
        layer = hass.states.get("number.resolume_127_0_0_1_background_master")
        assert comp is not None and float(comp.state) == 100.0
        assert layer is not None and float(layer.state) == 50.0
        assert layer.attributes["layer_index"] == 1

        # Moving the HA slider PUTs the raw value to the parameter id.
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": layer.entity_id, "value": 75},
            blocking=True,
        )
        assert fake.puts == [(101, {"value": 0.75})]
        assert (
            float(hass.states.get(layer.entity_id).state) == 75.0
        )  # optimistic

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_clip_button_and_thumbnail(
    hass: HomeAssistant, hass_client
) -> None:
    async with fake_resolume() as (fake, port):
        entry = await _setup(hass, port)

        clip = hass.states.get("button.resolume_127_0_0_1_intro_loop")
        assert clip is not None
        assert clip.attributes["clip_name"] == "Intro Loop"
        assert clip.attributes["layer_index"] == 1
        assert clip.attributes["clip_index"] == 1
        assert clip.attributes["playing"] is False

        # Pressing the button connects the clip in Resolume.
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": clip.entity_id},
            blocking=True,
        )
        assert fake.connects == [(1, 1)]

        # The entity picture is a token-gated proxy URL serving the PNG.
        picture = clip.attributes["entity_picture"]
        assert picture.startswith(
            f"/api/resolume/{entry.entry_id}/thumbnail/1/1.png?token="
        )
        assert "cb=1700000000123" in picture
        client = await hass_client()
        response = await client.get(picture)
        assert response.status == 200
        assert await response.read() == FAKE_PNG

        # A wrong token is rejected.
        bad = picture.split("?")[0] + "?token=wrong"
        response = await client.get(bad)
        assert response.status == 401

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_ws_push_updates_clip_connected(hass: HomeAssistant) -> None:
    async with fake_resolume() as (fake, port):
        entry = await _setup(hass, port)

        await _wait_for(
            lambda: "/composition/layers/1/clips/1/connected"
            in fake.subscriptions
        )
        await fake.push("/composition/layers/1/clips/1/connected", "Connected")
        await _wait_for(
            lambda: hass.states.get(
                "button.resolume_127_0_0_1_intro_loop"
            ).attributes["playing"]
            is True
        )

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_ws_push_updates_slider(hass: HomeAssistant) -> None:
    async with fake_resolume() as (fake, port):
        entry = await _setup(hass, port)

        # The client subscribes to every fader after connecting.
        await _wait_for(
            lambda: "/composition/layers/1/master" in fake.subscriptions
        )

        await fake.push("/composition/layers/1/master", 0.9)
        await _wait_for(
            lambda: float(
                hass.states.get(
                    "number.resolume_127_0_0_1_background_master"
                ).state
            )
            == 90.0
        )

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
