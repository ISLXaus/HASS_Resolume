"""HTTP view proxying Resolume clip thumbnails through Home Assistant.

Serving thumbnails via Home Assistant (instead of pointing the browser at
the Resolume webserver directly) makes them work from remote access and
the mobile apps. Image tags cannot send authentication headers, so the
view is unauthenticated but gated by a per-entry random token embedded in
the entity_picture URL.
"""

from __future__ import annotations

import logging
from http import HTTPStatus

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from .api import ResolumeConnectionError
from .const import DATA_THUMBNAIL_TOKENS, DOMAIN, THUMBNAIL_URL

_LOGGER = logging.getLogger(__name__)


def thumbnail_url(
    entry_id: str,
    token: str,
    layer_index: int,
    clip_index: int,
    cache_key: str,
) -> str:
    """Build the proxied thumbnail URL for a clip."""
    return (
        THUMBNAIL_URL.format(
            entry_id=entry_id, layer_index=layer_index, clip_index=clip_index
        )
        + f"?token={token}&cb={cache_key}"
    )


class ResolumeThumbnailView(HomeAssistantView):
    """Serve clip thumbnails fetched from the Resolume webserver."""

    url = THUMBNAIL_URL  # aiohttp route pattern with {placeholders}
    name = "api:resolume:thumbnail"
    requires_auth = False  # <img> tags cannot send auth headers; token-gated

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the view."""
        self.hass = hass

    async def get(
        self,
        request: web.Request,
        entry_id: str,
        layer_index: str,
        clip_index: str,
    ) -> web.Response:
        """Return the PNG thumbnail for a clip."""
        entry = self.hass.config_entries.async_get_entry(entry_id)
        if (
            entry is None
            or entry.domain != DOMAIN
            or entry.state is not ConfigEntryState.LOADED
        ):
            return web.Response(status=HTTPStatus.NOT_FOUND)

        tokens: dict[str, str] = self.hass.data.get(DOMAIN, {}).get(
            DATA_THUMBNAIL_TOKENS, {}
        )
        if request.query.get("token") != tokens.get(entry_id):
            return web.Response(status=HTTPStatus.UNAUTHORIZED)

        try:
            image = await entry.runtime_data.client.async_get_thumbnail(
                int(layer_index), int(clip_index)
            )
        except ValueError:
            return web.Response(status=HTTPStatus.BAD_REQUEST)
        except ResolumeConnectionError as err:
            _LOGGER.debug("Thumbnail fetch failed: %s", err)
            return web.Response(status=HTTPStatus.BAD_GATEWAY)

        return web.Response(
            body=image,
            content_type="image/png",
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )
