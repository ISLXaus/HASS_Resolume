"""Client for the Resolume Arena webserver: REST calls plus WebSocket push.

REST (``http://host:port/api/v1``) is used to validate the connection,
fetch the composition and set parameter values. The WebSocket endpoint on
the same port (``ws://host:port/api/v1``) is used to subscribe to parameter
changes so faders update in Home Assistant in real time. The WebSocket
reconnects automatically with exponential backoff; if it is down, the
coordinator's periodic REST refresh keeps state eventually consistent.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

from .api import ResolumeConnectionError

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10.0
WS_HEARTBEAT = 20.0
RECONNECT_MIN = 1.0
RECONNECT_MAX = 60.0

MessageCallback = Callable[[dict[str, Any]], None]
ConnectionCallback = Callable[[], Awaitable[None]]


class ResolumeClient:
    """Asynchronous client for a Resolume Arena/Avenue webserver."""

    def __init__(
        self, host: str, port: int, session: aiohttp.ClientSession
    ) -> None:
        """Initialize the client."""
        self._host = host
        self._port = port
        self._session = session
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._ws_task: asyncio.Task[None] | None = None
        self._closing = False
        self._ws_connected = False

        self.product_name: str | None = None
        self.product_version: str | None = None

        self.on_message: MessageCallback | None = None
        self.on_ws_connected: ConnectionCallback | None = None
        self.on_ws_disconnected: ConnectionCallback | None = None

    @property
    def base_url(self) -> str:
        """Return the REST base URL."""
        return f"http://{self._host}:{self._port}/api/v1"

    @property
    def ws_url(self) -> str:
        """Return the WebSocket URL."""
        return f"ws://{self._host}:{self._port}/api/v1"

    @property
    def ws_connected(self) -> bool:
        """Return whether the push channel is currently up."""
        return self._ws_connected

    # REST

    async def _request(
        self, method: str, path: str, json: Any | None = None
    ) -> Any:
        """Perform a REST request and return decoded JSON (or None)."""
        url = f"{self.base_url}{path}"
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                response = await self._session.request(method, url, json=json)
                async with response:
                    response.raise_for_status()
                    if response.status == 204:
                        return None
                    return await response.json(content_type=None)
        except (aiohttp.ClientError, OSError, TimeoutError) as err:
            raise ResolumeConnectionError(
                f"Error communicating with Resolume at {url}: {err}"
            ) from err

    async def async_validate(self) -> str:
        """Check the connection and return the product name + version."""
        product = await self._request("GET", "/product")
        if not isinstance(product, dict) or "name" not in product:
            raise ResolumeConnectionError(
                f"{self.base_url} does not look like a Resolume webserver"
            )
        self.product_name = str(product.get("name"))
        self.product_version = ".".join(
            str(product.get(part, 0)) for part in ("major", "minor", "micro")
        )
        return f"{self.product_name} {self.product_version}"

    async def async_get_composition(self) -> dict[str, Any]:
        """Fetch the full composition."""
        data = await self._request("GET", "/composition")
        if not isinstance(data, dict):
            raise ResolumeConnectionError("Composition response was not JSON")
        return data

    async def async_set_parameter(self, parameter_id: int, value: float) -> None:
        """Set a parameter value by its unique id."""
        await self._request(
            "PUT", f"/parameter/by-id/{parameter_id}", json={"value": value}
        )

    async def async_connect_clip(
        self, layer_index: int, clip_index: int
    ) -> None:
        """Trigger (connect) a clip by its grid position (1-based)."""
        await self._request(
            "POST",
            f"/composition/layers/{layer_index}/clips/{clip_index}/connect",
        )

    async def async_get_thumbnail(
        self, layer_index: int, clip_index: int
    ) -> bytes:
        """Fetch a clip's PNG thumbnail by grid position (1-based)."""
        url = (
            f"{self.base_url}/composition/layers/{layer_index}"
            f"/clips/{clip_index}/thumbnail"
        )
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                response = await self._session.get(url)
                async with response:
                    response.raise_for_status()
                    return await response.read()
        except (aiohttp.ClientError, OSError, TimeoutError) as err:
            raise ResolumeConnectionError(
                f"Error fetching thumbnail from {url}: {err}"
            ) from err

    # WebSocket push channel

    async def async_start_ws(self) -> None:
        """Start the background WebSocket task (never raises)."""
        self._closing = False
        if self._ws_task is None:
            self._ws_task = asyncio.ensure_future(self._ws_loop())

    async def async_stop(self) -> None:
        """Stop the WebSocket task and close the connection."""
        self._closing = True
        if self._ws_task is not None:
            self._ws_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._ws_task
            self._ws_task = None
        await self._close_ws()

    async def async_subscribe(self, parameter_path: str) -> None:
        """Subscribe to updates for a parameter path."""
        await self._ws_send(
            {"action": "subscribe", "parameter": parameter_path}
        )

    async def _ws_send(self, message: dict[str, Any]) -> None:
        """Send a JSON message over the WebSocket."""
        ws = self._ws
        if ws is None or ws.closed:
            raise ResolumeConnectionError("WebSocket is not connected")
        _LOGGER.debug("WS sending: %s", message)
        try:
            await ws.send_json(message)
        except (aiohttp.ClientError, ConnectionError, OSError) as err:
            raise ResolumeConnectionError(f"WebSocket send failed: {err}") from err

    async def _ws_loop(self) -> None:
        """Maintain the WebSocket connection with exponential backoff."""
        backoff = RECONNECT_MIN
        while not self._closing:
            try:
                self._ws = await self._session.ws_connect(
                    self.ws_url, heartbeat=WS_HEARTBEAT
                )
            except (aiohttp.ClientError, OSError, TimeoutError) as err:
                _LOGGER.debug("WebSocket connect failed: %s", err)
                await asyncio.sleep(backoff + random.uniform(0, backoff / 4))
                backoff = min(backoff * 2, RECONNECT_MAX)
                continue

            backoff = RECONNECT_MIN
            self._ws_connected = True
            _LOGGER.info("Connected to Resolume WebSocket at %s", self.ws_url)
            if self.on_ws_connected is not None:
                try:
                    await self.on_ws_connected()
                except ResolumeConnectionError as err:
                    _LOGGER.debug("Error during WS connect handling: %s", err)

            try:
                await self._ws_read()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - keep the loop alive
                _LOGGER.exception("Unexpected error in Resolume WS loop")
            finally:
                await self._close_ws()
                if not self._closing:
                    _LOGGER.warning(
                        "Lost WebSocket connection to Resolume at %s",
                        self.ws_url,
                    )
                    if self.on_ws_disconnected is not None:
                        await self.on_ws_disconnected()

    async def _ws_read(self) -> None:
        """Receive and dispatch messages until the connection drops."""
        ws = self._ws
        if ws is None:
            return
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    data = msg.json()
                except ValueError:
                    _LOGGER.debug("Ignoring non-JSON WS message")
                    continue
                if isinstance(data, dict) and self.on_message is not None:
                    self.on_message(data)
            elif msg.type == aiohttp.WSMsgType.ERROR:
                return

    async def _close_ws(self) -> None:
        """Close the WebSocket connection."""
        self._ws_connected = False
        if self._ws is not None:
            with contextlib.suppress(aiohttp.ClientError, OSError):
                await self._ws.close()
            self._ws = None
