"""Blocks prices the system never gave. A safety net under the prompt, not a replacement."""

import json
import re
from decimal import Decimal, InvalidOperation

NUMBER = r"\d[\d,]*(?:\.\d+)?"
CURRENCY = r"(?:tzs|tshs?|shs?|shilingi|shillings?)"
PRICE = re.compile(
    rf"\b{CURRENCY}\.?\s*(?P<after>{NUMBER})(?P<k1>k\b)?"
    rf"|(?P<before>{NUMBER})(?P<k2>k)?\s*(?:/[=-]|{CURRENCY}\b)"
    rf"|\belfu\s+(?P<thousands>{NUMBER})"
    rf"|(?<![\d,])(?P<grouped>\d{{1,3}}(?:,\d{{3}})+(?:\.\d+)?)"
    rf"|\b(?P<short>\d+)k\b",
    re.IGNORECASE,
)


def prices(text: str) -> set[Decimal]:
    """Every amount in `text` that reads as a price."""
    found = set()
    for match in PRICE.finditer(text):
        groups = match.groupdict()
        raw = next(
            groups[n] for n in ("after", "before", "thousands", "grouped", "short") if groups[n]
        )
        amount = _decimal(raw)
        if amount is not None:
            thousand = any(groups[n] for n in ("k1", "k2", "thousands", "short"))
            found.add(amount * 1000 if thousand else amount)
    return found


def numbers(text: str) -> set[Decimal]:
    return {n for n in map(_decimal, re.findall(NUMBER, text)) if n is not None} | prices(text)


def _decimal(raw) -> Decimal | None:
    try:
        return Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None


def known_prices(turns) -> set[Decimal]:
    """From tool results, our own notifications, and what the user wrote."""
    known = set()
    for turn in turns:
        if turn.role == "tool":
            known |= prices(json.dumps(turn.results, ensure_ascii=False))
        elif turn.role == "user":
            known |= numbers(turn.text)
        elif turn.raw is None:
            known |= prices(turn.text)
    return known
