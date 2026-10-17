"""Numbers -> the words a correct TTS should say. The inverse of numparse.

Used twice: to list acceptable spoken forms for each test case, and (later) by
SafeSpeak to spell values out itself instead of trusting the TTS to.
"""

from __future__ import annotations

from decimal import Decimal

ONES = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen"
).split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def _below_100(n: int) -> str:
    if n < 20:
        return ONES[n]
    tens, ones = divmod(n, 10)
    return TENS[tens] + (f" {ONES[ones]}" if ones else "")


def _below_1000(n: int, and_: bool) -> str:
    hundreds, rest = divmod(n, 100)
    if not hundreds:
        return _below_100(rest)
    head = f"{ONES[hundreds]} hundred"
    if not rest:
        return head
    return f"{head} {'and ' if and_ else ''}{_below_100(rest)}"


def _join(parts: list[str], rest: int, and_: bool) -> str:
    # British style puts "and" before a trailing sub-hundred group: "one lakh and five".
    if rest:
        tail = _below_1000(rest, and_)
        parts.append(f"and {tail}" if and_ and parts and rest < 100 else tail)
    return " ".join(parts)


def international(n: int, and_: bool = False) -> str:
    if n == 0:
        return "zero"
    parts = []
    for scale, word in ((10**9, "billion"), (10**6, "million"), (10**3, "thousand")):
        if n >= scale:
            q, n = divmod(n, scale)
            parts.append(f"{_below_1000(q, and_)} {word}")
    return _join(parts, n, and_)


def indian(n: int, and_: bool = False) -> str:
    if n == 0:
        return "zero"
    parts = []
    crore, n = divmod(n, 10**7)
    if crore:
        parts.append(f"{indian(crore, and_)} crore")
    for scale, word in ((10**5, "lakh"), (10**3, "thousand")):
        if n >= scale:
            q, n = divmod(n, scale)
            parts.append(f"{_below_100(q)} {word}")
    return _join(parts, n, and_)


def digits(s: str) -> str:
    """Digit by digit: "022" -> "zero two two". Non-digits are dropped."""
    return " ".join(ONES[int(c)] for c in s if c.isdigit())


def decimal(x: int | float | str) -> list[str]:
    """Every acceptable reading of a decimal: 0.5 -> ["zero point five", "point five", ...]."""
    d = Decimal(str(x)).normalize()
    whole, _, frac = f"{d:f}".partition(".")
    whole_n = int(whole)
    if not frac:
        return cardinal(whole_n)
    frac_words = digits(frac)
    forms = [f"{w} point {frac_words}" for w in cardinal(whole_n)]
    if whole_n == 0:
        forms.append(f"point {frac_words}")
    return forms


def cardinal(n: int) -> list[str]:
    """All standard readings of an integer, Indian and international, with and without "and"."""
    forms = [indian(n), indian(n, True), international(n), international(n, True)]
    return list(dict.fromkeys(forms))
