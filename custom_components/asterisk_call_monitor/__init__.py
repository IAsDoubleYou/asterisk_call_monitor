"""The Asterisk Call Monitor integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .ami import AmiConnection, AsteriskAuthError, AsteriskConnectionError
from .call_tracker import CallTracker
from .const import (
    CONF_EXCLUDED_EXTENSIONS,
    CONF_MIN_EXTERNAL_DIGITS,
    DEFAULT_EXCLUDED_EXTENSIONS,
    DEFAULT_MIN_EXTERNAL_DIGITS,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

type AsteriskCallMonitorConfigEntry = ConfigEntry[AmiConnection]


async def async_setup_entry(
    hass: HomeAssistant, entry: AsteriskCallMonitorConfigEntry
) -> bool:
    """Set up Asterisk Call Monitor from a config entry."""
    options = entry.options
    tracker = CallTracker(
        excluded_extensions=options.get(
            CONF_EXCLUDED_EXTENSIONS, DEFAULT_EXCLUDED_EXTENSIONS
        ),
        min_external_digits=options.get(
            CONF_MIN_EXTERNAL_DIGITS, DEFAULT_MIN_EXTERNAL_DIGITS
        ),
    )
    connection = AmiConnection(hass, dict(entry.data), tracker)

    try:
        await connection.async_connect()
    except AsteriskAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except AsteriskConnectionError as err:
        raise ConfigEntryNotReady(str(err)) from err

    entry.runtime_data = connection
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: AsteriskCallMonitorConfigEntry
) -> bool:
    """Unload a config entry and close its AMI connection."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_close()
    return unloaded


async def _async_reload_entry(
    hass: HomeAssistant, entry: AsteriskCallMonitorConfigEntry
) -> None:
    """Reload the entry after its options changed."""
    await hass.config_entries.async_reload(entry.entry_id)
