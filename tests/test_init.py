"""Tests for setting up and unloading the Asterisk Call Monitor integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from .conftest import make_entry, setup_entry
from custom_components.asterisk_call_monitor.ami import (
    AsteriskAuthError,
    AsteriskConnectionError,
)


async def test_setup_entry_connects(hass: HomeAssistant, mock_ami) -> None:
    """A working AMI connection loads the entry and its sensors."""
    entry = make_entry()
    await setup_entry(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    mock_ami.assert_called_once()
    assert hass.states.get("sensor.asterisk_pbx_local_incoming_call") is not None
    assert hass.states.get("sensor.asterisk_pbx_local_outgoing_call") is not None


async def test_entry_not_ready_when_unreachable(hass: HomeAssistant, mock_ami) -> None:
    """An unreachable AMI postpones setup so it can retry."""
    mock_ami.side_effect = AsteriskConnectionError("no route")
    entry = make_entry()
    await setup_entry(hass, entry)

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_entry_auth_failed_on_bad_credentials(
    hass: HomeAssistant, mock_ami
) -> None:
    """Wrong AMI credentials fail the entry instead of retrying forever."""
    mock_ami.side_effect = AsteriskAuthError("Authentication failed")
    entry = make_entry()
    await setup_entry(hass, entry)

    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_unload_entry(hass: HomeAssistant, mock_ami) -> None:
    """Unloading removes the entities and closes the AMI connection."""
    entry = make_entry()
    await setup_entry(hass, entry)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
