"""Throw random and malformed input at every offline component: nothing may crash."""

import random

from readback import cases
from readback.numparse import find_numbers, parse_cardinal, to_digits
from readback.safespeak import prepare
from readback.sanitize import sanitize
from readback.score import score_row

WORDS = (
    "zero one two three four five six seven eight nine ten eleven twelve twenty thirty ninety hundred thousand lakh "
    "lakhs crore million billion point and a double triple oh o first third twenty-fourth rupees paise mg ml at dot "
    "minus dash the of march april pm am"
).split()
PUNCT = [" ", ", ", ". ", "-", "/", ":", "? ", "₹", "Rs.", "+91 ", "@", "_"]
WEIRD = ["​", "‮", "‬", "⁠", "­", "Н", "О", "४", "٤", "１", "½", "<b>", "</b>", "**", "<sub alias=\"x\">", "﻿"]


def random_text(rng: random.Random) -> str:
    parts = []
    for _ in range(rng.randrange(0, 18)):
        r = rng.random()
        if r < 0.45:
            parts.append(rng.choice(WORDS))
        elif r < 0.7:
            parts.append(str(rng.randrange(0, 10 ** rng.randrange(1, 12))))
        elif r < 0.85:
            parts.append(rng.choice(PUNCT))
        else:
            parts.append(rng.choice(WEIRD))
        parts.append(rng.choice([" ", "", ","]))
    return "".join(parts)


def test_parsers_never_crash():
    rng = random.Random(11)
    for _ in range(3000):
        text = random_text(rng)
        for span in find_numbers(text):
            assert text[span.start : span.end] == span.text
        toks = text.lower().split()
        parse_cardinal(toks)
        to_digits(toks)


def test_sanitize_never_crashes_and_is_idempotent():
    rng = random.Random(12)
    for _ in range(3000):
        once = sanitize(random_text(rng)).text
        assert sanitize(once).text == once, repr(once)


def test_safespeak_prepare_never_crashes():
    rng = random.Random(13)
    for _ in range(3000):
        plan = prepare(random_text(rng))
        plan.render(set(range(len(plan.entities))))  # fallback rendering too
        for a, b in zip(plan.entities, plan.entities[1:]):
            assert a.end <= b.start  # entities never overlap


def test_scorer_never_crashes_on_garbage_transcripts():
    rng = random.Random(14)
    all_cases = cases.load()
    for _ in range(3000):
        c = rng.choice(all_cases)
        row = {"text": c.text, "critical": c.critical, "value": c.value, "accept": c.accept_forms(), "verbatim": random_text(rng), "error": None}
        assert score_row(row, use_llm=False).status in ("PASS", "FAIL", "UNCLEAR")


def test_empty_inputs():
    assert find_numbers("") == []
    assert sanitize("").text == ""
    assert prepare("").spoken_text == ""
    c = cases.load()[0]
    row = {"text": c.text, "critical": c.critical, "value": c.value, "accept": c.accept_forms(), "verbatim": "", "error": None}
    assert score_row(row, use_llm=False).status in ("FAIL", "UNCLEAR")
