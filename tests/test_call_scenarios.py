"""Whole-call scenarios, replayed from event sequences seen on a real FreePBX.

The events are reduced to the fields the tracker reads, and every number and
channel name is made up. What matters is the order and the channels: a trunk
channel of an outgoing call starts as "Down" (never "Ring"), and the own
handset and the trunk hang up as two separate events.
"""

from __future__ import annotations

from custom_components.asterisk_call_monitor.call_tracker import CallTracker
from custom_components.asterisk_call_monitor.const import (
    STATUS_ANSWERED,
    STATUS_DIALING,
    STATUS_ENDED,
    STATUS_IDLE,
    STATUS_RINGING,
)

HANDSET = "PJSIP/100-0000001a"
OUT_TRUNK = "PJSIP/trunk-0000001b"
IN_TRUNK = "PJSIP/provider-0000001e"
IN_HANDSET = "PJSIP/100-0000001f"
DESTINATION = "0031612345678"
CALLER = "0612345678"


def _tracker() -> CallTracker:
    return CallTracker(excluded_extensions=["100"], min_external_digits=5)


def _outgoing_call_until_dialing(tracker: CallTracker) -> None:
    """Replay the start of an outgoing call: handset rings, trunk is created."""
    assert not tracker.handle_newchannel(
        {
            "Channel": HANDSET,
            "ChannelStateDesc": "Ring",
            "CallerIDNum": "100",
            "Exten": "0612345678",
        }
    )
    assert tracker.handle_newexten(
        {
            "Channel": HANDSET,
            "ChannelStateDesc": "Ring",
            "CallerIDNum": "100",
            "Extension": DESTINATION,
            "Application": "Dial",
            "AppData": f"PJSIP/{DESTINATION}@trunk,300,Tb(some-macro^s^1,(6))",
        }
    )
    # The trunk channel starts as "Down", so it is not an incoming call.
    assert not tracker.handle_newchannel(
        {
            "Channel": OUT_TRUNK,
            "ChannelStateDesc": "Down",
            "CallerIDNum": "<unknown>",
        }
    )


def test_outgoing_call_answered_and_ended() -> None:
    """An answered outgoing call is tracked from dialing to ended."""
    tracker = _tracker()

    _outgoing_call_until_dialing(tracker)
    assert tracker.outgoing.status == STATUS_DIALING
    assert tracker.outgoing.phonenumber == DESTINATION
    assert tracker.incoming.status == STATUS_IDLE

    # The trunk joins the bridge first, then the handset.
    assert tracker.handle_answered(
        {"Channel": OUT_TRUNK, "Uniqueid": "1000000000.41"}
    ) == (False, False)
    assert tracker.handle_answered(
        {"Channel": HANDSET, "Uniqueid": "1000000000.40"}
    ) == (False, True)
    assert tracker.outgoing.status == STATUS_ANSWERED

    # The trunk hangs up first: that is not yet the end of the tracked call.
    assert tracker.handle_hangup(
        {"Channel": OUT_TRUNK, "Cause": "16", "Cause-txt": "Normal Clearing"}
    ) == (False, False)
    assert tracker.outgoing.status == STATUS_ANSWERED

    assert tracker.handle_hangup(
        {"Channel": HANDSET, "Cause": "16", "Cause-txt": "Normal Clearing"}
    ) == (False, True)
    assert tracker.outgoing.status == STATUS_ENDED
    assert tracker.outgoing.cause == "16"
    assert tracker.outgoing.phonenumber == DESTINATION
    assert tracker.incoming.status == STATUS_IDLE


def test_incoming_call_answered_and_ended() -> None:
    """An incoming call rings on the trunk channel and ends with its hangup."""
    tracker = _tracker()

    assert tracker.handle_newchannel(
        {
            "Channel": IN_TRUNK,
            "ChannelStateDesc": "Ring",
            "CallerIDNum": CALLER,
            "Exten": "0123456789",
        }
    )
    assert tracker.incoming.status == STATUS_RINGING
    assert tracker.incoming.phonenumber == CALLER

    # Ringing the own handset is neither a second incoming nor an outgoing call.
    assert not tracker.handle_newchannel(
        {"Channel": IN_HANDSET, "ChannelStateDesc": "Down", "CallerIDNum": "100"}
    )
    assert not tracker.handle_newexten(
        {
            "Channel": IN_HANDSET,
            "ChannelStateDesc": "Down",
            "CallerIDNum": "100",
            "Extension": "9999",
            "Application": "AppDial",
            "AppData": "(Outgoing Line)",
        }
    )
    assert tracker.outgoing.status == STATUS_IDLE

    assert tracker.handle_answered(
        {"Channel": IN_TRUNK, "Uniqueid": "1000000001.46"}
    ) == (True, False)
    assert tracker.incoming.status == STATUS_ANSWERED

    # The handset hangs up before the trunk: only the trunk closes the call.
    assert tracker.handle_hangup(
        {"Channel": IN_HANDSET, "Cause": "16", "Cause-txt": "Normal Clearing"}
    ) == (False, False)
    assert tracker.incoming.status == STATUS_ANSWERED

    assert tracker.handle_hangup(
        {"Channel": IN_TRUNK, "Cause": "16", "Cause-txt": "Normal Clearing"}
    ) == (True, False)
    assert tracker.incoming.status == STATUS_ENDED
    assert tracker.incoming.cause == "16"
    assert tracker.incoming.phonenumber == CALLER
    assert tracker.outgoing.status == STATUS_IDLE
