"""API client tests."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.naim_streaming.api import (
    NaimClient,
    NaimConnectionError,
    NaimError,
    NaimInput,
    NaimState,
    as_flag,
    as_int,
    model_from_host,
)

from .conftest import NOW_PLAYING_SPOTIFY

BASE = "http://naim:15081"
SDK = "http://naim/api/getData"


def sdk_answer(aioclient_mock: AiohttpClientMocker, path: str, value: object) -> None:
    aioclient_mock.get(SDK, params={"path": path, "roles": "value"}, json=[value])


def test_parsing() -> None:
    assert as_int("35") == 35
    assert as_int("-1") == -1
    assert as_int("") is None
    assert as_int(None) is None
    assert as_flag("1") and not as_flag("0") and as_flag(True)


def test_restrictions_are_reason_codes() -> None:
    state = NaimState(
        reachable=True,
        power="on",
        playing={"restrictResume": "2", "restrictSkipPrev": "16", "restrictPause": "0"},
    )
    assert state.restricted("Resume")
    assert state.restricted("SkipPrev")
    assert not state.restricted("Pause")
    assert not state.restricted("Stop")


async def test_get_state(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{BASE}/power", json={"system": "on", "state": "on"})
    aioclient_mock.get(f"{BASE}/levels/room", json={"volume": "22", "mute": "1"})
    aioclient_mock.get(f"{BASE}/nowplaying", json=NOW_PLAYING_SPOTIFY)

    state = await NaimClient("naim", async_get_clientsession(hass)).get_state()
    assert state.is_on and state.volume == 22 and state.muted is True
    assert state.source == "inputs/spotify"
    assert state.transport == 2


async def test_standby_reads_only_power(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{BASE}/power", json={"system": "lona", "state": "lona"})
    state = await NaimClient("naim", async_get_clientsession(hass)).get_state()
    assert state.reachable and not state.is_on
    assert aioclient_mock.call_count == 1


def test_apply_events() -> None:
    state = NaimState(reachable=True, power="on", volume=42, muted=False, playing={"title": "A"})
    assert state.apply("levels/room", {"volume": "43"})
    assert state.volume == 43 and state.muted is False
    assert state.apply("levels/room", {"mute": "1"})
    assert state.muted is True
    assert state.apply("nowplaying", {"transportState": "2", "source": "inputs/ana1"})
    assert state.playing == {"title": "A", "transportState": "2", "source": "inputs/ana1"}
    assert not state.apply("system/status", {"hostCpuTemp": "4217"})


async def test_events(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """The shape of a Uniti Star's /notify stream, with a heartbeat and an unreadable line."""
    aioclient_mock.get(
        f"{BASE}/notify",
        text=(
            "retry:3000\n\n"
            'id:349\ndata:{"version":"1","ussi":"","id":"0"}\n\n'
            'event:levels\ndata:{"version":"1","ussi":"levels/room","id":"0",'
            '"parameters":{"volume":"43"}}\n\n'
            "data:{not json\n\n"
            'event:nowplaying\ndata:{"version":"1","ussi":"nowplaying","id":"1"}\n\n'
        ),
        headers={"Content-Type": "text/event-stream"},
    )
    client = NaimClient("naim", async_get_clientsession(hass))
    assert [event async for event in client.events()] == [
        ("levels/room", {"volume": "43"}),
        ("nowplaying", {}),
    ]


