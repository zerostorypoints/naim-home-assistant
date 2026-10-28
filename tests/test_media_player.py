"""Media player, sensor and coordinator tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from homeassistant.components.media_player import (
    ATTR_INPUT_SOURCE,
    ATTR_MEDIA_VOLUME_LEVEL,
    ATTR_MEDIA_VOLUME_MUTED,
    DOMAIN as MP_DOMAIN,
    SERVICE_SELECT_SOURCE,
    MediaPlayerEntityFeature,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_SUPPORTED_FEATURES,
    SERVICE_MEDIA_NEXT_TRACK,
    SERVICE_MEDIA_PAUSE,
    SERVICE_MEDIA_PLAY,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    SERVICE_VOLUME_MUTE,
    SERVICE_VOLUME_SET,
    SERVICE_VOLUME_UP,
    STATE_OFF,
    STATE_ON,
    STATE_PLAYING,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.naim_streaming.api import NaimConnectionError, NaimError, NaimState
from custom_components.naim_streaming.const import (
    CONF_DEVICE,
    CONF_HIDDEN_SOURCES,
    CONF_MAX_VOLUME,
    CONF_SOURCES,
    DOMAIN,
)
from custom_components.naim_streaming.diagnostics import async_get_config_entry_diagnostics
from custom_components.naim_streaming.sensor import quality

from .conftest import DEVICE, FAVORITES, HOST, NOW_PLAYING_SPOTIFY, UNIQUE_ID, playing_state

PLAYER = "media_player.uniti_star"


async def setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


async def call(hass: HomeAssistant, service: str, **data) -> None:
    await hass.services.async_call(
        MP_DOMAIN, service, {ATTR_ENTITY_ID: PLAYER, **data}, blocking=True
    )


async def test_playing(hass: HomeAssistant, config_entry, client) -> None:
    await setup(hass, config_entry)
    state = hass.states.get(PLAYER)
    assert state.state == STATE_PLAYING
    assert state.attributes["media_title"] == "Track title"
    assert state.attributes["media_artist"] == "Artist"
    assert state.attributes["media_album_name"] == "Album"
    assert state.attributes["app_name"] == "Spotify"
    assert state.attributes["source"] == "Spotify"
    assert state.attributes["volume_level"] == 0.3
    assert state.attributes["is_volume_muted"] is False
    assert state.attributes["media_duration"] == 334
    assert state.attributes["media_position"] == 3
    assert state.attributes["entity_picture"].startswith("/api/media_player_proxy/")
    # Selectable inputs only: TIDAL starts from the TIDAL app.
    assert state.attributes["source_list"] == [
        "Turntable",
        "Digital 1",
        "Internet Radio",
        "Spotify",
        "CD Player",
    ]

    assert hass.states.get("sensor.uniti_star_codec").state == "FLAC"
    assert hass.states.get("sensor.uniti_star_audio_quality").state == "lossless"
    assert hass.states.get("sensor.uniti_star_bitrate").state == "768"
    assert hass.states.get("sensor.uniti_star_sample_rate").state == "unknown"
    assert hass.states.get("binary_sensor.uniti_star_network").state == STATE_ON
    assert hass.states.get("sensor.uniti_star_streaming_service").state == "Spotify"


async def test_restrictions_set_the_features(hass: HomeAssistant, config_entry, client) -> None:
    await setup(hass, config_entry)
    features = MediaPlayerEntityFeature(hass.states.get(PLAYER).attributes[ATTR_SUPPORTED_FEATURES])
    # restrictResume "2" while playing.
    assert not features & MediaPlayerEntityFeature.PLAY
    assert features & MediaPlayerEntityFeature.PAUSE
    assert features & MediaPlayerEntityFeature.NEXT_TRACK

    paused = copy.deepcopy(NOW_PLAYING_SPOTIFY)
    paused.update(transportState="3", restrictResume="0", restrictPause="1", restrictSkipPrev="16")
    client.get_state.return_value = playing_state(playing=paused)
    await refresh(hass, config_entry)
    state = hass.states.get(PLAYER)
    features = MediaPlayerEntityFeature(state.attributes[ATTR_SUPPORTED_FEATURES])
    assert state.state == "paused"
    assert features & MediaPlayerEntityFeature.PLAY
    assert not features & MediaPlayerEntityFeature.PAUSE
    assert not features & MediaPlayerEntityFeature.PREVIOUS_TRACK


async def test_external_input(hass: HomeAssistant, config_entry, client) -> None:
    """An analogue input plays with no track and no position (transportPosition -1)."""
    client.get_state.return_value = playing_state(
        playing={
            "source": "inputs/ana1",
            "bitRate": "1536000",
            "mimeType": "audio/x-wav",
            "transportPosition": "-1",
            "transportState": "2",
            "live": "1",
            "sampleRate": "48000",
            "bitDepth": "16",
        },
    )
    await setup(hass, config_entry)
    state = hass.states.get(PLAYER)
    assert state.state == STATE_PLAYING
    assert state.attributes["source"] == "Turntable"
    assert "media_title" not in state.attributes
    assert "media_position" not in state.attributes
    assert hass.states.get("sensor.uniti_star_streaming_service").state == "unknown"
    assert hass.states.get("sensor.uniti_star_sample_rate").state == "48.0"
    assert hass.states.get("sensor.uniti_star_audio_quality").state == "unknown"


async def test_buffering(hass: HomeAssistant, config_entry, client) -> None:
    client.get_state.return_value = playing_state(
        playing={**NOW_PLAYING_SPOTIFY, "transportState": "8", "transportPosition": "-1"}
    )
    await setup(hass, config_entry)
    assert hass.states.get(PLAYER).state == "buffering"


async def test_standby_is_off(hass: HomeAssistant, config_entry, client) -> None:
    await setup(hass, config_entry)
    client.get_state.return_value = NaimState(reachable=True, power="lona")
    await refresh(hass, config_entry)
    state = hass.states.get(PLAYER)
    assert state.state == STATE_OFF
    assert "source_list" not in state.attributes
    assert hass.states.get("binary_sensor.uniti_star_network").state == STATE_ON
    assert hass.states.get("sensor.uniti_star_codec").state == "unknown"

    with pytest.raises(ServiceValidationError):
        await call(hass, SERVICE_VOLUME_SET, **{ATTR_MEDIA_VOLUME_LEVEL: 0.2})


async def test_not_responding_is_off(hass: HomeAssistant, config_entry, client) -> None:
    await setup(hass, config_entry)
    client.get_state.side_effect = NaimConnectionError("timeout")
    await refresh(hass, config_entry)
    assert hass.states.get(PLAYER).state == STATE_OFF
    assert hass.states.get("binary_sensor.uniti_star_network").state == STATE_OFF
    with pytest.raises(HomeAssistantError):
        await call(hass, SERVICE_TURN_ON)


async def test_unexpected_answer_keeps_the_last_state(
    hass: HomeAssistant, config_entry, client
) -> None:
    await setup(hass, config_entry)
    client.get_state.side_effect = NaimError("bad JSON")
    await refresh(hass, config_entry)
    assert hass.states.get(PLAYER).state == STATE_PLAYING


async def test_setup_retries_when_not_responding(hass: HomeAssistant, config_entry, client) -> None:
    client.get_device_info.side_effect = NaimConnectionError("timeout")
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_starts_off_when_seen_before(hass: HomeAssistant, client) -> None:
    """Switched off at the mains after a restart: the cached device and inputs are used."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=UNIQUE_ID,
        data={
            "host": HOST,
            CONF_DEVICE: {
                "unique_id": UNIQUE_ID,
                "name": "Uniti Star",
                "model": "Uniti Star",
                "manufacturer": "Naim",
                "firmware": "3.13.0.5828",
            },
            CONF_SOURCES: {"inputs/cd": {"name": "CD Player", "selectable": True}},
        },
    )
    client.get_device_info.side_effect = NaimConnectionError("timeout")
    client.get_state.side_effect = NaimConnectionError("timeout")
    await setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(PLAYER).state == STATE_OFF
    assert [i.ussi for i in entry.runtime_data.inputs] == ["inputs/cd"]


