"""Tests for the AMI event classification logic."""

from __future__ import annotations

from custom_components.asterisk_call_monitor.call_tracker import CallState, CallTracker
from custom_components.asterisk_call_monitor.const import (
    STATUS_ANSWERED,
    STATUS_BUSY,
    STATUS_DIALING,
    STATUS_ENDED,
    STATUS_IDLE,
    STATUS_NO_ANSWER,
    STATUS_REJECTED,
    STATUS_RINGING,
)


class FakeClock:
    """A controllable clock so call age can be tested without real time."""

    def __init__(self, start: float = 1000.0) -> None:
        """Start the clock at a fixed, arbitrary timestamp."""
        self.now = start

    def __call__(self) -> float:
        """Return the current fake time."""
        return self.now

    def advance(self, seconds: float) -> None:
        """Move the clock forward."""
        self.now += seconds


def _tracker(**overrides) -> CallTracker:
    """Return a tracker with sensible defaults for the household's own setup."""
    clock = FakeClock()
    kwargs = {
        "excluded_extensions": ["100"],
        "min_external_digits": 5,
        "now": clock,
    }
    kwargs.update(overrides)
    tracker = CallTracker(**kwargs)
    tracker.clock = clock  # type: ignore[attr-defined]
    return tracker


# -- Incoming: Newchannel -----------------------------------------------


def test_ringing_external_channel_starts_an_incoming_call() -> None:
    """A Ring channel from a real caller is reported as incoming."""
    tracker = _tracker()

    changed = tracker.handle_newchannel(
        {
            "Channel": "PJSIP/trunk-001",
            "ChannelStateDesc": "Ring",
            "CallerIDNum": "0031612345678",
        }
    )

    assert changed is True
    assert tracker.incoming.status == STATUS_RINGING
    assert tracker.incoming.phonenumber == "0031612345678"
    assert tracker.incoming.channel == "PJSIP/trunk-001"


def test_ringing_internal_handset_is_ignored() -> None:
    """The household's own handset (extension 100) never counts as a caller."""
    tracker = _tracker()

    changed = tracker.handle_newchannel(
        {"Channel": "PJSIP/100-001", "ChannelStateDesc": "Ring", "CallerIDNum": "100"}
    )

    assert changed is False
    assert tracker.incoming.status == STATUS_IDLE


def test_non_ringing_channel_is_ignored() -> None:
    """A channel that is not in the Ring state is not a new incoming call."""
    tracker = _tracker()

    changed = tracker.handle_newchannel(
        {
            "Channel": "PJSIP/trunk-001",
            "ChannelStateDesc": "Up",
            "CallerIDNum": "0031612345678",
        }
    )

    assert changed is False


# -- Outgoing: Newexten + Dial --------------------------------------------


def test_newexten_with_dial_application_starts_an_outgoing_call() -> None:
    """A Dial application in Newexten's AppData registers the call right away."""
    tracker = _tracker()

    changed = tracker.handle_newexten(
        {
            "Channel": "PJSIP/100-002",
            "Application": "Dial",
            "AppData": "SIP/trunk/0031612345678,60,g",
        }
    )

    assert changed is True
    assert tracker.outgoing.status == STATUS_DIALING
    assert tracker.outgoing.phonenumber == "0031612345678"


def test_newexten_bare_extension_is_only_pending() -> None:
    """A long digit extension alone does not register a call outright."""
    tracker = _tracker()

    changed = tracker.handle_newexten(
        {"Channel": "PJSIP/100-003", "Extension": "0031687654321"}
    )

    assert changed is False
    assert tracker.outgoing.status == STATUS_IDLE


def test_confirm_pending_outgoing_registers_an_unconfirmed_fallback_match() -> None:
    """When no Dial event supersedes it, the pending fallback match is confirmed."""
    tracker = _tracker()
    tracker.handle_newexten({"Channel": "PJSIP/100-003", "Extension": "0031687654321"})

    confirmed = tracker.confirm_pending_outgoing("PJSIP/100-003")

    assert confirmed is True
    assert tracker.outgoing.status == STATUS_DIALING
    assert tracker.outgoing.phonenumber == "0031687654321"


def test_confirm_pending_outgoing_is_a_noop_once_dial_already_registered_it() -> None:
    """A Dial event that already claimed the channel is not overwritten."""
    tracker = _tracker()
    tracker.handle_newexten({"Channel": "PJSIP/100-003", "Extension": "0031687654321"})
    tracker.handle_dial(
        {"Channel": "PJSIP/100-003", "Dialstring": "SIP/trunk/0031699999999"}
    )

    confirmed = tracker.confirm_pending_outgoing("PJSIP/100-003")

    assert confirmed is False
    assert tracker.outgoing.phonenumber == "0031699999999"


