import math
from fractions import Fraction
from typing import Literal

AnswerFormat = Literal["integer", "fraction", "decimal"]


def tolerance_for(fmt: AnswerFormat, decimal_places: int | None) -> float:
    """How far a submitted answer may be from the exact value and still count as correct."""
    if fmt == "decimal":
        return 0.5 * 10 ** -(decimal_places if decimal_places is not None else 4)
    return 0.0


def display_answer(value: float, fmt: AnswerFormat, decimal_places: int | None) -> str:
    if fmt == "integer":
        return str(round(value))
    if fmt == "fraction":
        f = Fraction(value).limit_denominator(10**6)
        return str(f.numerator) if f.denominator == 1 else f"{f.numerator}/{f.denominator}"
    return f"{value:.{decimal_places if decimal_places is not None else 4}f}"


def answers_agree(a: float, b: float, tolerance: float) -> bool:
    # A small relative epsilon absorbs float noise, e.g. 0.1 + 0.2 vs 0.3.
    return abs(a - b) <= tolerance + 1e-9 * max(1.0, abs(a), abs(b))


def parse_number(text: str) -> float | None:
    """Parse '42', '-3.5', '1e-3' or a fraction 'p/q'. Returns None for anything else, inf or nan."""
    text = text.strip().rstrip(".").replace(",", "")
    if not text:
        return None
    try:
        value = float(Fraction(text)) if "/" in text else float(text)
    except (ValueError, ZeroDivisionError):
        return None
    return value if math.isfinite(value) else None
