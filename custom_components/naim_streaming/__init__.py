"""Naim Streaming: Home Assistant integration for Naim network streamers.

Brought to you by HiFiSync (https://hifisync.com). Made by Zero Story Points.
"""

from __future__ import annotations

from dataclasses import asdict

from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import NaimClient, NaimConnectionError, NaimDeviceInfo, NaimError
from .const import CONF_DEVICE, DOMAIN
from .coordinator import NaimConfigEntry, NaimCoordinator

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.MEDIA_PLAYER, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: NaimConfigEntry) -> bool:
    """Set up a streamer from a config entry."""
    client = NaimClient(entry.data[CONF_HOST], async_get_clientsession(hass))
    try:
        device = await client.get_device_info()
    except NaimConnectionError as err:
        # A streamer that is off at the mains still gets its entities, shown as off, once it
        # has been seen before.
        if cached := entry.data.get(CONF_DEVICE):
            device = NaimDeviceInfo(**cached)
        else:
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key="not_responding",
                translation_placeholders={"host": entry.data[CONF_HOST]},
            ) from err
    except NaimError as err:
        raise ConfigEntryNotReady(str(err)) from err
    else:
        if entry.data.get(CONF_DEVICE) != asdict(device):
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_DEVICE: asdict(device)}
            )

    coordinator = NaimCoordinator(hass, entry, client, device)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_create_background_task(
        hass, coordinator.async_run_event_loop(), f"{DOMAIN} events {entry.entry_id}"
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NaimConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