def test_dial_event_cleans_the_destination_number() -> None:
    """Protocol prefixes, @domain suffixes and trailing parameters are stripped."""
    tracker = _tracker()

    tracker.handle_dial(
        {"Channel": "PJSIP/100-004", "Dialstring": "PJSIP/0031612345678@trunk"}
    )
    assert tracker.outgoing.phonenumber == "0031612345678"

    tracker2 = _tracker()
    tracker2.handle_dial(
        {"Channel": "PJSIP/100-005", "Dialstring": "SIP/trunk/0031612345678,60,g"}
    )
    assert tracker2.outgoing.phonenumber == "0031612345678"


def test_dial_falls_back_to_dest_caller_id_when_no_dialstring() -> None:
    """A Dial event without a Dialstring still registers via DestCallerIDNum."""
    tracker = _tracker()

    changed = tracker.handle_dial(
        {"Channel": "PJSIP/100-006", "DestCallerIDNum": "0031611112222"}
    )

    assert changed is True
    assert tracker.outgoing.phonenumber == "0031611112222"


def test_dial_without_any_destination_does_nothing() -> None:
    """A Dial event that names no destination at all changes nothing."""
    tracker = _tracker()

    changed = tracker.handle_dial({"Channel": "PJSIP/100-007"})

    assert changed is False
    assert tracker.outgoing.status == STATUS_IDLE


def test_dial_ringing_a_household_extension_is_not_an_outgoing_call() -> None:
    """FreePBX ringing extension 100 to deliver an incoming call is not outgoing.

    Regression test: an incoming call's own dialplan can ring a handset via
    a Dial() application step (e.g. AppData "PJSIP/100,20,tI") to deliver
    the call - which matches the exact same "Application: Dial" pattern
    used to detect a real outbound call, and used to register the
    household's own extension as a bogus outgoing destination.
    """
    tracker = _tracker()

    changed = tracker.handle_newexten(
        {
            "Channel": "PJSIP/trunk-001",
            "Application": "Dial",
            "AppData": "PJSIP/100,20,tI",
        }
    )

    assert changed is False
    assert tracker.outgoing.status == STATUS_IDLE


def test_unrelated_dial_event_does_not_clobber_an_in_progress_call() -> None:
    """A Dial event for a different channel never overwrites the real call.

    Regression test: FreePBX's own dialplan can emit an extra Dial event
    for a channel unrelated to the actual outbound call (a macro or
    Local-channel hop), which used to silently overwrite the correctly
    detected destination - even with something like the dialing extension
    itself, e.g. "sip:100".
    """
    tracker = _tracker()
    tracker.handle_dial(
        {"Channel": "PJSIP/100-001", "Dialstring": "SIP/trunk/0031612345678"}
    )

    changed = tracker.handle_dial(
        {"Channel": "Local/100@from-internal-00000042", "Dialstring": "sip:100"}
    )

    assert changed is False
    assert tracker.outgoing.phonenumber == "0031612345678"
    assert tracker.outgoing.channel == "PJSIP/100-001"


def test_related_dial_event_still_refines_the_tracked_call() -> None:
    """A second Dial event for the SAME channel is a legitimate refinement."""
    tracker = _tracker()
    tracker.handle_dial(
        {"Channel": "PJSIP/100-001", "DestCallerIDNum": "0031612340000"}
    )

    changed = tracker.handle_dial(
        {"Channel": "PJSIP/100-001", "Dialstring": "SIP/trunk/0031612345678"}
    )

    assert changed is True
    assert tracker.outgoing.phonenumber == "0031612345678"


def test_dial_event_to_a_household_extension_does_not_clobber_a_real_call() -> None:
    """The same false-positive via handle_dial does not overwrite a real call."""
    tracker = _tracker()
    tracker.handle_dial(
        {"Channel": "PJSIP/100-001", "Dialstring": "SIP/trunk/0031612345678"}
    )

    changed = tracker.handle_dial(
        {"Channel": "PJSIP/trunk-002", "Dialstring": "PJSIP/100"}
    )

    assert changed is False
    assert tracker.outgoing.phonenumber == "0031612345678"


def test_a_new_outgoing_call_can_start_right_after_the_previous_one_ended() -> None:
    """A finished call does not block a genuinely new one from being tracked."""
    tracker = _tracker()
    tracker.handle_dial(
        {"Channel": "PJSIP/100-001", "Dialstring": "SIP/trunk/0031612345678"}
    )
    tracker.handle_hangup(
        {"Channel": "PJSIP/100-001", "Cause": "16", "Cause-txt": "Normal Clearing"}
    )

    changed = tracker.handle_dial(
        {"Channel": "PJSIP/100-002", "Dialstring": "SIP/trunk/0031699999999"}
    )

    assert changed is True
    assert tracker.outgoing.phonenumber == "0031699999999"


