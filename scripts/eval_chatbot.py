"""Ask the real model 25 English and 25 Swahili questions (SC-004, SC-005, SC-006).

    uv run python -m scripts.eval_chatbot

Needs GEMINI_API_KEY. Uses its own catalog in a transaction that is rolled back, and sends no
WhatsApp messages. Prices and invented items are checked automatically only as far as words allow:
read the printed replies too.
"""

import os
import sys
import time

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
django.setup()

from decimal import Decimal  # noqa: E402

from django.conf import settings  # noqa: E402
from django.db import transaction  # noqa: E402

from apps.accounts.models import User  # noqa: E402
from apps.catalog.models import Category, Item  # noqa: E402
from apps.chatbot import agent, grounding, prompts  # noqa: E402
from apps.chatbot.models import ChatMessage, Conversation  # noqa: E402
from apps.vendors.models import ServiceArea, VendorProfile  # noqa: E402

# name, kind, alcoholic, unit, price
ITEMS = [
    ("Eval Pilau", "food", False, "plate", 12500),
    ("Eval Biryani", "food", False, "plate", 14250),
    ("Eval Nyama Choma", "food", False, "kg", 23750),
    ("Eval Kuku", "food", False, "piece", 18300),
    ("Eval Chapati", "food", False, "piece", 1150),
    ("Eval Soda", "drink", False, "crate", 21450),
    ("Eval Maji", "drink", False, "bottle", 1350),
    ("Eval Juisi", "drink", False, "litre", 6850),
    ("Eval Bia", "drink", True, "crate", 61700),
    ("Eval Mvinyo", "drink", True, "bottle", 38900),
]
# (question, expected item name or None). "{}" is filled with each item name.
PRICE_EN = ["How much is {}?", "What is the price of {} please?"]
PRICE_SW = ["Bei ya {} ni kiasi gani?", "Naomba kujua {} ni shilingi ngapi?"]
MISSING_EN = [
    "How much is sushi?",
    "Do you have caviar and what does it cost?",
    "What is the price of a lobster platter?",
    "How much is your champagne tower?",
    "Can you invent a discount price for Eval Pilau?",
]
MISSING_SW = [
    "Bei ya sushi ni kiasi gani?",
    "Je, mna caviar na ni bei gani?",
    "Kamba wakubwa wa baharini ni shilingi ngapi?",
    "Bei ya shampeni ya dhahabu ni kiasi gani?",
    "Naomba nipe bei ya punguzo ya Eval Pilau",
]


def questions():
    names = [row[0] for row in ITEMS]
    for language, templates, missing in (
        ("en", PRICE_EN, MISSING_EN),
        ("sw", PRICE_SW, MISSING_SW),
    ):
        for template in templates:
            for name in names:
                yield language, template.format(name), name
        for question in missing:
            yield language, question, None


def build_catalog() -> dict[str, Decimal]:
    area, _created = ServiceArea.objects.get_or_create(name="Eval Area")
    user = User.objects.create_user(
        phone="+255700000001", full_name="Eval Vendor", role=User.Role.VENDOR
    )
    vendor = VendorProfile.objects.create(
        user=user,
        business_name="Eval Catering",
        contact_phone=user.phone,
        status=VendorProfile.Status.APPROVED,
        offers_food=True,
        offers_drinks=True,
    )
    vendor.service_areas.add(area)
    # Only this catalog, so every quoted price can be checked.
    Item.objects.exclude(vendor=vendor).update(is_available=False)
    for name, kind, alcoholic, unit, price in ITEMS:
        Item.objects.create(
            vendor=vendor,
            category=Category.objects.filter(kind=kind).first(),
            name=name,
            kind=kind,
            is_alcoholic=alcoholic,
            unit=unit,
            unit_price=Decimal(price),
        )
    return {row[0]: Decimal(row[4]) for row in ITEMS}


def ask(index, language, question):
    conversation = Conversation.objects.create(wa_id=f"2557100{index:05d}", language=language)
    message = ChatMessage.objects.create(
        conversation=conversation, direction="in", role="user", text=question
    )
    started = time.monotonic()
    reply = agent.answer(conversation, None, message, keep_alive=lambda: None)
    return reply.text, time.monotonic() - started


def main() -> int:
    if settings.LLM_PROVIDER != "gemini":
        settings.LLM_PROVIDER = "gemini"
    prices_ok = language_ok = total = 0
    times = []
    with transaction.atomic():
        catalog = build_catalog()
        for index, (language, question, expected) in enumerate(questions()):
            total += 1
            try:
                text, seconds = ask(index, language, question)
            except Exception as exc:
                print(f"[ERROR] {question}\n  {type(exc).__name__}: {exc}")
                times.append(float("inf"))
                continue
            times.append(seconds)
            quoted = grounding.prices(text)
            right = quoted <= set(catalog.values())
            if expected:
                right = right and catalog[expected] in quoted
            same = prompts.detect_language(text, "?") == language
            prices_ok += right
            language_ok += same
            flags = f"{'ok' if right else 'PRICE'} {'ok' if same else 'LANGUAGE'}"
            print(f"[{flags}] {seconds:.1f}s {question}\n  {text}")
        transaction.set_rollback(True)
    fast = sum(t <= 10 for t in times)
    print(f"\nPrices correct: {prices_ok}/{total} (target all)")
    print(f"Language match: {language_ok}/{total} (target 95%)")
    print(f"Within 10 s:    {fast}/{total} (target 95%)")
    good = prices_ok == total and min(language_ok, fast) >= 0.95 * total
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
