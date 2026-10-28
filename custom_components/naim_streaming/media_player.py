"""Media player entity: power, volume, mute, input and playback."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import (
    TRANSPORT_BUFFERING,
    TRANSPORT_PAUSED,
    TRANSPORT_PLAYING,
    NaimError,
    as_int,
)
from .const import CONF_HIDDEN_SOURCES, CONF_MAX_VOLUME, DEFAULT_MAX_VOLUME, DOMAIN
from .coordinator import NaimConfigEntry, NaimCoordinator
from .entity import NaimEntity

PARALLEL_UPDATES = 1

BASE_FEATURES = (
    MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.SELECT_SOURCE
)
# Offered unless /nowplaying restricts them (restrictPause, restrictSkipNext, ...).
TRANSPORT_FEATURES = {
    "Resume": MediaPlayerEntityFeature.PLAY,
    "Pause": MediaPlayerEntityFeature.PAUSE,
    "Stop": MediaPlayerEntityFeature.STOP,
    "SkipNext": MediaPlayerEntityFeature.NEXT_TRACK,
    "SkipPrev": MediaPlayerEntityFeature.PREVIOUS_TRACK,
}
ALL_FEATURES = BASE_FEATURES
for _feature in TRANSPORT_FEATURES.values():
    ALL_FEATURES |= _feature


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NaimConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([NaimMediaPlayer(entry.runtime_data)])


class NaimMediaPlayer(NaimEntity, MediaPlayerEntity):
    """The streamer."""

    _attr_name = None
    _attr_device_class = MediaPlayerDeviceClass.RECEIVER
    _attr_media_image_remotely_accessible = False
    _attr_volume_step = 0.01
    _attr_supported_features = ALL_FEATURES

    def __init__(self, coordinator: NaimCoordinator) -> None:
        super().__init__(coordinator)
        options = coordinator.config_entry.options
        self._max_volume = int(options.get(CONF_MAX_VOLUME, DEFAULT_MAX_VOLUME))
        # Keyed by the input's ussi, e.g. inputs/ana1.
        self._hidden_sources: set[str] = set(options.get(CONF_HIDDEN_SOURCES, []))
        self._update_attrs()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_attrs()
        super()._handle_coordinator_update()

    @property
    def available(self) -> bool:
        # A streamer that does not answer is shown as off, not unavailable.
        return self.coordinator.data is not None

    def _update_attrs(self) -> None:
        state = self.coordinator.data
        if state is None or not state.is_on:
            self._attr_state = MediaPlayerState.OFF
            self._attr_volume_level = None
            self._attr_is_volume_muted = None
            self._attr_source = None
            self._attr_source_list = None
            self._clear_media()
            return

        inputs = self.coordinator.inputs
        self._attr_source_list = [
            i.name for i in inputs if i.selectable and i.ussi not in self._hidden_sources
        ] or None
        current = next((i for i in inputs if i.ussi == state.source), None)
        self._attr_source = current.name if current else None
        self._attr_volume_level = state.volume / 100 if state.volume is not None else None
        self._attr_is_volume_muted = state.muted

        transport = state.transport
        if transport == TRANSPORT_PLAYING:
            self._attr_state = MediaPlayerState.PLAYING
        elif transport == TRANSPORT_PAUSED:
            self._attr_state = MediaPlayerState.PAUSED
        elif transport == TRANSPORT_BUFFERING:
            self._attr_state = MediaPlayerState.BUFFERING
        else:
            self._attr_state = MediaPlayerState.ON
        features = BASE_FEATURES
        for key, feature in TRANSPORT_FEATURES.items():
            if not state.restricted(key):
                features |= feature
        self._attr_supported_features = features

        playing = state.playing
        if not playing.get("title"):
            self._clear_media()
            return
        self._attr_media_content_type = MediaType.MUSIC
        self._attr_media_title = playing.get("title")
        self._attr_media_artist = playing.get("artistName") or None
        self._attr_media_album_name = playing.get("albumName") or None
        artwork = playing.get("artwork") or ""
        self._attr_media_image_url = artwork if artwork.startswith("http") else None
        self._attr_app_name = current.name if current else None
        duration = as_int(playing.get("duration"))
        self._attr_media_duration = round(duration / 1000) if duration else None
        position = as_int(playing.get("transportPosition"))
        # -1 is no position: an external input, or a track that has not started.
        if position is not None and position >= 0 and duration:
            self._attr_media_position = round(position / 1000)
            self._attr_media_position_updated_at = state.position_at
        else:
            self._attr_media_position = None
            self._attr_media_position_updated_at = None

    def _clear_media(self) -> None:
        self._attr_media_content_type = None
        self._attr_media_title = None
        self._attr_media_artist = None
        self._attr_media_album_name = None
        self._attr_media_image_url = None
        self._attr_app_name = None
        self._attr_media_duration = None
        self._attr_media_position = None
        self._attr_media_position_updated_at = None

    async def _call(self, func: Callable[[], Awaitable[None]], *, needs_on: bool = True) -> None:
        state = self.coordinator.data
        if state is None or not state.reachable:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="not_responding",
                translation_placeholders={"host": self.coordinator.client.host},
            )
        if needs_on and not state.is_on:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="turned_off")
        try:
            await func()
        except NaimError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        # The change itself arrives as an event, 0.2 to 1 s later; this covers a lost stream.
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self) -> None:
        await self._call(self.coordinator.client.power_on, needs_on=False)

    async def async_turn_off(self) -> None:
        await self._call(self.coordinator.client.power_standby, needs_on=False)

    async def async_set_volume_level(self, volume: float) -> None:
        level = min(round(volume * 100), self._max_volume)
        await self._call(lambda: self.coordinator.client.set_volume(level))

    async def async_volume_up(self) -> None:
        current = self.coordinator.data.volume or 0
        await self.async_set_volume_level(min(current + 1, 100) / 100)

    async def async_volume_down(self) -> None:
        current = self.coordinator.data.volume or 0
        await self.async_set_volume_level(max(current - 1, 0) / 100)

    async def async_mute_volume(self, mute: bool) -> None:
        await self._call(lambda: self.coordinator.client.set_mute(mute))

    async def async_select_source(self, source: str) -> None:
        ussi = next((i.ussi for i in self.coordinator.inputs if source in (i.name, i.ussi)), None)
        if ussi is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_source",
                translation_placeholders={"source": source},
            )
        await self._call(lambda: self.coordinator.client.select_input(ussi))

    async def async_media_play(self) -> None:
        await self._call(lambda: self.coordinator.client.control("play"))

    async def async_media_pause(self) -> None:
        await self._call(lambda: self.coordinator.client.control("pause"))

    async def async_media_stop(self) -> None:
        await self._call(lambda: self.coordinator.client.control("stop"))

    async def async_media_next_track(self) -> None:
        await self._call(lambda: self.coordinator.client.control("next"))

    async def async_media_previous_track(self) -> None:
        await self._call(lambda: self.coordinator.client.control("prev"))
