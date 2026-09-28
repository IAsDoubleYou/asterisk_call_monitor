"""Tests for the incoming/outgoing/last-call sensors."""

from __future__ import annotations

from datetime import datetime

from pytest_homeassistant_custom_component.common import mock_restore_cache

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .conftest import make_entry, setup_entry
from custom_components.asterisk_call_monitor.const import (
    DIRECTION_INCOMING,
    DIRECTION_OUTGOING,
    SIGNAL_CALL_UPDATED,
    STATUS_ANSWERED,
    STATUS_DIALING,
    STATUS_ENDED,
    STATUS_IDLE,
    STATUS_RINGING,
)

INCOMING_SENSOR = "sensor.asterisk_pbx_local_incoming_call"
OUTGOING_SENSOR = "sensor.asterisk_pbx_local_outgoing_call"
LAST_CALL_SENSOR = "sensor.asterisk_pbx_local_last_call"


async def _ring(hass: HomeAssistant, connection, caller_id: str) -> None:
    """Simulate an incoming call ringing and notify the sensors of it."""
    connection.tracker.handle_newchannel(
        {
            "Channel": "PJSIP/trunk-1",
            "ChannelStateDesc": "Ring",
            "CallerIDNum": caller_id,
        }
    )
    async_dispatcher_send(hass, SIGNAL_CALL_UPDATED, DIRECTION_INCOMING)
    await hass.async_block_till_done()


async def _dial(hass: HomeAssistant, connection, destination: str) -> None:
    """Simulate an outgoing call starting and notify the sensors of it."""
    connection.tracker.handle_dial(
        {"Channel": "PJSIP/100-1", "Dialstring": f"SIP/trunk/{destination}"}
    )
    async_dispatcher_send(hass, SIGNAL_CALL_UPDATED, DIRECTION_OUTGOING)
    await hass.async_block_till_done()


async def test_last_call_is_idle_before_any_call(hass: HomeAssistant, mock_ami) -> None:
    """With no call yet, the last-call sensor reports idle and no direction."""
    entry = make_entry()
    await setup_entry(hass, entry)

    state = hass.states.get(LAST_CALL_SENSOR)
    assert state.state == STATUS_IDLE
    assert state.attributes["direction"] is None


async def test_incoming_sensor_restores_its_last_call_after_a_restart(
    hass: HomeAssistant, mock_ami
) -> None:
    """A sensor's last known call survives a Home Assistant restart."""
    mock_restore_cache(
        hass,
        [
            State(
                INCOMING_SENSOR,
                STATUS_ANSWERED,
                {
                    "phonenumber": "0031612345678",
                    "started_at": 900.0,
                    "updated_at": 950.0,
                },
            )
        ],
    )
    entry = make_entry()
    await setup_entry(hass, entry)

    state = hass.states.get(INCOMING_SENSOR)
    assert state.state == STATUS_ANSWERED
    assert state.attributes["phonenumber"] == "0031612345678"
    assert state.attributes["updated_at"] == dt_util.utc_from_timestamp(950.0)


async def test_started_at_and_updated_at_are_readable_datetimes(
    hass: HomeAssistant, mock_ami
) -> None:
    """The timestamp attributes are datetimes, not raw epoch numbers."""
    entry = make_entry()
    await setup_entry(hass, entry)
    connection = entry.runtime_data

    await _ring(hass, connection, "0031612345678")

    state = hass.states.get(INCOMING_SENSOR)
    assert isinstance(state.attributes["started_at"], datetime)
    assert isinstance(state.attributes["updated_at"], datetime)


async def test_restore_accepts_an_iso_timestamp_from_a_previous_version(
    hass: HomeAssistant, mock_ami
) -> None:
    """A restored datetime (round-tripped through JSON as an ISO string) still works.

    Regression test: restore-state storage serializes a datetime attribute
    to an ISO-8601 string, unlike the plain float this integration used to
    store before started_at/updated_at became datetimes; restoring must
    parse that string back into a float for the tracker's own arithmetic.
    """
    mock_restore_cache(
        hass,
        [
            State(
                INCOMING_SENSOR,
                STATUS_ANSWERED,
                {
                    "phonenumber": "0031612345678",
                    "started_at": dt_util.utc_from_timestamp(900.0),
                    "updated_at": dt_util.utc_from_timestamp(950.0),
                },
            )
        ],
    )
    entry = make_entry()
    await setup_entry(hass, entry)

    state = hass.states.get(INCOMING_SENSOR)
    assert state.state == STATUS_ANSWERED
    assert state.attributes["updated_at"] == dt_util.utc_from_timestamp(950.0)


