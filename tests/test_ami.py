"""Tests for AmiConnection itself, with pyst2's Manager mocked out.

Unlike test_config_flow.py/test_init.py (which mock AmiConnection.async_connect
wholesale), these exercise the real async_connect() body - including the
homeassistant.helpers.event calls it makes - so a mistake like passing a
plain int where async_track_time_interval requires a timedelta is actually
caught, instead of being hidden behind the mock.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from homeassistant.core import HomeAssistant

from custom_components.asterisk_call_monitor.ami import AmiConnection
from custom_components.asterisk_call_monitor.call_tracker import CallTracker
from custom_components.asterisk_call_monitor.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
)

CONNECTION = {
    CONF_HOST: "pbx.local",
    CONF_PORT: 5038,
    CONF_USERNAME: "hauser",
    CONF_PASSWORD: "secret",
}


async def test_async_connect_registers_events_and_starts_the_watchdog(
    hass: HomeAssistant,
) -> None:
    """async_connect() runs to completion against a fake pyst2 Manager.

    A regression test for passing RECONNECT_INTERVAL (a plain int) straight
    to async_track_time_interval, which requires a timedelta and raised
    "'int' object has no attribute 'total_seconds'" at runtime.
    """
    fake_manager = MagicMock()

    with patch(
        "custom_components.asterisk_call_monitor.ami.Manager",
        return_value=fake_manager,
    ):
        connection = AmiConnection(hass, CONNECTION, CallTracker(["100"], 5))
        await connection.async_connect()

    assert fake_manager.connect.called
    assert fake_manager.login.called
    assert fake_manager.register_event.call_count == 6
    assert connection._unsub_watchdog is not None

    await connection.async_close()
    assert fake_manager.close.called