async def test_events_connection_lost(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{BASE}/notify", exc=TimeoutError())
    client = NaimClient("naim", async_get_clientsession(hass))
    with pytest.raises(NaimConnectionError):
        async for _ in client.events():
            pass


async def test_timeout_is_connection_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{BASE}/power", exc=TimeoutError())
    with pytest.raises(NaimConnectionError):
        await NaimClient("naim", async_get_clientsession(hass)).get_state()


async def test_http_error(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{BASE}/power", status=500, text="boom")
    with pytest.raises(NaimError) as err:
        await NaimClient("naim", async_get_clientsession(hass)).get_state()
    assert not isinstance(err.value, NaimConnectionError)


async def test_not_json(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{BASE}/system", text="<html>router</html>")
    with pytest.raises(NaimError):
        await NaimClient("naim", async_get_clientsession(hass)).get_device_info()


async def test_inputs(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(
        f"{BASE}/inputs",
        json={
            "children": [
                {
                    "name": "Analogue 1",
                    "ussi": "inputs/ana1",
                    "alias": "Turntable",
                    "disabled": "0",
                    "selectable": "1",
                },
                {
                    "name": "Analogue 2",
                    "ussi": "inputs/ana2",
                    "alias": "",
                    "disabled": "1",
                    "selectable": "1",
                },
                {
                    "name": "Digital 1",
                    "ussi": "inputs/dig1",
                    "alias": "",
                    "disabled": "0",
                    "selectable": "1",
                },
                {"name": "Multi-room", "ussi": "inputs/multiroom", "selectable": "0"},
                {"name": "TIDAL", "ussi": "inputs/tidal", "disabled": "0", "selectable": "0"},
            ]
        },
    )
    inputs = await NaimClient("naim", async_get_clientsession(hass)).get_inputs()
    assert inputs == [
        NaimInput("inputs/ana1", "Turntable", True),
        NaimInput("inputs/dig1", "Digital 1", True),
        NaimInput("inputs/multiroom", "Multi-room", False),
        NaimInput("inputs/tidal", "TIDAL", False),
    ]


async def test_device_info(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(
        f"{BASE}/system",
        json={
            "version": "1.4.0",
            "appVer": "3.13.0.5828",
            "hardwareType": "stream800",
            "hardwareSerial": "123456",
            "model": "33",
        },
    )
    sdk_answer(
        aioclient_mock,
        "systemmanager:systemMember",
        {
            "type": "systemMember",
            "systemMember": {
                "id": "np800-abc",
                "host": "Uniti-Star-123456.local.",
                "name": "Living room",
            },
        },
    )
    info = await NaimClient("naim", async_get_clientsession(hass)).get_device_info()
    assert info.unique_id == "np800-abc"
    assert info.name == "Living room"
    assert info.model == "Uniti Star"
    assert info.firmware == "3.13.0.5828"


async def test_device_info_needs_an_id(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{BASE}/system", json={"appVer": "3.13.0.5828"})
    aioclient_mock.get(SDK, status=404)
    with pytest.raises(NaimError):
        await NaimClient("naim", async_get_clientsession(hass)).get_device_info()


@pytest.mark.parametrize(
    ("host", "serial", "model"),
    [
        ("Uniti-Star-123456.local.", "123456", "Uniti Star"),
        ("NDX-2-1.local.", None, "NDX 2 1"),
        (None, "1", None),
    ],
)
def test_model_from_host(host, serial, model) -> None:
    assert model_from_host(host, serial) == model


@pytest.mark.parametrize(
    ("call", "method", "url"),
    [
        (lambda c: c.power_on(), "PUT", f"{BASE}/power?system=on"),
        (lambda c: c.power_standby(), "PUT", f"{BASE}/power?system=lona"),
        (lambda c: c.set_volume(31), "PUT", f"{BASE}/levels/room?volume=31"),
        (lambda c: c.set_mute(True), "PUT", f"{BASE}/levels/room?mute=1"),
        (lambda c: c.set_mute(False), "PUT", f"{BASE}/levels/room?mute=0"),
        (lambda c: c.control("prev"), "GET", f"{BASE}/nowplaying?cmd=prev"),
        (lambda c: c.select_input("inputs/ana1"), "GET", f"{BASE}/inputs/ana1?cmd=select"),
    ],
)
async def test_commands(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, call, method: str, url: str
) -> None:
    aioclient_mock.request(method, url, text="")
    await call(NaimClient("naim", async_get_clientsession(hass)))
    assert aioclient_mock.call_count == 1
    sent_method, sent_url, _, _ = aioclient_mock.mock_calls[0]
    assert sent_method == method
    assert str(sent_url) == url
