"""Config flow for the Asterisk Call Monitor integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .ami import AmiConnection, AsteriskAuthError, AsteriskConnectionError
from .call_tracker import CallTracker
from .const import (
    CONF_EXCLUDED_EXTENSIONS,
    CONF_HOST,
    CONF_MIN_EXTERNAL_DIGITS,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    DEFAULT_EXCLUDED_EXTENSIONS,
    DEFAULT_MIN_EXTERNAL_DIGITS,
    DEFAULT_PORT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# Database errors are shown on the form itself, so they are cut off before
# they push the rest of the dialog out of view.
_MAX_ERROR_LENGTH = 255

CONNECTION_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): TextSelector(),
        vol.Required(CONF_PORT, default=DEFAULT_PORT): NumberSelector(
            NumberSelectorConfig(min=1, max=65535, step=1, mode=NumberSelectorMode.BOX)
        ),
        vol.Required(CONF_USERNAME): TextSelector(),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)

# Reauth only asks for credentials; the host and port of an existing entry
# stay untouched, matching what actually goes stale (a rotated AMI secret).
REAUTH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): TextSelector(),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)


def _error_detail(err: Exception) -> str:
    """Return the message of an error in a form that fits on the dialog."""
    message = str(err).strip()
    if not message:
        return type(err).__name__
    if len(message) > _MAX_ERROR_LENGTH:
        message = f"{message[:_MAX_ERROR_LENGTH]}..."
    return message


async def _async_validate_connection(
    hass: HomeAssistant, connection: dict[str, Any]
) -> tuple[str | None, str]:
    """Try the AMI connection. Returns the error key to show, and a detail message."""
    ami = AmiConnection(
        hass,
        connection,
        CallTracker(DEFAULT_EXCLUDED_EXTENSIONS, DEFAULT_MIN_EXTERNAL_DIGITS),
    )
    try:
        await ami.async_connect()
    except AsteriskAuthError as err:
        return "invalid_auth", _error_detail(err)
    except AsteriskConnectionError as err:
        return "cannot_connect", _error_detail(err)
    except Exception as err:
        _LOGGER.exception("Unexpected error while validating the connection")
        return "unknown", _error_detail(err)
    else:
        await ami.async_close()
        return None, ""


class AsteriskCallMonitorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the setup of an Asterisk AMI connection."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> AsteriskCallMonitorOptionsFlow:
        """Return the options flow that manages call-classification settings."""
        return AsteriskCallMonitorOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the AMI connection settings."""
        errors: dict[str, str] = {}
        detail = ""

        if user_input is not None:
            connection = {
                CONF_HOST: user_input[CONF_HOST].strip(),
                CONF_PORT: int(user_input[CONF_PORT]),
                CONF_USERNAME: user_input[CONF_USERNAME],
                CONF_PASSWORD: user_input[CONF_PASSWORD],
            }

            await self.async_set_unique_id(
                f"{connection[CONF_HOST]}:{connection[CONF_PORT]}"
            )
            self._abort_if_unique_id_configured()

            error, detail = await _async_validate_connection(self.hass, connection)
            if error is None:
                return self.async_create_entry(
                    title=f"Asterisk @ {connection[CONF_HOST]}",
                    data=connection,
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                CONNECTION_SCHEMA, user_input or {}
            ),
            errors=errors,
            description_placeholders={"error": detail},
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauth after ConfigEntryAuthFailed; the host/port stay the same."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Re-collect the AMI username and password for the existing entry."""
        errors: dict[str, str] = {}
        detail = ""
        entry = self._get_reauth_entry()

        if user_input is not None:
            connection = {
                CONF_HOST: entry.data[CONF_HOST],
                CONF_PORT: entry.data[CONF_PORT],
                CONF_USERNAME: user_input[CONF_USERNAME],
                CONF_PASSWORD: user_input[CONF_PASSWORD],
            }
            error, detail = await _async_validate_connection(self.hass, connection)
            if error is None:
                return self.async_update_reload_and_abort(entry, data=connection)
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                REAUTH_SCHEMA, user_input or {CONF_USERNAME: entry.data[CONF_USERNAME]}
            ),
            errors=errors,
            description_placeholders={"error": detail, "host": entry.data[CONF_HOST]},
        )


class AsteriskCallMonitorOptionsFlow(OptionsFlow):
    """Manage which extensions are internal and how outgoing numbers are recognized."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the call-classification options."""
        if user_input is not None:
            excluded = [
                item.strip()
                for item in user_input[CONF_EXCLUDED_EXTENSIONS].split(",")
                if item.strip()
            ]
            return self.async_create_entry(
                data={
                    CONF_EXCLUDED_EXTENSIONS: excluded,
                    CONF_MIN_EXTERNAL_DIGITS: int(user_input[CONF_MIN_EXTERNAL_DIGITS]),
                }
            )

        current = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_EXCLUDED_EXTENSIONS,
                        default=", ".join(
                            current.get(
                                CONF_EXCLUDED_EXTENSIONS, DEFAULT_EXCLUDED_EXTENSIONS
                            )
                        ),
                    ): TextSelector(),
                    vol.Required(
                        CONF_MIN_EXTERNAL_DIGITS,
                        default=current.get(
                            CONF_MIN_EXTERNAL_DIGITS, DEFAULT_MIN_EXTERNAL_DIGITS
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1, max=20, step=1, mode=NumberSelectorMode.BOX
                        )
                    ),
                }
            ),
        )
