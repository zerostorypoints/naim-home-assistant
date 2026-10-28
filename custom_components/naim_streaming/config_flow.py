"""Config flow: zeroconf discovery, host entry, reconfigure, and options."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers import issue_registry as ir, selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
import voluptuous as vol

from .api import NaimConnectionError, NaimDeviceInfo, NaimError, async_probe
from .const import (
    CONF_HIDDEN_SOURCES,
    CONF_MAX_VOLUME,
    CONF_SOURCES,
    DEFAULT_MAX_VOLUME,
    DOMAIN,
    HIFISYNC_URL,
    ZSP_URL,
)

CREDITS = {"hifisync_url": HIFISYNC_URL, "zsp_url": ZSP_URL}

_LOGGER = logging.getLogger(__name__)


class NaimConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a Naim streamer."""

    VERSION = 1

    def __init__(self) -> None:
        self._host: str | None = None
        self._device: NaimDeviceInfo | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> NaimOptionsFlow:
        return NaimOptionsFlow()

    async def _probe(self, host: str) -> tuple[NaimDeviceInfo | None, str | None]:
        try:
            return await async_probe(host, async_get_clientsession(self.hass)), None
        except (NaimConnectionError, TimeoutError):
            return None, "cannot_connect"
        except NaimError:
            _LOGGER.exception("Unexpected answer from %s", host)
            return None, "not_naim"

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            device, error = await self._probe(host)
            if device:
                await self.async_set_unique_id(device.unique_id)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                return self.async_create_entry(title=device.name, data={CONF_HOST: host})
            errors["base"] = error or "unknown"
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Required(CONF_HOST): str}), user_input
            ),
            errors=errors,
            description_placeholders=CREDITS,
        )

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> ConfigFlowResult:
        # Hegel's and T+A's streamers announce the same service; only Naim's are ours.
        props = discovery_info.properties
        if not (props.get("manufacturer") or "").lower().startswith("naim"):
            return self.async_abort(reason="not_naim")
        host = props.get("ip") or discovery_info.host
        if uuid := props.get("uuid"):
            await self.async_set_unique_id(uuid)
            self._async_follow_new_host(host)
        device, error = await self._probe(host)
        if not device:
            return self.async_abort(reason=error or "cannot_connect")
        if model := props.get("model"):
            device.model = model
        await self.async_set_unique_id(device.unique_id)
        self._async_follow_new_host(host)
        self._host, self._device = host, device
        self.context["title_placeholders"] = {"name": device.name}
        return await self.async_step_zeroconf_confirm()

    @callback
    def _async_follow_new_host(self, host: str) -> None:
        """Abort if the streamer is set up, taking over a changed address.

        A changed address means the router gave the streamer a new one. It is followed
        automatically, and a repair issue suggests reserving the address.
        """
        entry = self.hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, self.unique_id)
        if entry and entry.data.get(CONF_HOST) != host:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"address_changed_{entry.entry_id}",
                is_fixable=False,
                is_persistent=True,
                severity=ir.IssueSeverity.WARNING,
                translation_key="address_changed",
                translation_placeholders={
                    "name": entry.title,
                    "old_host": entry.data.get(CONF_HOST, ""),
                    "new_host": host,
                },
            )
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._device and self._host
        if user_input is not None:
            return self.async_create_entry(title=self._device.name, data={CONF_HOST: self._host})
        self._set_confirm_only()
        return self.async_show_form(
            step_id="zeroconf_confirm",
            description_placeholders={
                "name": self._device.name,
                "model": self._device.model,
                "host": self._host,
                **CREDITS,
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            device, error = await self._probe(host)
            if device:
                await self.async_set_unique_id(device.unique_id)
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(entry, data_updates={CONF_HOST: host})
            errors["base"] = error or "unknown"
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Required(CONF_HOST): str}), user_input or entry.data
            ),
            errors=errors,
            description_placeholders=CREDITS,
        )


class NaimOptionsFlow(OptionsFlowWithReload):
    """Volume limit and hidden inputs.

    Inputs are renamed in the Naim app (the streamer stores the name), so there is no name field.
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        # Only inputs the streamer can switch to: a streaming service starts from its own app.
        inputs = {
            ussi: cached["name"]
            for ussi, cached in self.config_entry.data.get(CONF_SOURCES, {}).items()
            if cached.get("selectable")
        }
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_MAX_VOLUME: user_input[CONF_MAX_VOLUME],
                    CONF_HIDDEN_SOURCES: [
                        u for u in inputs if u in user_input.get(CONF_HIDDEN_SOURCES, [])
                    ],
                }
            )
        fields: dict[Any, Any] = {
            vol.Required(CONF_MAX_VOLUME, default=DEFAULT_MAX_VOLUME): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=10, max=100, step=1, mode=selector.NumberSelectorMode.SLIDER
                )
            ),
        }
        if inputs:
            fields[vol.Optional(CONF_HIDDEN_SOURCES, default=[])] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value=ussi, label=name)
                        for ussi, name in inputs.items()
                    ],
                    multiple=True,
                    mode=selector.SelectSelectorMode.LIST,
                )
            )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(fields), self.config_entry.options
            ),
            description_placeholders=CREDITS,
        )
