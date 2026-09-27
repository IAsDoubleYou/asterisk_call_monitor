"""Pure call-state classification logic for Asterisk AMI events.

Kept free of Home Assistant and pyst2 imports on purpose, so the event
classification - the part most worth getting right - can be unit tested
without a real AMI connection or the Home Assistant test harness. Ported from
a proven production script (phone-monitor.py) that tracked every channel
independently; simplified to one slot per call direction, since this
household never has more than one call of each kind active at a time.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
import time

from .const import (
    CAUSE_NO_ANSWER,
    CAUSE_USER_BUSY,
    STATUS_ANSWERED,
    STATUS_BUSY,
    STATUS_DIALING,
    STATUS_ENDED,
    STATUS_IDLE,
    STATUS_NO_ANSWER,
    STATUS_REJECTED,
    STATUS_RINGING,
)


@dataclass(frozen=True)
class CallState:
    """The current state of one direction's call slot."""

    status: str = STATUS_IDLE
    phonenumber: str | None = None
    channel: str | None = None
    started_at: float | None = None
    cause: str | None = None
    cause_text: str | None = None

    @property
    def is_active(self) -> bool:
        """Return whether a call is currently tracked in this slot."""
        return self.status != STATUS_IDLE


_IDLE = CallState()


def _clean_destination(raw: str) -> str:
    """Strip a Dial-style channel string down to the bare number.

    A Dialstring/AppData value looks like "SIP/trunk/0031612345678,60,g" or
    "PJSIP/0031612345678@trunk"; only the number itself is kept.
    """
    destination = raw
    if "/" in destination:
        destination = destination.split("/")[-1]
    if "@" in destination:
        destination = destination.split("@")[0]
    if "," in destination:
        destination = destination.split(",")[0]
    return destination


