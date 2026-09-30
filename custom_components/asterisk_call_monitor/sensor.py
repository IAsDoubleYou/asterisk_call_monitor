"""Sensor platform for the Asterisk Call Monitor integration."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import ClassVar

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .ami import AmiConnection
from .call_tracker import CallState
from .const import (
    CALL_STATUSES,
    DIRECTION_INCOMING,
    DIRECTION_OUTGOING,
    DOMAIN,
    SIGNAL_CALL_UPDATED,
    STATUS_IDLE,
)

_LOGGER = logging.getLogger(__name__)

ATTR_PHONENUMBER = "phonenumber"
ATTR_STARTED_AT = "started_at"
ATTR_UPDATED_AT = "updated_at"
ATTR_CAUSE = "cause"
ATTR_CAUSE_TEXT = "cause_text"
ATTR_DIRECTION = "direction"


def _as_attr_timestamp(value: float | None) -> datetime | None:
    """Turn an epoch float into a timezone-aware UTC datetime for display.

    A plain epoch number is unreadable as an attribute; a datetime object is
    what Home Assistant's own sensors use for this (see e.g. the emoncms
    integration) and what dashboard templates can call as_local() on
    directly, without an as_datetime() conversion step first.
    """
    return dt_util.utc_from_timestamp(value) if value is not None else None


def _timestamp_from_restored_attr(value: object) -> float | None:
    """Parse a restored started_at/updated_at value back into an epoch float.

    Home Assistant's restore-state storage round-trips attributes through
    JSON, so a datetime object saved by this integration comes back as an
    ISO-8601 string. A raw float is also accepted, since data saved by a
    version of this integration before these attributes became datetimes
    is still a plain float the first time it is restored after an upgrade.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    parsed = dt_util.parse_datetime(str(value))
    return parsed.timestamp() if parsed is not None else None


_DIRECTION_NAMES = {
    DIRECTION_INCOMING: "Incoming call",
    DIRECTION_OUTGOING: "Outgoing call",
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the incoming, outgoing and last-call sensors."""
    connection: AmiConnection = entry.runtime_data
    async_add_entities(
        [
            AsteriskCallSensor(entry, connection, DIRECTION_INCOMING),
            AsteriskCallSensor(entry, connection, DIRECTION_OUTGOING),
            AsteriskLastCallSensor(entry, connection),
        ]
    )


class AsteriskCallSensor(SensorEntity, RestoreEntity):
    """Report the current status of one call direction.

    Push-driven: the state lives on the shared AmiConnection's call tracker,
    and this only re-renders when notified over the dispatcher, never polls.
    The call tracker itself is rebuilt empty on every Home Assistant start,
    so the last known call is restored into it once, from this entity's own
    last recorded state, before any live AMI event can arrive.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar[list[str]] = list(CALL_STATUSES)
    _attr_translation_key = "call_status"

    def __init__(
        self, entry: ConfigEntry, connection: AmiConnection, direction: str
    ) -> None:
        """Set up the sensor for one call direction."""
        self._connection = connection
        self._direction = direction
        self._attr_unique_id = f"{entry.entry_id}_{direction}"
        self._attr_name = _DIRECTION_NAMES[direction]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            model="Asterisk AMI",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to call-state updates and restore the last known call."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_CALL_UPDATED, self._handle_update
            )
        )
        await self._async_restore_last_call()

    async def _async_restore_last_call(self) -> None:
        last_state = await self.async_get_last_state()
        _LOGGER.debug(
            "%s: last recorded state before this restart was %s",
            self.entity_id,
            last_state.state if last_state is not None else "<none recorded>",
        )
        if last_state is None or last_state.state not in CALL_STATUSES:
            return
        if last_state.state == STATUS_IDLE:
            return
        attributes = last_state.attributes
        self._connection.tracker.restore(
            self._direction,
            CallState(
                status=last_state.state,
                phonenumber=attributes.get(ATTR_PHONENUMBER),
                started_at=_timestamp_from_restored_attr(
                    attributes.get(ATTR_STARTED_AT)
                ),
                updated_at=_timestamp_from_restored_attr(
                    attributes.get(ATTR_UPDATED_AT)
                ),
                cause=attributes.get(ATTR_CAUSE),
                cause_text=attributes.get(ATTR_CAUSE_TEXT),
            ),
        )
        _LOGGER.debug("%s: restored as %s", self.entity_id, last_state.state)
        self.async_write_ha_state()

    @callback
    def _handle_update(self, direction: str) -> None:
        """Re-render only when the update is for this sensor's own direction."""
        if direction == self._direction:
            self.async_write_ha_state()

    @property
    def _state(self) -> CallState:
        return getattr(self._connection.tracker, self._direction)

    @property
    def native_value(self) -> str:
        """Return the current call status."""
        return self._state.status

    @property
    def extra_state_attributes(self) -> dict[str, str | datetime | None]:
        """Return the phone number and call metadata."""
        state = self._state
        return {
            ATTR_PHONENUMBER: state.phonenumber,
            ATTR_STARTED_AT: _as_attr_timestamp(state.started_at),
            ATTR_UPDATED_AT: _as_attr_timestamp(state.updated_at),
            ATTR_CAUSE: state.cause,
            ATTR_CAUSE_TEXT: state.cause_text,
        }


