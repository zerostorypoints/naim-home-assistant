"""Fixtures."""

from __future__ import annotations

from collections.abc import Generator
import copy
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.naim_streaming.api import NaimDeviceInfo, NaimInput, NaimState
from custom_components.naim_streaming.const import DOMAIN

HOST = "192.168.1.50"
UNIQUE_ID = "np800-00000000-1111-2222-3333-444444444444"

DEVICE = NaimDeviceInfo(
    unique_id=UNIQUE_ID,
    name="Uniti Star",
    model="Uniti Star",
    manufacturer="Naim",
    firmware="3.13.0.5828",
)

# The shape of a Uniti Star's /inputs: a streaming service is listed but not selectable,
# a disabled input is left out by the client.
INPUTS = [
    NaimInput(ussi="inputs/ana1", name="Turntable", selectable=True),
    NaimInput(ussi="inputs/dig1", name="Digital 1", selectable=True),
    NaimInput(ussi="inputs/radio", name="Internet Radio", selectable=True),
    NaimInput(ussi="inputs/spotify", name="Spotify", selectable=True),
    NaimInput(ussi="inputs/tidal", name="TIDAL", selectable=False),
    NaimInput(ussi="inputs/cd", name="CD Player", selectable=True),
]

# The shape of a Uniti Star's /nowplaying on Spotify: every value a string, restrictResume "2"
# while playing, live "1" although it is a track.
NOW_PLAYING_SPOTIFY: dict[str, Any] = {
    "source": "inputs/spotify",
    "sourceMultiroom": "inputs/none",
    "title": "Track title",
    "artistName": "Artist",
    "albumName": "Album",
    "artwork": "https://i.scdn.co/image/cover",
    "bitRate": "768097",
    "codec": "FLAC",
    "mimeType": "audio/flac",
    "duration": "334040",
    "transportPosition": "3021",
    "transportState": "2",
    "error": "0",
    "live": "1",
    "restrictPause": "0",
    "restrictResume": "2",
    "restrictSeek": "0",
    "restrictSkipNext": "0",
    "restrictSkipPrev": "0",
    "restrictStop": "0",
}

POSITION_AT = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def playing_state(**changes: Any) -> NaimState:
    state = NaimState(
        reachable=True,
        power="on",
        volume=30,
        muted=False,
        playing=copy.deepcopy(NOW_PLAYING_SPOTIFY),
        position_at=POSITION_AT,
    )
    for key, value in changes.items():
        setattr(state, key, value)
    return state


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components in every test."""


@pytest.fixture(autouse=True)
def no_event_loop() -> Generator[None]:
    """No event stream: tests drive events through the coordinator's handler."""
    with patch(
        "custom_components.naim_streaming.coordinator.NaimCoordinator.async_run_event_loop",
        new=AsyncMock(return_value=None),
    ):
        yield


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN, title="Uniti Star", unique_id=UNIQUE_ID, data={"host": HOST}
    )


@pytest.fixture
def client() -> Generator[AsyncMock]:
    """A NaimClient mock, used by the integration setup."""
    with patch("custom_components.naim_streaming.NaimClient", autospec=True) as cls:
        mock = cls.return_value
        mock.host = HOST
        mock.get_device_info.return_value = DEVICE
        mock.get_inputs.return_value = INPUTS
        mock.get_state.return_value = playing_state()
        mock.get_now_playing.return_value = copy.deepcopy(NOW_PLAYING_SPOTIFY)
        yield mock
