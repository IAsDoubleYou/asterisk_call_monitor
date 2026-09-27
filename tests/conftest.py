"""Fixtures for the Asterisk Call Monitor tests."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant

from custom_components.asterisk_call_monitor.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    DOMAIN,
)

pytest_plugins = "pytest_homeassistant_custom_component"

CONNECTION = {
    CONF_HOST: "pbx.local",
    CONF_PORT: 5038,
    CONF_USERNAME: "hauser",
    CONF_PASSWORD: "secret",
}

UNIQUE_ID = "pbx.local:5038"


def make_entry() -> MockConfigEntry:
    """Return a config entry for the test AMI connection."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Asterisk @ pbx.local",
        data=CONNECTION,
        unique_id=UNIQUE_ID,
    )


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add the entry to Home Assistant and set it up."""
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading of the custom integration in every test."""


@pytest.fixture
def mock_ami() -> Generator[Any]:
    """Replace the blocking AMI connection with a mock.

    Only connect/close are patched: register_event never runs, so nothing
    ever calls back into a real socket during a test.
    """
    with (
        patch(
            "custom_components.asterisk_call_monitor.ami.AmiConnection.async_connect",
            autospec=True,
        ) as connect,
        patch(
            "custom_components.asterisk_call_monitor.ami.AmiConnection.async_close",
            autospec=True,
        ),
    ):
        yield connect
