import pytest

from readback import cases
from readback.safespeak import chunk_digits, prepare, say_digits, verify, year_words
from readback.score import score_row


@pytest.mark.parametrize(
    "text, spoken",
    [
        ("Your balance is ₹1,50,000.", "Your balance is one lakh fifty thousand rupees."),
        ("₹10,00,000 has been debited.", "ten lakh rupees has been debited."),
        ("A refund of ₹2.5 crore.", "A refund of two crore fifty lakh rupees."),
        ("Loan of ₹1.2L approved.", "Loan of one lakh twenty thousand rupees approved."),
        ("The fare is ₹75.50.", "The fare is seventy five rupees and fifty paise."),
        ("Pay 499 rupees.", "Pay four hundred ninety nine rupees."),
        ("Take 0.5 mg at night.", "Take half a milligram at night."),
        ("Take 0.25 mg at night.", "Take zero point two five milligrams at night."),
        ("Dosage: 1-0-1 after food.", "Dosage: one in the morning, none in the afternoon, and one at night after food."),
        ("Metformin 500 mg BD.", "Metformin five hundred milligrams twice a day."),
        ("Call +91 98765 43210.", "Call plus nine one, nine eight seven six five, four three two one zero."),
        ("Dial 112 now.", "Dial double one two now."),
        # a value followed by a comma is punctuation, not part of the number
        ("Your pickup code is 482910, and it expires.", "Your pickup code is four eight two, nine one zero, and it expires."),
        ("Your EMI of ₹24,999, due soon.", "Your EMI of twenty four thousand nine hundred ninety nine rupees, due soon."),
        ("Take 500 mg, then rest.", "Take five hundred milligrams, then rest."),
        ("WhatsApp +91-90000-00001.", "WhatsApp plus nine one, nine double zero double zero, double zero double zero one."),
        ("Helpline 1800 425 1111.", "Helpline one eight double zero, four two five, double one double one."),
        ("Your OTP is 482910.", "Your OTP is four eight two, nine one zero."),
        ("Vehicle MH12AB1234.", "Vehicle M H one two A B one two three four."),
        ("On 03/04/2026.", "On the third of April, twenty twenty six."),
        ("Valid till 2026-10-24.", "Valid till the twenty fourth of October, twenty twenty six."),
        ("At 17:30 IST.", "At five thirty P M IST."),
        ("At 9:05 AM.", "At nine oh five A M."),
        ("Mail priya.sharma99@gmail.com.", "Mail priya dot sharma nine nine at gmail dot com."),
        ("See Dr. Rao on St. John's Road.", "See Doctor Rao on Saint John's Road."),
        # attacks: speak what the screen shows
        ("You will be charged ₹‮005‬ today.", "You will be charged five hundred rupees today."),
        ("Your refund of ₹5О00 is ready.", "Your refund of five thousand rupees is ready."),
        ("Transfer ₹10​000 now.", "Transfer ten thousand rupees now."),
        ("Your balance is **₹5,000**.", "Your balance is five thousand rupees."),
    ],
)
def test_spoken_text(text, spoken):
    assert prepare(text).spoken_text == spoken


def test_say_digits_round_trips_through_the_scorer():
    import random

    from readback.numparse import to_digits

    rng = random.Random(5)
    for _ in range(500):
        s = "".join(rng.choices("0019", k=rng.randrange(1, 12)))  # few symbols -> many runs
        assert to_digits(say_digits(s).split()) == s, (s, say_digits(s))
    assert say_digits("0000000") == "triple zero double zero double zero"


def test_chunk_digits():
    assert chunk_digits("4521367890") == ["452", "136", "7890"]
    assert chunk_digits("482910") == ["482", "910"]
    assert chunk_digits("1234") == ["1234"]


def test_year_words():
    assert [year_words(y) for y in (2026, 1990, 2000, 2005, 1905)] == [
        "twenty twenty six", "nineteen ninety", "two thousand", "two thousand five", "nineteen oh five"]


def test_attack_alerts_are_kept():
    plan = prepare("You will be charged ₹‮005‬ today.")
    assert plan.sanitized.critical


def test_verify_catches_a_misread():
    plan = prepare("Your balance is ₹1,50,000.")
    said = plan.spoken_text
    ok = verify(plan, said, "Your balance is one lakh fifty thousand rupees.", set())
    bad = verify(plan, said, "Your balance is one fifty thousand rupees.", set())
    assert [v.status for v in ok.values()] == ["PASS"]
    assert [v.status for v in bad.values()] == ["FAIL"]


def test_safespeak_text_passes_its_own_case_scoring():
    """If the TTS reads SafeSpeak's words faithfully, every case with a value must score PASS."""
    for c in cases.load():
        spoken = prepare(c.text).spoken_text
        row = {"text": c.text, "critical": c.critical, "value": c.value, "accept": c.accept_forms(), "verbatim": spoken, "error": None}
        if c.kind in ("text", "email") or c.id in ("code-012", "name-004", "name-005", "name-007", "name-010"):
            continue  # judged by fuzzy match / LLM, or deliberately left untouched
        assert score_row(row, use_llm=False).status == "PASS", (c.id, spoken)