class CallTracker:
    """Classify AMI events into at most one active incoming and outgoing call."""

    def __init__(
        self,
        excluded_extensions: list[str],
        min_external_digits: int,
        now: Callable[[], float] = time.time,
    ) -> None:
        """Store the settings that tell an internal extension from a real caller."""
        self._excluded_extensions = set(excluded_extensions)
        self._min_external_digits = min_external_digits
        self._now = now
        self.incoming: CallState = _IDLE
        self.outgoing: CallState = _IDLE
        # Channels seen in a Newexten fallback (bare-digit extension) match,
        # waiting to see whether a following Dial event supplies a cleaner
        # destination before they are confirmed as an outgoing call.
        self._pending_outgoing: dict[str, str] = {}

    def handle_newchannel(self, event: dict) -> bool:
        """Treat a ringing channel from a real caller as a new incoming call."""
        if event.get("ChannelStateDesc") != "Ring":
            return False

        caller_id = event.get("CallerIDNum", "")
        if caller_id in self._excluded_extensions:
            return False

        self.incoming = CallState(
            status=STATUS_RINGING,
            phonenumber=caller_id or None,
            channel=event.get("Channel", ""),
            started_at=self._now(),
        )
        return True

    def handle_newexten(self, event: dict) -> bool:
        """Look for the start of an outgoing call in a dialplan step.

        A Dial application with a destination registers the call right away.
        A bare-digit extension only registers a pending match: the caller
        should give a following Dial event a short window to supply a
        cleaner destination via confirm_pending_outgoing.
        """
        channel = event.get("Channel", "")
        application = event.get("Application", "")
        app_data = event.get("AppData", "")

        if application == "Dial" and app_data and "/" in app_data:
            self._start_outgoing(channel, _clean_destination(app_data))
            return True

        extension = event.get("Extension", "")
        if extension.isdigit() and len(extension) >= self._min_external_digits:
            self._pending_outgoing[channel] = extension

        return False

    def confirm_pending_outgoing(self, channel: str) -> bool:
        """Register a Newexten fallback match no Dial event has since covered."""
        extension = self._pending_outgoing.pop(channel, None)
        if extension is None or self.outgoing.channel == channel:
            return False
        self._start_outgoing(channel, extension)
        return True

    def handle_dial(self, event: dict) -> bool:
        """Register the outgoing call a Dial event usually names most cleanly."""
        channel = event.get("Channel", "")
        destination = (
            event.get("Dialstring")
            or event.get("DestCallerIDNum")
            or event.get("Destination")
            or self._pending_outgoing.get(channel)
        )
        if not destination:
            return False

        self._start_outgoing(channel, _clean_destination(destination))
        return True

    def _start_outgoing(self, channel: str, destination: str) -> None:
        self._pending_outgoing.pop(channel, None)
        self.outgoing = CallState(
            status=STATUS_DIALING,
            phonenumber=destination,
            channel=channel,
            started_at=self._now(),
        )

    def handle_answered(self, event: dict) -> tuple[bool, bool]:
        """Mark the matching call answered on a BridgeEnter/DialAnswer event."""
        channel = event.get("Channel", "")
        unique_id = event.get("Uniqueid", "")
        dest_channel = event.get("DestChannel", "")

        incoming_changed = False
        outgoing_changed = False

        if self.incoming.is_active and self._matches(
            self.incoming.channel, channel, unique_id
        ):
            self.incoming = replace(self.incoming, status=STATUS_ANSWERED)
            incoming_changed = True

        if self.outgoing.is_active and self._matches(
            self.outgoing.channel, channel, unique_id, dest_channel
        ):
            self.outgoing = replace(self.outgoing, status=STATUS_ANSWERED)
            outgoing_changed = True

        return incoming_changed, outgoing_changed

    def handle_hangup(self, event: dict) -> tuple[bool, bool]:
        """Close out the matching call with a final status on a Hangup event."""
        channel = event.get("Channel", "")
        cause = event.get("Cause", "")
        cause_text = event.get("Cause-txt", "")
        status = self._hangup_status(cause)

        incoming_changed = self._close_if_matching(
            "incoming", channel, status, cause, cause_text
        )
        outgoing_changed = self._close_if_matching(
            "outgoing", channel, status, cause, cause_text
        )
        self._pending_outgoing.pop(channel, None)
        return incoming_changed, outgoing_changed

    def _close_if_matching(
        self, direction: str, channel: str, status: str, cause: str, cause_text: str
    ) -> bool:
        current: CallState = getattr(self, direction)
        if not current.is_active or not self._channel_related(current.channel, channel):
            return False

        # A call that never got past ringing/dialing is rejected rather than
        # "ended": that status is reserved for one that was answered first.
        was_ringing = current.status in (STATUS_RINGING, STATUS_DIALING)
        final_status = (
            STATUS_REJECTED if status == STATUS_ENDED and was_ringing else status
        )

        setattr(
            self,
            direction,
            replace(current, status=final_status, cause=cause, cause_text=cause_text),
        )
        return True

    @staticmethod
    def _hangup_status(cause: str) -> str:
        if cause == CAUSE_USER_BUSY:
            return STATUS_BUSY
        if cause == CAUSE_NO_ANSWER:
            return STATUS_NO_ANSWER
        return STATUS_ENDED

    @staticmethod
    def _matches(tracked_channel: str | None, *candidates: str) -> bool:
        if not tracked_channel:
            return False
        return any(
            candidate
            and (
                candidate == tracked_channel
                or candidate in tracked_channel
                or tracked_channel in candidate
            )
            for candidate in candidates
        )

    @staticmethod
    def _channel_related(tracked_channel: str | None, channel: str) -> bool:
        if not tracked_channel or not channel:
            return False
        return (
            tracked_channel == channel
            or channel.startswith(tracked_channel)
            or tracked_channel.startswith(channel)
        )

    def prune_stale(self, max_age: float) -> tuple[bool, bool]:
        """Clear a call slot that has not changed in longer than max_age seconds."""
        now = self._now()
        incoming_changed = False
        outgoing_changed = False

        if (
            self.incoming.is_active
            and self.incoming.started_at is not None
            and now - self.incoming.started_at > max_age
        ):
            self.incoming = _IDLE
            incoming_changed = True

        if (
            self.outgoing.is_active
            and self.outgoing.started_at is not None
            and now - self.outgoing.started_at > max_age
        ):
            self.outgoing = _IDLE
            outgoing_changed = True

        return incoming_changed, outgoing_changed
