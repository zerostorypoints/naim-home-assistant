"""Config flow tests."""

from __future__ import annotations

from dataclasses import replace
from ipaddress import ip_address
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.naim_streaming.api import NaimConnectionError, NaimError
from custom_components.naim_streaming.const import (
    CONF_HIDDEN_SOURCES,
    CONF_MAX_VOLUME,
    CONF_SOURCES,
    DOMAIN,
)

from .conftest import DEVICE, HOST, UNIQUE_ID

PROBE = "custom_components.naim_streaming.config_flow.async_probe"
SETUP = "custom_components.naim_streaming.async_setup_entry"

# The shape of a Uniti Star's announcement.
ZEROCONF = ZeroconfServiceInfo(
    ip_address=ip_address(HOST),
    ip_addresses=[ip_address(HOST)],
    hostname="Uniti-Star-123456.local.",
    name=f"{UNIQUE_ID}._sues800device._tcp.local.",
    port=80,
    type="_sues800device._tcp.local.",
    properties={
        "uuid": UNIQUE_ID,
        "manufacturer": "Naim Audio",
        "serial": "123456",
        "model": "Uniti Star",
        "usage": "streamer",
        "name": "Uniti Star",
        "ip": HOST,
    },
)


async def discover(hass: HomeAssistant, info: ZeroconfServiceInfo = ZEROCONF) -> dict:
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=info
    )


async def start(hass: HomeAssistant) -> dict:
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_user_flow(hass: HomeAssistant) -> None:
    result = await start(hass)
    assert result["type"] is FlowResultType.FORM

    with patch(PROBE, return_value=DEVICE), patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": f" {HOST} "}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Uniti Star"
    assert result["data"] == {"host": HOST}
    assert result["result"].unique_id == UNIQUE_ID


async def test_user_flow_cannot_connect(hass: HomeAssistant) -> None:
    result = await start(hass)
    with patch(PROBE, side_effect=NaimConnectionError("timeout")):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": HOST})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    with patch(PROBE, return_value=DEVICE), patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": HOST})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_not_naim(hass: HomeAssistant) -> None:
    result = await start(hass)
    with patch(PROBE, side_effect=NaimError("not JSON")):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": HOST})
    assert result["errors"] == {"base": "not_naim"}


async def test_user_flow_already_configured(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    result = await start(hass)
    with patch(PROBE, return_value=DEVICE):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "192.168.1.51"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert config_entry.data["host"] == "192.168.1.51"


async def test_zeroconf_flow(hass: HomeAssistant) -> None:
    with patch(PROBE, return_value=replace(DEVICE, model="Naim")):
        result = await discover(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zeroconf_confirm"
    # The announced model wins over the one read from the host name.
    assert result["description_placeholders"]["model"] == "Uniti Star"
    with patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"host": HOST}
    assert result["result"].unique_id == UNIQUE_ID


async def test_zeroconf_follows_a_new_address(
    hass: HomeAssistant, config_entry: MockConfigEntry, issue_registry: ir.IssueRegistry
) -> None:
    config_entry.add_to_hass(hass)
    moved = replace(
        ZEROCONF,
        ip_address=ip_address("192.168.1.77"),
        properties={**ZEROCONF.properties, "ip": "192.168.1.77"},
    )
    with patch(PROBE) as probe:
        result = await discover(hass, moved)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    probe.assert_not_called()
    assert config_entry.data["host"] == "192.168.1.77"
    assert issue_registry.async_get_issue(DOMAIN, f"address_changed_{config_entry.entry_id}")


async def test_zeroconf_same_address_no_issue(
    hass: HomeAssistant, config_entry: MockConfigEntry, issue_registry: ir.IssueRegistry
) -> None:
    config_entry.add_to_hass(hass)
    result = await discover(hass)
    assert result["reason"] == "already_configured"
    assert not issue_registry.issues


async def test_zeroconf_other_manufacturer(hass: HomeAssistant) -> None:
    """Hegel's and T+A's streamers announce the same service."""
    other = replace(ZEROCONF, properties={**ZEROCONF.properties, "manufacturer": "Hegel"})
    with patch(PROBE) as probe:
        result = await discover(hass, other)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_naim"
    probe.assert_not_called()


async def test_zeroconf_cannot_connect(hass: HomeAssistant) -> None:
    with patch(PROBE, side_effect=NaimConnectionError("timeout")):
        result = await discover(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_reconfigure(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    with patch(PROBE, return_value=DEVICE), patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "192.168.1.52"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data["host"] == "192.168.1.52"


async def test_reconfigure_wrong_device(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reconfigure_flow(hass)
    with patch(PROBE, return_value=replace(DEVICE, unique_id="np800-other")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "192.168.1.52"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_device"
    assert config_entry.data["host"] == HOST


async def test_options_flow(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=UNIQUE_ID,
        data={
            "host": HOST,
            CONF_SOURCES: {
                "inputs/ana1": {"name": "Turntable", "selectable": True},
                "inputs/cd": {"name": "CD Player", "selectable": True},
                "inputs/tidal": {"name": "TIDAL", "selectable": False},
            },
        },
    )
    entry.add_to_hass(hass)
    with patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] is FlowResultType.FORM
        schema = result["data_schema"].schema
        hidden = next(k for k in schema if k == CONF_HIDDEN_SOURCES)
        options = schema[hidden].config["options"]
        # A streaming service starts from its own app: it is not offered.
        assert [o["value"] for o in options] == ["inputs/ana1", "inputs/cd"]
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_MAX_VOLUME: 60, CONF_HIDDEN_SOURCES: ["inputs/cd"]}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_MAX_VOLUME: 60, CONF_HIDDEN_SOURCES: ["inputs/cd"]}


async def test_options_flow_without_known_inputs(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    with patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_init(config_entry.entry_id)
        assert CONF_HIDDEN_SOURCES not in result["data_schema"].schema
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_MAX_VOLUME: 80}
        )
    assert config_entry.options == {CONF_MAX_VOLUME: 80, CONF_HIDDEN_SOURCES: []}
