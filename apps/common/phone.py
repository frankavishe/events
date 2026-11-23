"""Phone normalization to E.164. Tanzanian local formats are converted to +255."""

import re

TZ_COUNTRY_CODE = "255"
# Tanzanian mobile subscriber numbers: 9 digits starting with 6 or 7.
_TZ_SUBSCRIBER = re.compile(r"^[67]\d{8}$")
_E164 = re.compile(r"^\+[1-9]\d{7,14}$")
_SEPARATORS = re.compile(r"[\s\-().]")


class InvalidPhoneNumber(ValueError):
    pass


def normalize_phone(raw: str) -> str:
    """Return `raw` as E.164 (`+2557XXXXXXXX`) or raise InvalidPhoneNumber."""
    if not isinstance(raw, str):
        raise InvalidPhoneNumber("Phone number must be a string.")
    value = _SEPARATORS.sub("", raw.strip())
    if not value:
        raise InvalidPhoneNumber("Phone number is required.")

    if value.startswith("+"):
        digits = value[1:]
    elif value.startswith("00"):
        digits = value[2:]
    elif value.startswith("0"):
        digits = TZ_COUNTRY_CODE + value[1:]
    elif value.startswith(TZ_COUNTRY_CODE):
        digits = value
    else:
        digits = TZ_COUNTRY_CODE + value

    if not digits.isdigit():
        raise InvalidPhoneNumber(f"Invalid phone number: {raw!r}")

    if digits.startswith(TZ_COUNTRY_CODE):
        if not _TZ_SUBSCRIBER.match(digits[len(TZ_COUNTRY_CODE) :]):
            raise InvalidPhoneNumber(f"Invalid Tanzanian mobile number: {raw!r}")
    elif not _E164.match("+" + digits):
        raise InvalidPhoneNumber(f"Invalid phone number: {raw!r}")

    return "+" + digits
