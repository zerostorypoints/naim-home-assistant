"""State coordinator: a periodic full refresh plus the events the streamer pushes."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import replace
import logging
import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .api import (
    NaimClient,
    NaimConnectionError,
    NaimDeviceInfo,
    NaimError,
    NaimInput,
    NaimState,
    as_int,
)
from .const import (
    CONF_SOURCES,
    DOMAIN,
    FAVORITES_INTERVAL,
    INPUTS_INTERVAL,
    RECONNECT_INTERVAL,
    SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

POSITION_TOLERANCE_MS = 2000

type NaimConfigEntry = ConfigEntry[NaimCoordinator]


class NaimCoordinator(DataUpdateCoordinator[NaimState]):
    """Holds the streamer state.

    A streamer that does not answer is not an error here: it is reported as a state with
    reachable=False, so entities stay available and show it as off.
    """

    config_entry: NaimConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: NaimConfigEntry,
        client: NaimClient,
        device: NaimDeviceInfo,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {device.name}",
            update_interval=SCAN_INTERVAL,
            always_update=False,
        )
        self.client = client
        self.device = device
        # Inputs as the streamer names them, cached in the entry so they are known while it is off.
        self.inputs: list[NaimInput] = [
            NaimInput(ussi=ussi, **cached)
            for ussi, cached in entry.data.get(CONF_SOURCES, {}).items()
        ]
        self._inputs_read_at: float | None = None
        # Radio favourites, {station name: ussi}, read while the streamer is on.
        self.radio_favorites: dict[str, str] = {}
        self._favorites_read_at: float | None = None
        self._was_reachable = True

    async def _async_update_data(self) -> NaimState:
        try:
            state = await self.client.get_state()
            if state.is_on:
                await self._async_read_inputs()
                await self.async_read_favorites()
        except NaimConnectionError as err:
            if self._was_reachable:
                _LOGGER.info("%s is not responding, reporting it as off: %s", self.device.name, err)
            self._was_reachable = False
            return NaimState(reachable=False)
        except NaimError as err:
            _LOGGER.warning("Unexpected answer from %s: %s", self.device.name, err)
            return self.data or NaimState(reachable=False)
        if not self._was_reachable:
            _LOGGER.info("%s is responding again", self.device.name)
        self._was_reachable = True
        return state

    async def _async_read_inputs(self) -> None:
        now = time.monotonic()
        if (
            self._inputs_read_at is not None
            and now - self._inputs_read_at < INPUTS_INTERVAL.total_seconds()
        ):
            return
        inputs = await self.client.get_inputs()
        self._inputs_read_at = now
        if inputs:
            self._async_set_inputs(inputs)

    @callback
    def _async_set_inputs(self, inputs: list[NaimInput]) -> None:
        self.inputs = inputs
        cached = {
            i.ussi: {"name": i.name, "selectable": i.selectable, "streaming": i.streaming}
            for i in inputs
        }
        if self.config_entry.data.get(CONF_SOURCES) != cached:
            self.hass.config_entries.async_update_entry(
                self.config_entry, data={**self.config_entry.data, CONF_SOURCES: cached}
            )

    async def async_read_favorites(self, force: bool = False) -> None:
        """Read the radio favourites, at most every FAVORITES_INTERVAL unless forced."""
        now = time.monotonic()
        if (
            not force
            and self._favorites_read_at is not None
            and now - self._favorites_read_at < FAVORITES_INTERVAL.total_seconds()
        ):
            return
        try:
            self.radio_favorites = await self.client.get_radio_favorites()
        except NaimConnectionError:
            raise
        except NaimError as err:
            # The list comes from Naim's radio service through the streamer, which may not be
            # ready right after power on. Keep the last list and try again with the next refresh.
            _LOGGER.debug("Could not read the radio favourites of %s: %s", self.device.name, err)
            return
        self._favorites_read_at = now

    async def async_run_event_loop(self) -> None:
        """Follow the streamer's event stream for as long as the entry is loaded."""
        while True:
            try:
                events = self.client.events()
                # Catch anything that changed while there was no stream.
                await self.async_refresh()
                async for ussi, parameters in events:
                    await self._async_handle_event(ussi, parameters)
            except NaimError as err:
                _LOGGER.debug("Event stream of %s ended: %s", self.device.name, err)
                if isinstance(err, NaimConnectionError) and self.data and self.data.reachable:
                    await self.async_refresh()
            await asyncio.sleep(RECONNECT_INTERVAL)

    async def _async_handle_event(self, ussi: str, parameters: dict) -> None:
        if ussi == "power":
            # Standby and power on change what there is to read: read it all.
            self._favorites_read_at = None
            await self.async_refresh()
            return
        if ussi not in ("levels/room", "nowplaying") or self.data is None:
            return
        if ussi == "nowplaying" and parameters.keys() == {"transportPosition"}:
            # Sent every second while playing. Home Assistant counts the position on by itself,
            # so only a jump (a seek, a restart of the track) is worth a state write.
            position = as_int(parameters["transportPosition"])
            expected = self.data.expected_position_ms(dt_util.utcnow())
            if (
                position is not None
                and expected is not None
                and abs(position - expected) < POSITION_TOLERANCE_MS
            ):
                return
        state = replace(self.data, reachable=True)
        if parameters:
            state.apply(ussi, parameters)
        elif ussi == "nowplaying":
            # A new track or service: the event names the node, not what changed in it.
            with contextlib.suppress(NaimError):
                state.apply(ussi, await self.client.get_now_playing())
        if state.is_on and not self.inputs:
            # Turned on for the first time since setup: the inputs are not known yet.
            with contextlib.suppress(NaimError):
                await self._async_read_inputs()
        self._was_reachable = True
        self.async_set_updated_data(state)
