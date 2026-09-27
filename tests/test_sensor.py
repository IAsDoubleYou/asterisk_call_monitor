"""Tests for the incoming/outgoing/last-call sensors."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .conftest import make_entry, setup_entry
from custom_components.asterisk_call_monitor.const import (
    DIRECTION_INCOMING,
    DIRECTION_OUTGOING,
    SIGNAL_CALL_UPDATED,
    STATUS_ANSWERED,
    STATUS_DIALING,
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
