"""Client for the local HTTP API of Naim network streamers.

Naim's streaming platform (Uniti Atom, Star and Nova, Mu-so 2nd generation, NDX 2, ND5 XS 2 and
others set up with the Naim app) answers JSON on port 15081, the API the Naim app uses. Naim does
not document it. Read on a Uniti Star, firmware 3.13:

    GET  /system, /network            firmware (appVer); the name given in the Naim app (hostname)
    GET  /power                       {"system": "on" | "lona" | "off"}; lona is network standby
    PUT  /power?system=on|lona        power on, network standby
    GET  /levels/room                 {"volume": "0"-"100", "mute": "0" | "1", ...}
    PUT  /levels/room?volume=<n>      set the volume; ?mute=1|0 mutes
    GET  /nowplaying                  source (an input's ussi), transportState, track, bitRate,
                                      sampleRate, bitDepth, codec, restrict<Action> flags
    GET  /nowplaying?cmd=<cmd>        play, pause, stop, next, prev
    GET  /inputs                      {"children": [{"ussi": "inputs/ana1", "name", "alias",
                                      "disabled", "selectable", ...}]}
    GET  /<ussi>?cmd=select           switch to an input
    GET  /notify                      Server-Sent Events: each change as
                                      {"ussi": "levels/room", "parameters": {"volume": "43"}}

Every value is a string: "35", "1", "-1". A restrict flag is a reason code, "0" when allowed
("2", "16", "64" seen). A transportPosition of "-1" means none; live is "1" on Spotify too.
An event's parameters are the changed fields of the node its ussi names, with the names a GET
of that node gives; an event without parameters says the node changed in some other way.

The streaming board is StreamUnlimited's stream800 (hardwareType), so the Stream SDK answers on
port 80 as on Hegel's and T+A's streamers. It is read only for the streamer's id.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

PORT = 15081
EVENT_READ_TIMEOUT = 30

POWER_ON = "on"
POWER_STANDBY = "lona"

# Transport states in /nowplaying: 0 and 1 stopped (1 right after a stop command), 2 playing,
# 3 paused; 8 is seen between tracks and while a stream starts (inference: buffering).
TRANSPORT_PLAYING = 2
TRANSPORT_PAUSED = 3
TRANSPORT_BUFFERING = 8
ACTIVE_TRANSPORTS = (TRANSPORT_PLAYING, TRANSPORT_PAUSED, TRANSPORT_BUFFERING)

# {"id": "np800-<uuid>", "host": "Uniti-Star-123456.local.", "name": <the name in the Naim app>}.
# The id is also the uuid the streamer announces over mDNS.
SDK_MEMBER = "systemmanager:systemMember"


class NaimError(Exception):
    """Base error."""


class NaimConnectionError(NaimError):
    """The streamer did not answer."""


def as_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def as_flag(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


@dataclass(slots=True)
class NaimDeviceInfo:
    """Static facts about the streamer."""

    unique_id: str
    name: str
    model: str
    manufacturer: str
    firmware: str | None


@dataclass(slots=True)
class NaimInput:
    """One input as /inputs lists it."""

    ussi: str
    name: str
    selectable: bool = True


@dataclass(slots=True)
class NaimState:
    """Current state of the streamer."""

    reachable: bool = False
    power: str | None = None
    volume: int | None = None
    muted: bool | None = None
    playing: dict[str, Any] = field(default_factory=dict)
    position_at: datetime | None = None

    @property
    def is_on(self) -> bool:
        """True when the streamer is reachable and not in standby."""
        return self.reachable and self.power == POWER_ON

    @property
    def source(self) -> str | None:
        """The ussi of the current input, e.g. inputs/spotify."""
        return self.playing.get("source") or None

    @property
    def transport(self) -> int | None:
        return as_int(self.playing.get("transportState"))

    def restricted(self, key: str) -> bool:
        """True when /nowplaying forbids an action, e.g. restricted("SkipNext")."""
        return bool(as_int(self.playing.get(f"restrict{key}")))

    def expected_position_ms(self, now: datetime) -> int | None:
        """Where the track should be now, counting on from the last position read."""
        position = as_int(self.playing.get("transportPosition"))
        if position is None or position < 0 or self.position_at is None:
            return None
        if self.transport != TRANSPORT_PLAYING:
            return position
        return position + round((now - self.position_at).total_seconds() * 1000)

    def apply(self, ussi: str, parameters: dict[str, Any]) -> bool:
        """Apply an event's changed fields. Return True when the node is one this state holds."""
        if ussi == "power":
            if system := parameters.get("system"):
                self.power = system
        elif ussi == "levels/room":
            if "volume" in parameters:
                self.volume = as_int(parameters["volume"])
            if "mute" in parameters:
                self.muted = as_flag(parameters["mute"])
        elif ussi == "nowplaying":
            self.playing = {**self.playing, **parameters}
            if "transportPosition" in parameters:
                self.position_at = datetime.now(UTC)
        else:
            return False
        return True


def model_from_host(host: str | None, serial: str | None) -> str | None:
    """The model in the streamer's host name, e.g. Uniti Star for Uniti-Star-123456.local.

    Neither API names the model: productName is "Naim Network Player" on every one, and /system
    gives a number. mDNS has it (model=Uniti Star); this is for a streamer added by address.
    """
    if not host:
        return None
    name = host.split(".", 1)[0]
    if serial and name.endswith(f"-{serial}"):
        name = name[: -len(serial) - 1]
    return name.replace("-", " ").strip() or None