async def test_inputs_cached_in_the_entry(hass: HomeAssistant, config_entry, client) -> None:
    await setup(hass, config_entry)
    cached = config_entry.data[CONF_SOURCES]
    assert cached["inputs/ana1"] == {"name": "Turntable", "selectable": True, "streaming": False}
    assert cached["inputs/tidal"] == {"name": "TIDAL", "selectable": False, "streaming": True}
    assert config_entry.data[CONF_DEVICE]["unique_id"] == DEVICE.unique_id


async def test_commands(hass: HomeAssistant, config_entry, client) -> None:
    await setup(hass, config_entry)

    # The streamer has applied it by the refresh that follows the command.
    client.get_state.return_value = playing_state(volume=45)
    await call(hass, SERVICE_VOLUME_SET, **{ATTR_MEDIA_VOLUME_LEVEL: 0.45})
    client.set_volume.assert_awaited_once_with(45)
    assert hass.states.get(PLAYER).attributes["volume_level"] == 0.45

    await call(hass, SERVICE_VOLUME_UP)
    client.set_volume.assert_awaited_with(46)

    await call(hass, SERVICE_VOLUME_MUTE, **{ATTR_MEDIA_VOLUME_MUTED: True})
    client.set_mute.assert_awaited_once_with(True)

    await call(hass, SERVICE_MEDIA_PAUSE)
    client.control.assert_awaited_with("pause")
    await call(hass, SERVICE_MEDIA_NEXT_TRACK)
    client.control.assert_awaited_with("next")

    await call(hass, SERVICE_SELECT_SOURCE, **{ATTR_INPUT_SOURCE: "Turntable"})
    client.select_input.assert_awaited_once_with("inputs/ana1")

    await call(hass, SERVICE_TURN_OFF)
    client.power_standby.assert_awaited_once()