class AsteriskLastCallSensor(SensorEntity, RestoreEntity):
    """Report whichever of the incoming or outgoing calls changed most recently.

    Takes over that call's status and details, plus which direction it was.
    Every status change of the currently-tracked direction counts as "most
    recent", not only the start of a call, so this follows one call through
    ringing/dialing, answered and its final status; it only switches
    direction once the other one produces an update of its own.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "Last call"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar[list[str]] = list(CALL_STATUSES)
    _attr_translation_key = "call_status"

    def __init__(self, entry: ConfigEntry, connection: AmiConnection) -> None:
        """Set up the sensor; it starts idle until the first call event."""
        self._connection = connection
        self._direction: str | None = None
        self._attr_unique_id = f"{entry.entry_id}_last_call"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            model="Asterisk AMI",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to call-state updates and restore which direction to follow."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_CALL_UPDATED, self._handle_update
            )
        )
        await self._async_restore_direction()

    async def _async_restore_direction(self) -> None:
        last_state = await self.async_get_last_state()
        _LOGGER.debug(
            "%s: last recorded state before this restart was %s",
            self.entity_id,
            last_state.state if last_state is not None else "<none recorded>",
        )
        if last_state is None:
            return
        direction = last_state.attributes.get(ATTR_DIRECTION)
        if direction in (DIRECTION_INCOMING, DIRECTION_OUTGOING):
            self._direction = direction
            _LOGGER.debug("%s: restored direction %s", self.entity_id, direction)
            self.async_write_ha_state()

    @callback
    def _handle_update(self, direction: str) -> None:
        """Adopt whichever direction just changed as the last call."""
        self._direction = direction
        self.async_write_ha_state()

    @property
    def _state(self) -> CallState | None:
        if self._direction is None:
            return None
        return getattr(self._connection.tracker, self._direction)

    @property
    def native_value(self) -> str:
        """Return the current status of the last call, or idle before any."""
        state = self._state
        return state.status if state is not None else STATUS_IDLE

    @property
    def extra_state_attributes(self) -> dict[str, str | datetime | None]:
        """Return the direction, phone number and call metadata."""
        state = self._state
        started_at = state.started_at if state is not None else None
        updated_at = state.updated_at if state is not None else None
        return {
            ATTR_DIRECTION: self._direction,
            ATTR_PHONENUMBER: state.phonenumber if state is not None else None,
            ATTR_STARTED_AT: _as_attr_timestamp(started_at),
            ATTR_UPDATED_AT: _as_attr_timestamp(updated_at),
            ATTR_CAUSE: state.cause if state is not None else None,
            ATTR_CAUSE_TEXT: state.cause_text if state is not None else None,
        }