class NaimClient:
    """Async client for one streamer."""

    def __init__(self, host: str, session: aiohttp.ClientSession, timeout: float = 5) -> None:
        self.host = host
        self._session = session
        self._timeout = timeout
        self._base = f"http://{host}:{PORT}"

    async def _request(self, method: str, url: str, *, params: dict[str, Any] | None = None) -> Any:
        try:
            async with self._session.request(
                method,
                url,
                params=params,
                timeout=aiohttp.ClientTimeout(total=self._timeout),
            ) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    raise NaimError(f"{method} {url} returned {resp.status}: {text[:200]}")
                if not text:
                    return None
                try:
                    return await resp.json(content_type=None)
                except ValueError as err:
                    raise NaimError(f"{method} {url} did not answer JSON: {text[:200]}") from err
        except (TimeoutError, aiohttp.ClientError) as err:
            raise NaimConnectionError(f"{self.host} did not answer: {err}") from err

    async def get(self, path: str, **params: Any) -> Any:
        return await self._request("GET", f"{self._base}/{path}", params=params or None)

    async def put(self, path: str, **params: Any) -> None:
        await self._request("PUT", f"{self._base}/{path}", params=params)

    async def _get_dict(self, path: str) -> dict[str, Any]:
        data = await self.get(path)
        if not isinstance(data, dict):
            raise NaimError(f"/{path} answered {data!r}")
        return data

    # High-level calls

    async def get_device_info(self) -> NaimDeviceInfo:
        """Read identity and firmware."""
        system = await self._get_dict("system")
        member = await self._sdk_member()
        unique_id = member.get("id")
        if not unique_id:
            raise NaimError("The streamer reported no system member id")
        model = model_from_host(member.get("host"), system.get("hardwareSerial")) or "Naim"
        return NaimDeviceInfo(
            unique_id=unique_id,
            name=member.get("name") or model,
            model=model,
            manufacturer="Naim",
            firmware=system.get("appVer") or system.get("version"),
        )

    async def _sdk_get(self, path: str) -> Any:
        """Read a Stream SDK node on port 80, unwrapped; None when it is not there.

        Values are typed, e.g. {"type": "string_", "string_": "Naim Network Player"}.
        """
        try:
            data = await self._request(
                "GET", f"http://{self.host}/api/getData", params={"path": path, "roles": "value"}
            )
        except NaimError:
            return None
        value = data[0] if isinstance(data, list) and data else None
        if isinstance(value, dict) and isinstance(value.get("type"), str):
            return value.get(value["type"], value)
        return value

    async def _sdk_member(self) -> dict[str, Any]:
        member = await self._sdk_get(SDK_MEMBER)
        if not isinstance(member, dict):
            return {}
        member = member.get("systemMember", member)
        return member if isinstance(member, dict) else {}

    async def get_inputs(self) -> list[NaimInput]:
        """Inputs in the streamer's order. Disabled inputs (hidden in the Naim app) are left out."""
        data = await self._get_dict("inputs")
        inputs: list[NaimInput] = []
        for child in data.get("children") or []:
            ussi = child.get("ussi")
            if not ussi or as_flag(child.get("disabled")):
                continue
            name = (child.get("alias") or "").strip() or child.get("name") or ussi
            inputs.append(
                NaimInput(ussi=ussi, name=name, selectable=as_flag(child.get("selectable", True)))
            )
        return inputs

    async def get_state(self) -> NaimState:
        """Read the full state. Raises NaimConnectionError when the streamer does not answer."""
        power = await self._get_dict("power")
        state = NaimState(reachable=True, power=power.get("system") or power.get("state"))
        if not state.is_on:
            return state
        levels = await self._get_dict("levels/room")
        state.volume = as_int(levels.get("volume"))
        state.muted = as_flag(levels.get("mute")) if "mute" in levels else None
        state.playing = await self.get_now_playing()
        state.position_at = datetime.now(UTC)
        return state

    async def get_now_playing(self) -> dict[str, Any]:
        return await self._get_dict("nowplaying")

    async def power_on(self) -> None:
        await self.put("power", system=POWER_ON)

    async def power_standby(self) -> None:
        await self.put("power", system=POWER_STANDBY)

    async def set_volume(self, volume: int) -> None:
        await self.put("levels/room", volume=int(volume))

    async def set_mute(self, mute: bool) -> None:
        await self.put("levels/room", mute=1 if mute else 0)

    async def select_input(self, ussi: str) -> None:
        await self.get(ussi, cmd="select")

    async def control(self, command: str) -> None:
        """Send a transport command: play, pause, stop, next, prev."""
        await self.get("nowplaying", cmd=command)

    async def events(self) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Yield (ussi, parameters) for each change the streamer pushes, until the stream ends.

        The streamer sends a heartbeat (an empty ussi) every few seconds, so a read that waits
        longer than EVENT_READ_TIMEOUT means the connection is gone.
        """
        try:
            async with self._session.get(
                f"{self._base}/notify",
                timeout=aiohttp.ClientTimeout(
                    total=None, connect=self._timeout, sock_read=EVENT_READ_TIMEOUT
                ),
            ) as resp:
                if resp.status >= 400:
                    raise NaimError(f"/notify returned {resp.status}")
                async for line in resp.content:
                    if not line.startswith(b"data:"):
                        continue
                    try:
                        data = json.loads(line[5:])
                    except ValueError:
                        _LOGGER.debug("Unreadable event from %s: %r", self.host, line)
                        continue
                    if isinstance(data, dict) and (ussi := data.get("ussi")):
                        parameters = data.get("parameters")
                        yield ussi, parameters if isinstance(parameters, dict) else {}
        except (TimeoutError, aiohttp.ClientError) as err:
            raise NaimConnectionError(f"{self.host} event stream ended: {err}") from err


async def async_probe(host: str, session: aiohttp.ClientSession) -> NaimDeviceInfo:
    """Connect once and return the device info. Used by the config flow."""
    client = NaimClient(host, session)
    async with asyncio.timeout(15):
        return await client.get_device_info()
