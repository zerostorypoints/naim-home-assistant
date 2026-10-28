"""Stream format sensors: quality, codec, sample rate, bit depth, bitrate, service."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfDataRate, UnitOfFrequency
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import ACTIVE_TRANSPORTS, NaimInput, NaimState, as_int
from .coordinator import NaimConfigEntry
from .entity import NaimEntity

PARALLEL_UPDATES = 0

QUALITY_OPTIONS = ["hi_res", "cd", "lossless", "lossy", "dsd"]
LOSSLESS_CODECS = ("flac", "alac", "wav", "aiff", "pcm", "lpcm")


def _active(state: NaimState) -> bool:
    return state.is_on and state.transport in ACTIVE_TRANSPORTS


def _number(state: NaimState, key: str) -> int:
    """A /nowplaying number; 0 when it is missing or the streamer is not playing."""
    return (as_int(state.playing.get(key)) or 0) if _active(state) else 0


def codec(state: NaimState) -> str | None:
    return (state.playing.get("codec") or None) if _active(state) else None


def sample_rate(state: NaimState) -> float | None:
    rate = _number(state, "sampleRate")
    return round(rate / 1000, 1) if rate else None


def bit_depth(state: NaimState) -> int | None:
    return _number(state, "bitDepth") or None


def bitrate(state: NaimState) -> float | None:
    rate = _number(state, "bitRate")
    return round(rate / 1000) if rate else None


def quality(state: NaimState) -> str | None:
    """Classify the stream: hi_res, cd, lossless, lossy or dsd.

    An external input reports a rate and depth but no codec, and gets no class: what reaches it
    is not known.
    """
    name = (codec(state) or "").lower()
    if not name:
        return None
    rate = _number(state, "sampleRate")
    bits = _number(state, "bitDepth")
    if "dsd" in name:
        return "dsd"
    # A lossy stream's depth is the decoder's output (AAC radio reports 32 bit): not Hi-Res.
    if not any(c in name for c in LOSSLESS_CODECS):
        return "lossy"
    if bits > 16 or rate > 48000:
        return "hi_res"
    if bits == 16 and rate in (44100, 48000):
        return "cd"
    return "lossless"


def streaming_service(state: NaimState, inputs: list[NaimInput]) -> str | None:
    """The network source playing (Spotify, Qobuz, Internet Radio, ...), by its input's name."""
    if not _active(state):
        return None
    current = next((i for i in inputs if i.ussi == state.source), None)
    return current.name if current and current.streaming else None


@dataclass(frozen=True, kw_only=True)
class NaimSensorDescription(SensorEntityDescription):
    value_fn: Callable[[NaimState, list[NaimInput]], Any]


SENSORS: tuple[NaimSensorDescription, ...] = (
    NaimSensorDescription(
        key="audio_quality",
        translation_key="audio_quality",
        device_class=SensorDeviceClass.ENUM,
        options=QUALITY_OPTIONS,
        value_fn=lambda state, _: quality(state),
    ),
    NaimSensorDescription(
        key="codec", translation_key="codec", value_fn=lambda state, _: codec(state)
    ),
    NaimSensorDescription(
        key="sample_rate",
        translation_key="sample_rate",
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.KILOHERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda state, _: sample_rate(state),
    ),
    NaimSensorDescription(
        key="bit_depth",
        translation_key="bit_depth",
        native_unit_of_measurement="bit",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda state, _: bit_depth(state),
    ),
    NaimSensorDescription(
        key="bitrate",
        translation_key="bitrate",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.KILOBITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda state, _: bitrate(state),
    ),
    NaimSensorDescription(
        key="streaming_service",
        translation_key="streaming_service",
        value_fn=streaming_service,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NaimConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(NaimSensor(entry.runtime_data, d) for d in SENSORS)


class NaimSensor(NaimEntity, SensorEntity):
    entity_description: NaimSensorDescription

    def __init__(self, coordinator, description: NaimSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data, self.coordinator.inputs)
