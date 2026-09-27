"""Sensor platform for the Asterisk Call Monitor integration."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .ami import AmiConnection
from .call_tracker import CallState
from .const import (
    DIRECTION_INCOMING,
    DIRECTION_OUTGOING,
    DOMAIN,
    SIGNAL_CALL_UPDATED,
    STATUS_IDLE,
)

ATTR_PHONENUMBER = "phonenumber"
ATTR_STARTED_AT = "started_at"
ATTR_CAUSE = "cause"
ATTR_CAUSE_TEXT = "cause_text"
ATTR_DIRECTION = "direction"

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


class AsteriskCallSensor(SensorEntity):
    """Report the current status of one call direction.

    Push-driven: the state lives on the shared AmiConnection's call tracker,
    and this only re-renders when notified over the dispatcher, never polls.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

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
        """Subscribe to call-state updates for this direction."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_CALL_UPDATED, self._handle_update
            )
        )

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
    def extra_state_attributes(self) -> dict[str, str | float | None]:
        """Return the phone number and call metadata."""
        state = self._state
        return {
            ATTR_PHONENUMBER: state.phonenumber,
            ATTR_STARTED_AT: state.started_at,
            ATTR_CAUSE: state.cause,
            ATTR_CAUSE_TEXT: state.cause_text,
        }


class AsteriskLastCallSensor(SensorEntity):
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
        """Subscribe to call-state updates for either direction."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_CALL_UPDATED, self._handle_update
            )
        )

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
    def extra_state_attributes(self) -> dict[str, str | float | None]:
        """Return the direction, phone number and call metadata."""
        state = self._state
        return {
            ATTR_DIRECTION: self._direction,
            ATTR_PHONENUMBER: state.phonenumber if state is not None else None,
            ATTR_STARTED_AT: state.started_at if state is not None else None,
            ATTR_CAUSE: state.cause if state is not None else None,
            ATTR_CAUSE_TEXT: state.cause_text if state is not None else None,
        }