async def test_last_call_sensor_restores_its_direction_after_a_restart(
    hass: HomeAssistant, mock_ami
) -> None:
    """The last-call sensor follows the same restored call as the direction sensor."""
    mock_restore_cache(
        hass,
        [
            State(OUTGOING_SENSOR, STATUS_ENDED, {"phonenumber": "0031611112222"}),
            State(
                LAST_CALL_SENSOR,
                STATUS_ENDED,
                {"direction": DIRECTION_OUTGOING, "phonenumber": "0031611112222"},
            ),
        ],
    )
    entry = make_entry()
    await setup_entry(hass, entry)

    state = hass.states.get(LAST_CALL_SENSOR)
    assert state.state == STATUS_ENDED
    assert state.attributes["direction"] == DIRECTION_OUTGOING
    assert state.attributes["phonenumber"] == "0031611112222"


async def test_idle_last_state_is_not_restored(hass: HomeAssistant, mock_ami) -> None:
    """Restoring an idle sensor is a no-op: there is nothing to bring back."""
    mock_restore_cache(hass, [State(INCOMING_SENSOR, STATUS_IDLE, {})])
    entry = make_entry()
    await setup_entry(hass, entry)

    state = hass.states.get(INCOMING_SENSOR)
    assert state.state == STATUS_IDLE
    assert state.attributes["phonenumber"] is None


async def test_call_sensors_are_translatable_enums(
    hass: HomeAssistant, mock_ami
) -> None:
    """All three sensors expose their status as a translated enum, not raw text."""
    entry = make_entry()
    await setup_entry(hass, entry)

    for entity_id in (INCOMING_SENSOR, OUTGOING_SENSOR, LAST_CALL_SENSOR):
        state = hass.states.get(entity_id)
        assert state.attributes["device_class"] == "enum"
        assert state.state in state.attributes["options"]


async def test_last_call_follows_an_incoming_call(
    hass: HomeAssistant, mock_ami
) -> None:
    """An incoming call is adopted by the last-call sensor, direction included."""
    entry = make_entry()
    await setup_entry(hass, entry)
    connection = entry.runtime_data

    await _ring(hass, connection, "0031612345678")

    state = hass.states.get(LAST_CALL_SENSOR)
    assert state.state == STATUS_RINGING
    assert state.attributes["direction"] == DIRECTION_INCOMING
    assert state.attributes["phonenumber"] == "0031612345678"
    assert hass.states.get(INCOMING_SENSOR).state == STATUS_RINGING


async def test_last_call_switches_direction_on_a_new_event(
    hass: HomeAssistant, mock_ami
) -> None:
    """An outgoing call takes over from a previously tracked incoming one."""
    entry = make_entry()
    await setup_entry(hass, entry)
    connection = entry.runtime_data

    await _ring(hass, connection, "0031612345678")
    await _dial(hass, connection, "0031687654321")

    state = hass.states.get(LAST_CALL_SENSOR)
    assert state.state == STATUS_DIALING
    assert state.attributes["direction"] == DIRECTION_OUTGOING
    assert state.attributes["phonenumber"] == "0031687654321"
    # The incoming sensor itself keeps its own state; only "last call" moved on.
    assert hass.states.get(INCOMING_SENSOR).state == STATUS_RINGING


async def test_last_call_keeps_following_the_same_direction_through_its_lifecycle(
    hass: HomeAssistant, mock_ami
) -> None:
    """Answering the still-current call keeps last-call on that same direction."""
    entry = make_entry()
    await setup_entry(hass, entry)
    connection = entry.runtime_data

    await _ring(hass, connection, "0031612345678")

    connection.tracker.handle_answered({"Channel": "PJSIP/trunk-1"})
    async_dispatcher_send(hass, SIGNAL_CALL_UPDATED, DIRECTION_INCOMING)
    await hass.async_block_till_done()

    state = hass.states.get(LAST_CALL_SENSOR)
    assert state.state == STATUS_ANSWERED
    assert state.attributes["direction"] == DIRECTION_INCOMING