async def test_events_update_the_player(hass: HomeAssistant, config_entry, client) -> None:
    await setup(hass, config_entry)
    coordinator = config_entry.runtime_data

    await coordinator._async_handle_event("levels/room", {"volume": "43"})
    await coordinator._async_handle_event("levels/room", {"mute": "1"})
    state = hass.states.get(PLAYER)
    assert state.attributes["volume_level"] == 0.43
    assert state.attributes["is_volume_muted"] is True

    await coordinator._async_handle_event("nowplaying", {"transportState": "3"})
    assert hass.states.get(PLAYER).state == "paused"

    # An event that names the node without its fields: now playing is read again.
    client.get_now_playing.return_value = {**NOW_PLAYING_SPOTIFY, "title": "Next track"}
    await coordinator._async_handle_event("nowplaying", {})
    assert hass.states.get(PLAYER).attributes["media_title"] == "Next track"
    client.get_state.assert_awaited_once()  # only the setup's refresh


async def test_position_events_only_on_a_jump(hass: HomeAssistant, config_entry, client) -> None:
    """The Naim sends its position every second; only a seek or restart is written."""
    client.get_state.return_value = playing_state(position_at=dt_util.utcnow())
    await setup(hass, config_entry)
    coordinator = config_entry.runtime_data
    written = hass.states.get(PLAYER).last_updated

    # 3021 ms at setup: a second later, about 4021 ms is expected.
    await coordinator._async_handle_event("nowplaying", {"transportPosition": "4000"})
    assert hass.states.get(PLAYER).last_updated == written

    await coordinator._async_handle_event("nowplaying", {"transportPosition": "0"})
    state = hass.states.get(PLAYER)
    assert state.attributes["media_position"] == 0
    assert state.last_updated != written


async def test_power_event_reads_everything(hass: HomeAssistant, config_entry, client) -> None:
    await setup(hass, config_entry)
    client.get_state.return_value = NaimState(reachable=True, power="lona")
    await config_entry.runtime_data._async_handle_event("power", {"system": "lona"})
    await hass.async_block_till_done()
    assert hass.states.get(PLAYER).state == STATE_OFF


async def test_other_events_are_ignored(hass: HomeAssistant, config_entry, client) -> None:
    await setup(hass, config_entry)
    await config_entry.runtime_data._async_handle_event("system/status", {"hostCpuTemp": "1"})
    await config_entry.runtime_data._async_handle_event("levels", {"volume": "99"})
    assert hass.states.get(PLAYER).attributes["volume_level"] == 0.3


