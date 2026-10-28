"""Constants for the Naim Streaming integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "naim_streaming"

CONF_DEVICE: Final = "device"
CONF_MAX_VOLUME: Final = "max_volume"
CONF_HIDDEN_SOURCES: Final = "hidden_sources"
CONF_SOURCES: Final = "sources"
DEFAULT_MAX_VOLUME: Final = 100

# Full refresh as a safety net; changes arrive through the event stream in between.
SCAN_INTERVAL: Final = timedelta(seconds=30)
# How long to wait before opening the event stream again.
RECONNECT_INTERVAL: Final = 10
# Inputs change only when someone renames or disables one in the Naim app.
INPUTS_INTERVAL: Final = timedelta(minutes=10)

ZSP_URL: Final = "https://zerostorypoints.com/?utm_source=home-assistant&utm_medium=integration&utm_campaign=naim_streaming"
HIFISYNC_URL: Final = "https://hifisync.com/?utm_source=home-assistant&utm_medium=integration&utm_campaign=naim_streaming"
