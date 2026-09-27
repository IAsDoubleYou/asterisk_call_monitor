"""Constants for the Asterisk Call Monitor integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "asterisk_call_monitor"

# Connection keys.
CONF_HOST: Final = "host"
CONF_PORT: Final = "port"
CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"

# Options keys. Extensions in this list are internal handsets, not external
# callers, and are ignored by the incoming-call detection. The digit count is
# what tells an internal extension apart from an external number reached
# through Newexten's fallback path, when no Dial event names it directly.
CONF_EXCLUDED_EXTENSIONS: Final = "excluded_extensions"
CONF_MIN_EXTERNAL_DIGITS: Final = "min_external_digits"

DEFAULT_PORT: Final = 5038
# Matches the extension the production phone-monitor.py script has excluded
# from day one: the household's own handsets.
DEFAULT_EXCLUDED_EXTENSIONS: Final = ["100"]
DEFAULT_MIN_EXTERNAL_DIGITS: Final = 5

# A pooled AMI connection is worth little on its own; opening a fresh one is
# cheap and this only runs once at setup and on reconnect.
CONNECT_TIMEOUT: Final = 10
# How often the connection is checked and, if needed, reconnected.
RECONNECT_INTERVAL: Final = 30
# A call that has not changed status in this long is almost certainly a
# channel whose Hangup was missed; drop it rather than show it forever.
STUCK_CALL_TIMEOUT: Final = 3600

# Call status values. Kept in Dutch, matching the vocabulary the household's
# existing automations and the proven production script (phone-monitor.py)
# already use, so this integration is a drop-in replacement for that script
# rather than requiring every automation to be rewritten around new words.
STATUS_IDLE: Final = "idle"
STATUS_RINGING: Final = "bellen"
STATUS_DIALING: Final = "kiezen"
STATUS_ANSWERED: Final = "beantwoord"
STATUS_REJECTED: Final = "afgewezen"
STATUS_BUSY: Final = "bezet"
STATUS_NO_ANSWER: Final = "niet_beantwoord"
STATUS_ENDED: Final = "beeindigd"

# Hangup cause codes (ITU-T Q.850), used to tell a rejected call, a busy
# signal and an unanswered call apart when a channel is torn down.
CAUSE_NORMAL_CLEARING: Final = "16"
CAUSE_USER_BUSY: Final = "17"
CAUSE_NO_ANSWER: Final = "19"

# AMI events this integration listens for.
EVENT_NEWCHANNEL: Final = "Newchannel"
EVENT_NEWEXTEN: Final = "Newexten"
EVENT_DIAL: Final = "Dial"
EVENT_HANGUP: Final = "Hangup"
EVENT_BRIDGE_ENTER: Final = "BridgeEnter"
EVENT_DIAL_ANSWER: Final = "DialAnswer"

# Signal used to tell the sensors a call's state changed, dispatched with the
# call direction ("incoming" or "outgoing") as its only argument.
SIGNAL_CALL_UPDATED: Final = f"{DOMAIN}_call_updated"

DIRECTION_INCOMING: Final = "incoming"
DIRECTION_OUTGOING: Final = "outgoing"