# -- Answered ---------------------------------------------------------------


def test_answered_event_marks_the_matching_incoming_call() -> None:
    """A BridgeEnter/DialAnswer-style event answers the matching incoming call."""
    tracker = _tracker()
    tracker.handle_newchannel(
        {
            "Channel": "PJSIP/trunk-001",
            "ChannelStateDesc": "Ring",
            "CallerIDNum": "0031612345678",
        }
    )

    incoming_changed, outgoing_changed = tracker.handle_answered(
        {"Channel": "PJSIP/trunk-001"}
    )

    assert incoming_changed is True
    assert outgoing_changed is False
    assert tracker.incoming.status == STATUS_ANSWERED


def test_answered_event_matches_outgoing_via_dest_channel() -> None:
    """An answer event can reach the outgoing call through DestChannel too."""
    tracker = _tracker()
    tracker.handle_dial(
        {"Channel": "PJSIP/100-002", "Dialstring": "SIP/trunk/0031612345678"}
    )

    incoming_changed, outgoing_changed = tracker.handle_answered(
        {"Channel": "PJSIP/trunk-099", "DestChannel": "PJSIP/100-002"}
    )

    assert incoming_changed is False
    assert outgoing_changed is True
    assert tracker.outgoing.status == STATUS_ANSWERED


def test_answered_event_for_an_unrelated_channel_changes_nothing() -> None:
    """An answer event for a channel that is not tracked changes nothing."""
    tracker = _tracker()
    tracker.handle_newchannel(
        {
            "Channel": "PJSIP/trunk-001",
            "ChannelStateDesc": "Ring",
            "CallerIDNum": "0031612345678",
        }
    )

    incoming_changed, outgoing_changed = tracker.handle_answered(
        {"Channel": "PJSIP/other-999"}
    )

    assert (incoming_changed, outgoing_changed) == (False, False)
    assert tracker.incoming.status == STATUS_RINGING


# -- Hangup -------------------------------------------------------------


def test_hangup_after_ringing_is_rejected() -> None:
    """A call that hangs up (cause 16) while still ringing is rejected, not ended."""
    tracker = _tracker()
    tracker.handle_newchannel(
        {
            "Channel": "PJSIP/trunk-001",
            "ChannelStateDesc": "Ring",
            "CallerIDNum": "0031612345678",
        }
    )

    incoming_changed, _ = tracker.handle_hangup(
        {"Channel": "PJSIP/trunk-001", "Cause": "16", "Cause-txt": "Normal Clearing"}
    )

    assert incoming_changed is True
    assert tracker.incoming.status == STATUS_REJECTED
    assert tracker.incoming.cause == "16"


def test_hangup_after_answered_is_ended() -> None:
    """A call that hangs up (cause 16) after being answered is ended normally."""
    tracker = _tracker()
    tracker.handle_newchannel(
        {
            "Channel": "PJSIP/trunk-001",
            "ChannelStateDesc": "Ring",
            "CallerIDNum": "0031612345678",
        }
    )
    tracker.handle_answered({"Channel": "PJSIP/trunk-001"})

    tracker.handle_hangup(
        {"Channel": "PJSIP/trunk-001", "Cause": "16", "Cause-txt": "Normal Clearing"}
    )

    assert tracker.incoming.status == STATUS_ENDED


def test_hangup_with_busy_cause() -> None:
    """Cause 17 is reported as busy, regardless of prior status."""
    tracker = _tracker()
    tracker.handle_dial(
        {"Channel": "PJSIP/100-002", "Dialstring": "SIP/trunk/0031612345678"}
    )

    tracker.handle_hangup(
        {"Channel": "PJSIP/100-002", "Cause": "17", "Cause-txt": "User busy"}
    )

    assert tracker.outgoing.status == STATUS_BUSY


def test_hangup_with_no_answer_cause() -> None:
    """Cause 19 is reported as not answered."""
    tracker = _tracker()
    tracker.handle_dial(
        {"Channel": "PJSIP/100-002", "Dialstring": "SIP/trunk/0031612345678"}
    )

    tracker.handle_hangup(
        {"Channel": "PJSIP/100-002", "Cause": "19", "Cause-txt": "No answer"}
    )

    assert tracker.outgoing.status == STATUS_NO_ANSWER


def test_hangup_clears_a_pending_outgoing_match_for_that_channel() -> None:
    """A Newexten fallback that never got confirmed is dropped on hangup too."""
    tracker = _tracker()
    tracker.handle_newexten({"Channel": "PJSIP/100-003", "Extension": "0031687654321"})

    tracker.handle_hangup(
        {"Channel": "PJSIP/100-003", "Cause": "16", "Cause-txt": "Normal Clearing"}
    )

    assert tracker.confirm_pending_outgoing("PJSIP/100-003") is False


