"""Constants for the Resolume Arena integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "resolume"
MANUFACTURER: Final = "Resolume"

DEFAULT_PORT: Final = 8080

# Seconds between REST resyncs (safety net; live updates come over the
# WebSocket push channel).
UPDATE_INTERVAL: Final = 30