async def test_turn_on_from_standby(hass: HomeAssistant, config_entry, client) -> None:
    client.get_state.return_value = NaimState(reachable=True, power="lona")
    await setup(hass, config_entry)
    client.get_state.return_value = playing_state()
    await call(hass, SERVICE_TURN_ON)
    client.power_on.assert_awaited_once()
    assert hass.states.get(PLAYER).state == STATE_PLAYING


async def test_play_needs_no_resume_restriction(hass: HomeAssistant, config_entry, client) -> None:
    """Play is sent as play; HA refuses it itself only while the feature is off."""
    paused = {**NOW_PLAYING_SPOTIFY, "transportState": "3", "restrictResume": "0"}
    client.get_state.return_value = playing_state(playing=paused)
    await setup(hass, config_entry)
    await call(hass, SERVICE_MEDIA_PLAY)
    client.control.assert_awaited_with("play")


async def test_unknown_source(hass: HomeAssistant, config_entry, client) -> None:
    await setup(hass, config_entry)
    with pytest.raises(ServiceValidationError):
        await call(hass, SERVICE_SELECT_SOURCE, **{ATTR_INPUT_SOURCE: "Phono"})


async def test_rejected_command(hass: HomeAssistant, config_entry, client) -> None:
    await setup(hass, config_entry)
    client.control.side_effect = NaimError("returned 500")
    with pytest.raises(HomeAssistantError):
        await call(hass, SERVICE_MEDIA_PAUSE)


async def test_volume_limit_and_hidden_inputs(hass: HomeAssistant, client) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Uniti Star",
        unique_id=UNIQUE_ID,
        data={"host": HOST},
        options={CONF_MAX_VOLUME: 40, CONF_HIDDEN_SOURCES: ["inputs/cd", "inputs/dig1"]},
    )
    await setup(hass, entry)
    assert hass.states.get(PLAYER).attributes["source_list"] == [
        "Turntable",
        "Internet Radio",
        "Spotify",
    ]
    await call(hass, SERVICE_VOLUME_SET, **{ATTR_MEDIA_VOLUME_LEVEL: 0.9})
    client.set_volume.assert_awaited_once_with(40)


@pytest.mark.parametrize(
    ("codec", "rate", "bits", "expected"),
    [
        ("FLAC", None, None, "lossless"),
        ("FLAC", 44100, 16, "cd"),
        ("FLAC", 96000, 24, "hi_res"),
        ("MP3", 44100, 16, "lossy"),
        ("AAC", None, None, "lossy"),
        # AAC radio reports the decoder's 32 bit.
        ("AAC", 44100, 32, "lossy"),
        ("DSD64", 2822400, 1, "dsd"),
        (None, None, None, None),
    ],
)
def test_quality(codec, rate, bits, expected) -> None:
    playing = {**NOW_PLAYING_SPOTIFY, "codec": codec, "sampleRate": rate, "bitDepth": bits}
    assert quality(playing_state(playing=playing)) == expected


# The shape of a Uniti Star's /nowplaying on a radio favourite.
RADIO_PLAYING = {
    "source": "inputs/radio",
    "station": "Station Two",
    "title": "A song",
    "artistName": "Artist",
    "codec": "AAC",
    "bitRate": "317907",
    "sampleRate": "44100",
    "bitDepth": "32",
    "transportState": "2",
    "live": "1",
    "duration": "0",
    "restrictPause": "128",
    "restrictSkipNext": "128",
    "restrictSkipPrev": "128",
    "restrictSeek": "128",
    "restrictResume": "0",
    "restrictStop": "0",
}


async def test_radio_favorites(hass: HomeAssistant, config_entry, client) -> None:
    client.get_radio_favorites.return_value = FAVORITES
    await setup(hass, config_entry)
    state = hass.states.get(PLAYER)
    assert state.attributes["source_list"][-2:] == ["Station One", "Station Two"]

    await call(hass, SERVICE_SELECT_SOURCE, **{ATTR_INPUT_SOURCE: "Station One"})
    client.play_radio.assert_awaited_once_with(FAVORITES["Station One"])
    client.select_input.assert_not_called()


