"""Tests for the phone number normalisation."""

from __future__ import annotations

import pytest

from custom_components.asterisk_call_monitor.phone import (
    PhoneNumbers,
    normalize,
    warm_up,
)

NATIONAL = "0123456789"
INTERNATIONAL = "+31123456789"


@pytest.mark.parametrize(
    "raw",
    [
        "0123456789",  # incoming, as FreePBX received it
        "0031123456789",  # outgoing, as the outbound route sends it
        "+31123456789",
        " 0031123456789 ",
    ],
)
def test_dutch_number_in_any_notation(raw: str) -> None:
    """Every notation of the same number gives the same two forms."""
    assert normalize(raw, "NL") == PhoneNumbers(
        national=NATIONAL, international=INTERNATIONAL
    )


def test_country_is_case_insensitive() -> None:
    """A lower case country code is read like an upper case one."""
    assert normalize("0031123456789", "nl").national == NATIONAL


def test_mobile_number() -> None:
    """A mobile number keeps its trunk prefix in the national form."""
    assert normalize("0031612345678", "NL") == PhoneNumbers(
        national="0612345678", international="+31612345678"
    )


@pytest.mark.parametrize("raw", ["0031123456789", "+31123456789"])
def test_unknown_country_keeps_an_international_number(raw: str) -> None:
    """Without a country, an international number only gets its international form."""
    assert normalize(raw, None) == PhoneNumbers(international=INTERNATIONAL)


@pytest.mark.parametrize("country", [None, "", "XX"])
def test_unknown_country_cannot_read_a_national_number(country: str | None) -> None:
    """A national number needs its country to be read at all."""
    assert normalize("0123456789", country) == PhoneNumbers()


def test_foreign_number_has_no_national_form() -> None:
    """A number from another country is never shown in its own national form."""
    assert normalize("0049301234567", "NL") == PhoneNumbers(
        international="+49301234567"
    )


@pytest.mark.parametrize(
    "raw", [None, "", "   ", "anonymous", "112", "*97", "abc", "100"]
)
def test_not_a_phone_number(raw: str | None) -> None:
    """Internal extensions, short codes and text give an empty result."""
    assert normalize(raw, "NL") == PhoneNumbers()


def test_warm_up_does_not_change_the_result() -> None:
    """Warming up a country leaves the results of that country as they were."""
    warm_up("NL")
    assert normalize("0031123456789", "NL").national == NATIONAL
