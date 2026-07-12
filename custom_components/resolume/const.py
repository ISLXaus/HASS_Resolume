"""Constants for the Resolume Arena integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "resolume"
MANUFACTURER: Final = "Resolume"

DEFAULT_PORT: Final = 8080

# Seconds between REST resyncs (safety net; live updates come over the
# WebSocket push channel).
UPDATE_INTERVAL: Final = 30

# Route pattern for the thumbnail proxy view.
THUMBNAIL_URL: Final = (
    "/api/resolume/{entry_id}/thumbnail/{layer_index}/{clip_index}.png"
)

# hass.data keys
DATA_THUMBNAIL_TOKENS: Final = "thumbnail_tokens"
DATA_FRONTEND: Final = "frontend_registered"
DATA_VIEW: Final = "view_registered"

# Frontend cards
CARD_FILENAMES: Final = ("resolume-clip-card.js", "resolume-fader-card.js")
CARD_URL_BASE: Final = "/resolume_card"
