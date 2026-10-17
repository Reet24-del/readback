import random

import pytest

from readback import verbalize
from readback.numparse import parse_cardinal, to_digits


@pytest.mark.parametrize(
    "n, indian, international",
    [
        (150_000, "one lakh fifty thousand", "one hundred fifty thousand"),
        (12_499, "twelve thousand four hundred ninety nine", "twelve thousand four hundred ninety nine"),
        (25_000_000, "two crore fifty lakh", "twenty five million"),
        (1_000_000, "ten lakh", "one million"),
        (34_567_890, "three crore forty five lakh sixty seven thousand eight hundred ninety", "thirty four million five hundred sixty seven thousand eight hundred ninety"),
        (105, "one hundred five", "one hundred five"),
        (0, "zero", "zero"),
    ],
)
def test_readings(n, indian, international):
    assert verbalize.indian(n) == indian
    assert verbalize.international(n) == international


def test_british_and():
    assert verbalize.indian(100_005, and_=True) == "one lakh and five"
    assert verbalize.international(150_000, and_=True) == "one hundred and fifty thousand"


def test_decimal_forms():
    assert verbalize.decimal(0.5) == ["zero point five", "point five"]
    assert verbalize.decimal(2.5) == ["two point five"]
    assert verbalize.decimal(500) == ["five hundred"]


def test_digits():
    assert verbalize.digits("022-2345") == "zero two two two three four five"


def test_roundtrip_through_numparse():
    """Every reading verbalize produces must parse back to the same number."""
    rng = random.Random(7)
    numbers = [rng.randrange(0, 10**10) for _ in range(2_000)] + [rng.randrange(0, 10**5) for _ in range(500)]
    for n in numbers:
        for words in verbalize.cardinal(n):
            assert parse_cardinal(words.split()) == n, words


def test_decimal_roundtrip():
    for x in (0.5, 0.25, 2.5, 12.5, 75.5, 1.25):
        for words in verbalize.decimal(x):
            assert parse_cardinal(words.split()) == x, words


def test_digit_roundtrip():
    rng = random.Random(3)
    for _ in range(500):
        s = "".join(rng.choices("0123456789", k=rng.randrange(1, 13)))
        assert to_digits(verbalize.digits(s).split()) == s
