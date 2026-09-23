"""Check that a model did not produce any number of its own.

The design rule is that Pandas computes every figure and the model only
explains. This makes the rule enforceable: every number in the model's text
must match a number in the facts it was given, allowing only for rounding.
Anything else (a sum, a difference, a percentage it worked out, a figure it
invented) is rejected, and the caller falls back to rule-based text.

This is strict on purpose. A false alarm costs a nicer paragraph; a missed
one puts a wrong number in front of someone who trusts it.

Signs are compared loosely: "fell 3.5%" for a change of -3.5 is wording, not
arithmetic. That means the check can't catch a model describing a drop as a
rise; it only guarantees the magnitudes came from the facts.
"""

import json
import re
from decimal import Decimal, InvalidOperation

# A number not glued to a word or another number: "12,500", "-3.5", "98%", "2024".
# The lookbehind stops "2024-01-05" from producing "-01", and "Q3" or "v2" from producing digits.
NUMBER = re.compile(r"(?<![\w.])-?\d+(?:,\d{3})*(?:\.\d+)?")


def numbers_in(text: str) -> list[str]:
    return NUMBER.findall(text)


def ungrounded_numbers(text: str, facts: dict | list | str) -> list[str]:
    """Numbers in `text` that don't match any number in `facts`, in order of appearance."""
    fact_text = facts if isinstance(facts, str) else json.dumps(facts, default=str)
    fact_values = {value for n in numbers_in(fact_text) if (value := _to_decimal(n)) is not None}

    return [raw for raw in numbers_in(text) if not _matches_any(raw, fact_values)]


def _matches_any(raw: str, fact_values: set[Decimal]) -> bool:
    value = _to_decimal(raw)
    if value is None:
        return True
    # Written to 2 decimals means the true value may differ by up to 0.005.
    decimals = len(raw.split(".")[1]) if "." in raw else 0
    tolerance = Decimal("0.5") * Decimal(10) ** -decimals
    return any(abs(abs(fact) - abs(value)) <= tolerance for fact in fact_values)


def _to_decimal(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None
