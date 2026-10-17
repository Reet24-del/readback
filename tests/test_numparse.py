import pytest

from readback.numparse import find_numbers, parse_cardinal, to_digits


def only(text):
    spans = find_numbers(text)
    assert len(spans) == 1, spans
    return spans[0]


@pytest.mark.parametrize(
    "words, value",
    [
        ("twenty five", 25),
        ("one hundred and five", 105),
        ("fifteen hundred", 1500),
        ("one lakh fifty thousand", 150_000),
        ("two lakh", 200_000),
        ("a lakh", 100_000),
        ("two point five crore", 25_000_000),
        ("zero point five", 0.5),
        ("point five", 0.5),
        ("four hundred ninety nine", 499),
        ("ten crore twenty lakh", 102_000_000),
        ("two thousand twenty six", 2026),
    ],
)
def test_cardinal_values(words, value):
    assert parse_cardinal(words.split()) == value


@pytest.mark.parametrize("words", ["five five", "twenty thirty", "nine eight seven", "point"])
def test_ungrammatical_cardinals_are_rejected(words):
    assert parse_cardinal(words.split()) is None


@pytest.mark.parametrize(
    "words, digits",
    [
        ("nine eight seven six five four three two one zero", "9876543210"),
        ("ninety eight seven six five", "98765"),
        ("double five", "55"),
        ("triple nine one", "9991"),
        ("one eight hundred", "1800"),
        ("eighteen hundred", "1800"),
        ("zero two two", "022"),
        ("oh two two", "022"),
        ("twenty twenty six", "2026"),
    ],
)
def test_digit_strings(words, digits):
    assert to_digits(words.split()) == digits


def test_dose_in_sentence():
    span = only("Take zero point five milligrams of clonazepam at night.")
    assert span.value == 0.5
    assert span.text == "zero point five"


def test_misread_dose_is_visible():
    assert only("Take five milligrams at night.").value == 5


def test_indian_money_in_sentence():
    span = only("Your balance is one lakh fifty thousand rupees")
    assert span.value == 150_000


def test_phone_number_with_commas_stays_one_span():
    span = only("Call plus nine one, nine eight seven six five, four three two one zero.")
    assert span.digits == "919876543210"


def test_sentence_break_splits_numbers():
    spans = find_numbers("Take two. Three more later.")
    assert [s.value for s in spans] == [2, 3]


def test_hyphenated_and_literal_numbers():
    assert only("ninety-eight").value == 98
    assert only("pay Rs 1,00,000 today").value == 100_000
    assert only("dose 0.5 mg").value == 0.5


def test_oclock_is_not_fifty():
    assert only("see you at five o'clock").value == 5


def test_words_that_are_not_numbers():
    assert find_numbers("a big apple and a pear") == []
    assert find_numbers("oh no") == []


def test_ordinal_dates():
    span = only("on the third of April")
    assert span.value == 3 and span.ordinal
