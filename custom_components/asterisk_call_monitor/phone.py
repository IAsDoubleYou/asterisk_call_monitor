"""Phone number normalisation for the call sensors.

Kept free of Home Assistant imports on purpose, like call_tracker.py, so it
can be unit tested on its own. Asterisk reports a number exactly as the
dialplan hands it over: an incoming caller usually as FreePBX received it
(often national, "0123456789"), an outgoing destination as the outbound
route sends it to the trunk (often international, "0031123456789"). This
turns either into one uniform national and international form.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat

# Country calling code prefix of an international number that is written
# with the "00" dialling prefix and no country to read it against.
_INTERNATIONAL_PREFIX = "00"


@dataclass(frozen=True)
class PhoneNumbers:
    """A phone number in a national and an international form.

    A form is None when it cannot be determined with the information at hand.
    """

    national: str | None = None
    international: str | None = None


_UNKNOWN = PhoneNumbers()


def _region(country: str | None) -> str | None:
    """Return the country as an upper case region code, or None when unknown."""
    if not country:
        return None
    region = country.strip().upper()
    return region if region in phonenumbers.SUPPORTED_REGIONS else None


@lru_cache(maxsize=128)
def normalize(raw: str | None, country: str | None) -> PhoneNumbers:
    """Return the national and international form of a number.

    The international form is the E.164 notation ("+31123456789"), the
    national form only digits, with the national trunk prefix ("0123456789").
    Without a known country, a number that is already international ("+" or
    "00" notation) still gets its international form, and the national form
    stays empty. The national form is also left empty for a number from
    another country than the given one: its national notation would be
    meaningless next to local numbers, and could even collide with one.
    Anything that is not a plausible phone number (an internal extension, a
    short code, "anonymous") gives an empty result.
    """
    if not raw:
        return _UNKNOWN

    text = raw.strip()
    region = _region(country)
    if region is None and text.startswith(_INTERNATIONAL_PREFIX):
        text = f"+{text[len(_INTERNATIONAL_PREFIX) :]}"

    try:
        number = phonenumbers.parse(text, region)
    except NumberParseException:
        return _UNKNOWN
    if not phonenumbers.is_possible_number(number):
        return _UNKNOWN

    international = phonenumbers.format_number(number, PhoneNumberFormat.E164)
    if region is None or number.country_code != phonenumbers.country_code_for_region(
        region
    ):
        return PhoneNumbers(international=international)

    national = "".join(
        ch
        for ch in phonenumbers.format_number(number, PhoneNumberFormat.NATIONAL)
        if ch.isdigit()
    )
    return PhoneNumbers(national=national, international=international)


def warm_up(country: str | None) -> None:
    """Load the metadata of a country, so the first real call does not.

    Meant to run in an executor: the metadata of a region is read from disk
    the first time a number of it is parsed.
    """
    normalize.cache_clear()
    normalize("0123456789", country)
