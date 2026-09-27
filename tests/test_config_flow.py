"""Tests for the Asterisk Call Monitor config and options flow."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import CONNECTION, UNIQUE_ID, make_entry, setup_entry
from custom_components.asterisk_call_monitor.ami import (
    AsteriskAuthError,
    AsteriskConnectionError,
)
from custom_components.asterisk_call_monitor.const import (
    CONF_EXCLUDED_EXTENSIONS,
    CONF_MIN_EXTERNAL_DIGITS,
    DEFAULT_EXCLUDED_EXTENSIONS,
    DEFAULT_MIN_EXTERNAL_DIGITS,
    DOMAIN,
)

USER_INPUT = {
    "host": "pbx.local",
    "port": 5038,
    "username": "hauser",
    "password": "secret",
}


async def test_user_flow(hass: HomeAssistant, mock_ami) -> None:
    """A working connection results in a config entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Asterisk @ pbx.local"
    assert result["data"] == CONNECTION


async def test_user_flow_cannot_connect(hass: HomeAssistant, mock_ami) -> None:
    """An unreachable AMI is reported on the form."""
    mock_ami.side_effect = AsteriskConnectionError("no route to host")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert "no route" in result["description_placeholders"]["error"]


async def test_user_flow_invalid_auth(hass: HomeAssistant, mock_ami) -> None:
    """Wrong AMI credentials are reported as such."""
    mock_ami.side_effect = AsteriskAuthError("Authentication failed")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_unexpected_error(hass: HomeAssistant, mock_ami) -> None:
    """An unexpected error shows what actually went wrong."""
    mock_ami.side_effect = RuntimeError("boom")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}
    assert result["description_placeholders"]["error"] == "boom"


async def test_user_flow_recovers_after_error(hass: HomeAssistant, mock_ami) -> None:
    """The form can be submitted again once the problem is solved."""
    mock_ami.side_effect = AsteriskConnectionError("no route")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["errors"] == {"base": "cannot_connect"}

    mock_ami.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_duplicate(hass: HomeAssistant, mock_ami) -> None:
    """The same AMI host and port cannot be added twice."""
    entry = make_entry()
    entry.add_to_hass(hass)
    assert entry.unique_id == UNIQUE_ID

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow_updates_settings(hass: HomeAssistant, mock_ami) -> None:
    """Submitting the options form stores the new classification settings."""
    entry = make_entry()
    await setup_entry(hass, entry)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_EXCLUDED_EXTENSIONS: "100, 101",
            CONF_MIN_EXTERNAL_DIGITS: 6,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_EXCLUDED_EXTENSIONS] == ["100", "101"]
    assert entry.options[CONF_MIN_EXTERNAL_DIGITS] == 6


async def test_options_flow_default_values_used_when_unset(
    hass: HomeAssistant, mock_ami
) -> None:
    """Defaults from the constants module are used until the user changes them."""
    entry = make_entry()
    await setup_entry(hass, entry)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    schema_defaults = {
        field.schema: field.default() if callable(field.default) else field.default
        for field in result["data_schema"].schema
    }
    assert schema_defaults[CONF_EXCLUDED_EXTENSIONS] == ", ".join(
        DEFAULT_EXCLUDED_EXTENSIONS
    )
    assert schema_defaults[CONF_MIN_EXTERNAL_DIGITS] == DEFAULT_MIN_EXTERNAL_DIGITS
