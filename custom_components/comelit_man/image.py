"""Image entity — stores the last doorbell ring snapshot."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

if TYPE_CHECKING:
    from collections.abc import Callable

from .coordinator import ComelitLocalConfigEntry, ComelitLocalCoordinator
from .entity import ComelitEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ComelitLocalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up image entities — only when the device has an intercom (doors)."""
    coordinator = entry.runtime_data
    config = coordinator.device_config
    if not config or not config.doors:
        return
    async_add_entities([LastRingImage(coordinator, entry.entry_id)])


class LastRingImage(ComelitEntity, ImageEntity):
    """Stores the JPEG snapshot captured when the last ring started passive video.

    Updated by the coordinator's best-frame sampling after each ring (the ring event
    itself fires earlier, before any video frame exists).
    Never overwritten by outbound video initiation.
    """

    _attr_translation_key = "last_ring_image"
    _attr_content_type = "image/jpeg"

    def __init__(
        self,
        coordinator: ComelitLocalCoordinator,
        entry_id: str,
    ) -> None:
        """Initialize the last-ring image entity."""
        ComelitEntity.__init__(self, coordinator, entry_id)
        ImageEntity.__init__(self, coordinator.hass)
        self._attr_unique_id = f"{entry_id}_last_ring_image"
        self._remove_push_cb: Callable[[], None] | None = None

    async def async_image(self) -> bytes | None:
        """Return the last ring snapshot bytes."""
        return self.coordinator.last_ring_snapshot

    async def async_added_to_hass(self) -> None:
        """Register for snapshot updates."""
        self._remove_push_cb = self.coordinator.add_snapshot_callback(self._on_snapshot)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister the snapshot callback."""
        if self._remove_push_cb:
            self._remove_push_cb()
            self._remove_push_cb = None

    def _on_snapshot(self) -> None:
        """Refresh state when a (better) snapshot has been stored.

        The ring event fires before any video frame exists, so the image is
        updated separately, ~0.2-2.5 s later.  Automations that need the
        picture should trigger on this entity's state change, or wait a few
        seconds after the ring event.
        """
        self._attr_image_last_updated = datetime.now(UTC)
        self.async_write_ha_state()
