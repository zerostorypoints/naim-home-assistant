"""Network connectivity of the streamerlifier."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NaimConfigEntry
from .entity import NaimEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NaimConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([NaimConnectivity(entry.runtime_data)])


class NaimConnectivity(NaimEntity, BinarySensorEntity):
    """On while the streamer answers on the network, in standby too.

    Off means it is switched off at the mains, unplugged or not on the network.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "network"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "network")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data and self.coordinator.data.reachable)