def test_hangup_for_an_unrelated_channel_changes_nothing() -> None:
    """A hangup for a channel that is not tracked in either slot is a no-op."""
    tracker = _tracker()
    tracker.handle_newchannel(
        {
            "Channel": "PJSIP/trunk-001",
            "ChannelStateDesc": "Ring",
            "CallerIDNum": "0031612345678",
        }
    )

    incoming_changed, outgoing_changed = tracker.handle_hangup(
        {"Channel": "PJSIP/other-999", "Cause": "16", "Cause-txt": "Normal Clearing"}
    )

    assert (incoming_changed, outgoing_changed) == (False, False)
    assert tracker.incoming.status == STATUS_RINGING


# -- Stale call pruning ---------------------------------------------------


def test_prune_stale_clears_an_old_call() -> None:
    """A call that has not changed in longer than max_age is dropped."""
    clock = FakeClock()
    tracker = CallTracker(["100"], 5, now=clock)
    tracker.handle_newchannel(
        {
            "Channel": "PJSIP/trunk-001",
            "ChannelStateDesc": "Ring",
            "CallerIDNum": "0031612345678",
        }
    )

    clock.advance(3601)
    incoming_changed, outgoing_changed = tracker.prune_stale(3600)

    assert incoming_changed is True
    assert outgoing_changed is False
    assert tracker.incoming.status == STATUS_IDLE


def test_prune_stale_leaves_a_fresh_call_alone() -> None:
    """A recent call is not pruned."""
    clock = FakeClock()
    tracker = CallTracker(["100"], 5, now=clock)
    tracker.handle_newchannel(
        {
            "Channel": "PJSIP/trunk-001",
            "ChannelStateDesc": "Ring",
            "CallerIDNum": "0031612345678",
        }
    )

    clock.advance(10)
    incoming_changed, outgoing_changed = tracker.prune_stale(3600)

    assert (incoming_changed, outgoing_changed) == (False, False)
    assert tracker.incoming.status == STATUS_RINGING


def test_prune_stale_leaves_idle_slots_alone() -> None:
    """Pruning never touches a slot with no active call."""
    tracker = _tracker()

    incoming_changed, outgoing_changed = tracker.prune_stale(3600)

    assert (incoming_changed, outgoing_changed) == (False, False)


def test_prune_stale_is_based_on_the_last_change_not_the_call_start() -> None:
    """A call answered recently is not pruned just because it started long ago."""
    clock = FakeClock()
    tracker = CallTracker(["100"], 5, now=clock)
    tracker.handle_newchannel(
        {
            "Channel": "PJSIP/trunk-001",
            "ChannelStateDesc": "Ring",
            "CallerIDNum": "0031612345678",
        }
    )

    clock.advance(3000)
    tracker.handle_answered({"Channel": "PJSIP/trunk-001"})
    clock.advance(3000)  # 6000s since ringing started, but 3000s since answered
    incoming_changed, _ = tracker.prune_stale(3600)

    assert incoming_changed is False
    assert tracker.incoming.status == STATUS_ANSWERED


# -- Restoring after a restart ---------------------------------------------


def test_restore_populates_an_idle_slot() -> None:
    """A call state saved before a restart is adopted while the slot is idle."""
    tracker = _tracker()

    tracker.restore(
        "incoming",
        CallState(
            status=STATUS_ANSWERED,
            phonenumber="0031612345678",
            channel="PJSIP/trunk-001",
            started_at=900.0,
            updated_at=950.0,
        ),
    )

    assert tracker.incoming.status == STATUS_ANSWERED
    assert tracker.incoming.phonenumber == "0031612345678"
    assert tracker.incoming.updated_at == 950.0


def test_restore_drops_the_old_channel_id() -> None:
    """The restored channel id is not reused, so it cannot false-match a new event."""
    tracker = _tracker()

    tracker.restore(
        "incoming",
        CallState(status=STATUS_ENDED, channel="PJSIP/trunk-001"),
    )

    assert tracker.incoming.channel is None


def test_restore_never_overwrites_an_active_call() -> None:
    """A real event that already arrived is never clobbered by restored data."""
    tracker = _tracker()
    tracker.handle_newchannel(
        {
            "Channel": "PJSIP/trunk-002",
            "ChannelStateDesc": "Ring",
            "CallerIDNum": "0031699999999",
        }
    )

    tracker.restore(
        "incoming",
        CallState(status=STATUS_ENDED, phonenumber="0031612345678"),
    )

    assert tracker.incoming.status == STATUS_RINGING
    assert tracker.incoming.phonenumber == "0031699999999"
