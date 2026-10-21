"""Regression tests for false passes in multi-value and live-agent replies."""

import asyncio

import pytest

from readback.safespeak import BLOCKED, RETRIED, check_raw, prepare, speak, verify
from readback.score import score_row
from server.app import verdict


@pytest.mark.parametrize("heard, expected", [
    ("Your EMI is five hundred rupees. Your balance is one thousand rupees.", ["PASS", "PASS"]),
    ("Your EMI is one thousand rupees. Your balance is five hundred rupees.", ["FAIL", "FAIL"]),
    ("Your EMI is five hundred rupees. Your balance is five hundred rupees.", ["PASS", "FAIL"]),
    ("Your EMI is rupees. Your balance is one thousand rupees.", ["UNCLEAR", "PASS"]),
    ("Five hundred rupees and one thousand rupees.", ["UNCLEAR", "UNCLEAR"]),
])
def test_each_value_is_bound_to_its_field(heard, expected):
    plan = prepare("Your EMI is ₹500. Your balance is ₹1,000.")
    assert [c["status"] for c in check_raw(plan, heard)] == expected
    assert [c.status for c in verify(plan, plan.spoken_text, heard, set()).values()] == expected


def test_ambiguous_repeated_anchor_does_not_pass():
    plan = prepare("Balance is ₹500.")
    checks = check_raw(plan, "Balance is ten rupees. Balance is five hundred rupees.")
    assert checks[0]["status"] == "UNCLEAR"


def test_spelled_out_followup_is_checked():
    plan = prepare("Your outstanding balance is ten lakh rupees.")
    assert check_raw(plan, "Your outstanding balance is ten rupees.")[0]["status"] == "FAIL"
    assert check_raw(plan, plan.spoken_text)[0]["status"] == "PASS"


def test_empty_checks_do_not_mean_correct():
    assert verdict(check_raw(prepare("Hello, welcome back."), "Hello, welcome back.")) == "not_checked"


def test_alignment_preserves_code_casing_and_decimal_points():
    plan = prepare("Your code is ABCD1234. Take 0.5 mg at night.")
    checks = check_raw(plan, "Your code is ABCD one two three four. Take 0.5 milligrams at night.")
    assert [c["status"] for c in checks] == ["PASS", "PASS"]


def test_short_otp_is_not_ignored():
    plan = prepare("Your OTP is 1234.")
    assert "one two three four" in plan.spoken_text
    assert check_raw(plan, "Your OTP is one two three five.")[0]["status"] == "FAIL"


@pytest.mark.parametrize("text,heard", [
    ("Your OTP is 1234.", "Your OTP is one two three four five."),
    ("Your code is ABCD1234.", "Your code is ABCD one two three four five."),
])
def test_extra_digits_cannot_pass(text, heard):
    assert check_raw(prepare(text), heard)[0]["status"] != "PASS"


def test_extra_conflicting_reading_cannot_pass():
    plan = prepare("Your balance is ₹500.")
    assert check_raw(plan, "Your balance is ten rupees or five hundred rupees.")[0]["status"] != "PASS"


def test_benchmark_accept_phrase_cannot_use_other_amount():
    row = {"text": "EMI ₹500, balance ₹1,000", "critical": "₹500",
           "value": {"type": "amount", "value": 500, "unit": "INR"},
           "accept": ["five hundred rupees"],
           "verbatim": "EMI one thousand rupees, balance five hundred rupees"}
    assert score_row(row, use_llm=False).status == "FAIL"


@pytest.mark.parametrize("second, expected", [
    ("Your balance is unavailable.", BLOCKED),
    ("Your balance is five hundred rupees.", RETRIED),
])
def test_unclear_is_retried_then_blocked_or_verified(monkeypatch, second, expected):
    class Engine:
        def __init__(self):
            self.said = []

        async def asynthesize(self, text, voice):
            self.said.append(text)
            return object()

    responses = iter(["Your balance is unavailable.", second])
    monkeypatch.setattr("readback.stt.cached_transcribe", lambda *a: {"text": next(responses)})
    engine = Engine()
    result = asyncio.run(speak("Your balance is ₹500.", engine=engine))
    assert result.status == expected
    assert len(engine.said) == 2 and "five, hundred, rupees" in engine.said[1]
    assert result.attempts[0]["checks"][0]["status"] == "UNCLEAR"
