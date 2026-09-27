"""AMI connection management for the Asterisk Call Monitor integration.

pyst2's Manager runs its own background threads for reading the socket and
dispatching registered event callbacks (started automatically by connect());
callbacks therefore never run on Home Assistant's event loop, and every call
back into hass has to be bridged onto it explicitly. A dropped connection is
not reported through an exception either - pyst2 clears its own internal
"connected" flag and lets the caller notice - so this owns a periodic
watchdog rather than relying on pyst2 to signal trouble.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta
import logging
from typing import Any

from asterisk.manager import Manager, ManagerAuthException, ManagerSocketException

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_time_interval

from .call_tracker import CallTracker
from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    DIRECTION_INCOMING,
    DIRECTION_OUTGOING,
    EVENT_BRIDGE_ENTER,
    EVENT_DIAL,
    EVENT_DIAL_ANSWER,
    EVENT_HANGUP,
    EVENT_NEWCHANNEL,
    EVENT_NEWEXTEN,
    RECONNECT_INTERVAL,
    SIGNAL_CALL_UPDATED,
    STUCK_CALL_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)

# How long a Newexten fallback match waits for a Dial event to supersede it,
# mirroring the production script this integration replaces.
_PENDING_OUTGOING_DELAY = 2.0


class AsteriskConnectionError(Exception):
    """Raised when the AMI connection cannot be established."""


class AsteriskAuthError(Exception):
    """Raised when the AMI login is refused."""


class AmiConnection:
    """Own a single AMI connection and keep the call tracker up to date."""

    def __init__(
        self, hass: HomeAssistant, connection: dict[str, Any], tracker: CallTracker
    ) -> None:
        """Store the connection settings; connect() actually opens it."""
        self._hass = hass
        self._host = connection[CONF_HOST]
        self._port = connection[CONF_PORT]
        self._username = connection[CONF_USERNAME]
        self._password = connection[CONF_PASSWORD]
        self.tracker = tracker
        self._manager: Manager | None = None
        self._unsub_watchdog: Callable[[], None] | None = None

    @property
    def is_connected(self) -> bool:
        """Return whether the AMI connection is currently up.

        pyst2 exposes no public property for this; ``_connected`` is the
        internal ``threading.Event`` the library itself clears on a socket
        failure, so it is the only accurate signal available. Anything that
        goes wrong reading it is treated as "not connected", which is the
        safe failure mode here: it just triggers a reconnect attempt.
        """
        if self._manager is None:
            return False
        try:
            return bool(self._manager._connected.isSet())  # noqa: SLF001
        except AttributeError:
            return False

    async def async_connect(self) -> None:
        """Open the AMI connection, log in, and start listening for events."""
        try:
            await self._hass.async_add_executor_job(self._connect_and_login)
        except ManagerSocketException as err:
            raise AsteriskConnectionError(str(err)) from err
        except ManagerAuthException as err:
            raise AsteriskAuthError(str(err)) from err

        self._register_event_handlers()
        self._unsub_watchdog = async_track_time_interval(
            self._hass, self._async_watchdog, timedelta(seconds=RECONNECT_INTERVAL)
        )

    def _connect_and_login(self) -> None:
        """Blocking: open the socket and authenticate. Runs in the executor."""
        manager = Manager()
        manager.connect(self._host, self._port)
        manager.login(self._username, self._password)
        self._manager = manager

    async def async_close(self) -> None:
        """Stop the watchdog and close the AMI connection."""
        if self._unsub_watchdog is not None:
            self._unsub_watchdog()
            self._unsub_watchdog = None
        if self._manager is not None:
            await self._hass.async_add_executor_job(self._manager.close)
            self._manager = None

    def _register_event_handlers(self) -> None:
        assert self._manager is not None
        self._manager.register_event(EVENT_NEWCHANNEL, self._on_newchannel)
        self._manager.register_event(EVENT_NEWEXTEN, self._on_newexten)
        self._manager.register_event(EVENT_DIAL, self._on_dial)
        self._manager.register_event(EVENT_HANGUP, self._on_hangup)
        self._manager.register_event(EVENT_BRIDGE_ENTER, self._on_answered)
        self._manager.register_event(EVENT_DIAL_ANSWER, self._on_answered)

    # -- pyst2 callbacks: these run on pyst2's own background thread. ------

    def _on_newchannel(self, event: object, manager: Manager) -> None:
        del manager
        if self.tracker.handle_newchannel(dict(event.headers)):
            self._notify(DIRECTION_INCOMING)

    def _on_newexten(self, event: object, manager: Manager) -> None:
        del manager
        headers = dict(event.headers)
        if self.tracker.handle_newexten(headers):
            self._notify(DIRECTION_OUTGOING)
            return
        channel = headers.get("Channel", "")
        if channel:
            self._schedule_pending_outgoing_check(channel)

    def _on_dial(self, event: object, manager: Manager) -> None:
        del manager
        if self.tracker.handle_dial(dict(event.headers)):
            self._notify(DIRECTION_OUTGOING)

    def _on_answered(self, event: object, manager: Manager) -> None:
        del manager
        incoming_changed, outgoing_changed = self.tracker.handle_answered(
            dict(event.headers)
        )
        if incoming_changed:
            self._notify(DIRECTION_INCOMING)
        if outgoing_changed:
            self._notify(DIRECTION_OUTGOING)

    def _on_hangup(self, event: object, manager: Manager) -> None:
        del manager
        incoming_changed, outgoing_changed = self.tracker.handle_hangup(
            dict(event.headers)
        )
        if incoming_changed:
            self._notify(DIRECTION_INCOMING)
        if outgoing_changed:
            self._notify(DIRECTION_OUTGOING)

    def _schedule_pending_outgoing_check(self, channel: str) -> None:
        """Ask the event loop to confirm a fallback match after the grace delay.

        Called from pyst2's callback thread, so the scheduling itself has to
        cross onto the event loop too; async_call_later is not thread-safe.
        """
        self._hass.loop.call_soon_threadsafe(
            async_call_later,
            self._hass,
            _PENDING_OUTGOING_DELAY,
            lambda _now: self._confirm_pending_outgoing(channel),
        )

    def _confirm_pending_outgoing(self, channel: str) -> None:
        if self.tracker.confirm_pending_outgoing(channel):
            self._notify(DIRECTION_OUTGOING)

    def _notify(self, direction: str) -> None:
        """Tell the sensors a call slot changed. Safe to call from any thread."""
        asyncio.run_coroutine_threadsafe(self._async_notify(direction), self._hass.loop)

    async def _async_notify(self, direction: str) -> None:
        async_dispatcher_send(self._hass, SIGNAL_CALL_UPDATED, direction)

    async def _async_watchdog(self, now: object) -> None:
        """Reconnect a dropped connection and drop stuck calls."""
        del now
        if not self.is_connected:
            _LOGGER.warning(
                "AMI connection to %s:%s is down; reconnecting", self._host, self._port
            )
            try:
                await self._hass.async_add_executor_job(self._connect_and_login)
            except (ManagerSocketException, ManagerAuthException) as err:
                _LOGGER.warning(
                    "Reconnect to %s:%s failed: %s", self._host, self._port, err
                )
                return
            self._register_event_handlers()
            _LOGGER.info("Reconnected to AMI at %s:%s", self._host, self._port)

        incoming_changed, outgoing_changed = self.tracker.prune_stale(
            STUCK_CALL_TIMEOUT
        )
        if incoming_changed:
            async_dispatcher_send(self._hass, SIGNAL_CALL_UPDATED, DIRECTION_INCOMING)
        if outgoing_changed:
            async_dispatcher_send(self._hass, SIGNAL_CALL_UPDATED, DIRECTION_OUTGOING)