async def test_radio_favorite_playing(hass: HomeAssistant, config_entry, client) -> None:
    """The source is the station; a station gives only stop."""
    client.get_radio_favorites.return_value = FAVORITES
    client.get_state.return_value = playing_state(playing=dict(RADIO_PLAYING))
    await setup(hass, config_entry)
    state = hass.states.get(PLAYER)
    assert state.attributes["source"] == "Station Two"
    assert state.attributes["app_name"] == "Internet Radio"
    features = MediaPlayerEntityFeature(state.attributes[ATTR_SUPPORTED_FEATURES])
    assert features & MediaPlayerEntityFeature.STOP
    assert not features & (MediaPlayerEntityFeature.PAUSE | MediaPlayerEntityFeature.NEXT_TRACK)
    assert hass.states.get("sensor.uniti_star_audio_quality").state == "lossy"
    assert hass.states.get("sensor.uniti_star_streaming_service").state == "Internet Radio"


async def test_radio_outside_favorites_shows_the_input(
    hass: HomeAssistant, config_entry, client
) -> None:
    client.get_radio_favorites.return_value = FAVORITES
    client.get_state.return_value = playing_state(
        playing={**RADIO_PLAYING, "station": "Not a favourite"}
    )
    await setup(hass, config_entry)
    assert hass.states.get(PLAYER).attributes["source"] == "Internet Radio"


async def test_input_wins_over_a_favorite_of_the_same_name(
    hass: HomeAssistant, config_entry, client
) -> None:
    client.get_radio_favorites.return_value = {"Spotify": "inputs/radio/c3BvdGlmeQ"}
    await setup(hass, config_entry)
    assert hass.states.get(PLAYER).attributes["source_list"].count("Spotify") == 1
    await call(hass, SERVICE_SELECT_SOURCE, **{ATTR_INPUT_SOURCE: "Spotify"})
    client.select_input.assert_awaited_once_with("inputs/spotify")
    client.play_radio.assert_not_called()


async def test_favorites_read_sparingly(hass: HomeAssistant, config_entry, client) -> None:
    await setup(hass, config_entry)
    await refresh(hass, config_entry)
    await refresh(hass, config_entry)
    assert client.get_radio_favorites.await_count == 1
    # Power on (or standby) reads them again.
    await config_entry.runtime_data._async_handle_event("power", {"system": "on"})
    await hass.async_block_till_done()
    assert client.get_radio_favorites.await_count == 2


async def test_new_favorite_is_read_on_select(hass: HomeAssistant, config_entry, client) -> None:
    await setup(hass, config_entry)
    client.get_radio_favorites.return_value = FAVORITES
    await call(hass, SERVICE_SELECT_SOURCE, **{ATTR_INPUT_SOURCE: "Station Two"})
    client.play_radio.assert_awaited_once_with(FAVORITES["Station Two"])


async def test_favorites_not_read_in_standby(hass: HomeAssistant, config_entry, client) -> None:
    client.get_state.return_value = NaimState(reachable=True, power="lona")
    await setup(hass, config_entry)
    client.get_radio_favorites.assert_not_called()


async def test_favorites_read_failure_keeps_the_list(
    hass: HomeAssistant, config_entry, client
) -> None:
    client.get_radio_favorites.return_value = FAVORITES
    await setup(hass, config_entry)
    client.get_radio_favorites.side_effect = NaimError("returned 500")
    await config_entry.runtime_data.async_read_favorites(force=True)
    assert config_entry.runtime_data.radio_favorites == FAVORITES


async def test_diagnostics_and_unload(hass: HomeAssistant, config_entry, client) -> None:
    await setup(hass, config_entry)
    diag = await async_get_config_entry_diagnostics(hass, config_entry)
    assert diag["device"]["model"] == "Uniti Star"
    assert diag["state"]["power"] == "on"
    assert {
        "ussi": "inputs/ana1",
        "name": "Turntable",
        "selectable": True,
        "streaming": False,
    } in diag["inputs"]
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_translations_and_icons_match_entities() -> None:
    root = Path(__file__).parent.parent / "custom_components" / DOMAIN
    icons = json.loads((root / "icons.json").read_text())["entity"]
    for lang in ("en", "pl"):
        names = json.loads((root / "translations" / f"{lang}.json").read_text())["entity"]
        for platform in ("sensor", "binary_sensor"):
            assert set(icons[platform]) == set(names[platform]), (lang, platform)
