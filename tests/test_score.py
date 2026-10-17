import pytest

from readback import cases
from readback.score import FAIL, PASS, UNCLEAR, formatted_hides_it, score_row, spelled_windows

BY_ID = {c.id: c for c in cases.load()}


def row(case_id: str, heard: str, formatted: str = "") -> dict:
    c = BY_ID[case_id]
    return {
        "case_id": c.id, "category": c.category, "text": c.text, "critical": c.critical,
        "value": c.value, "accept": c.accept_forms(), "verbatim": heard, "formatted": formatted, "error": None,
    }


def status(case_id: str, heard: str) -> str:
    return score_row(row(case_id, heard), use_llm=False).status


@pytest.mark.parametrize(
    "case_id, heard, expected",
    [
        # BUG-001 transcripts, verbatim from the probe run
        ("money-001", "Your balance is one fifty thousand rupees.", FAIL),
        ("money-006", "ten zero rupees has been debited from your account.", FAIL),
        ("money-007", "Pay ten rupees before five p m to avoid a penalty.", FAIL),
        ("money-009", "Your account balance is ninety nine ninety nine thousand nine hundred ninety nine rupees.", FAIL),
        # correct readings
        ("money-001", "Your balance is one lakh fifty thousand rupees.", PASS),
        ("money-001", "Your balance is one hundred and fifty thousand rupees.", PASS),
        ("money-003", "A refund of two point five crore rupees has been approved.", PASS),
        ("money-005", "pre approved for a loan of one point two lakh rupees", PASS),
        ("money-013", "Your bill comes to twelve hundred fifty dollars.", PASS),
        # medical
        ("med-001", "Take zero point five milligrams of clonazepam at night.", PASS),
        ("med-001", "Take five milligrams of clonazepam at night.", FAIL),
        ("med-001", "Take zero point five of clonazepam at night.", FAIL),  # unit dropped
        ("med-003", "Take one half tab of Ecosprin after lunch.", PASS),
        ("med-012", "Take zero point two five milligrams of alprazolam at bedtime.", PASS),
        # digits
        ("code-002", "Your OTP is four eight two nine one zero. Do not share it with anyone.", PASS),
        ("code-002", "Your OTP is forty eight twenty nine ten.", PASS),
        ("code-002", "Your OTP is four hundred eighty two thousand nine hundred ten.", FAIL),
        ("phone-007", "Call nine billion nine hundred eighty eight million seven hundred seventy six thousand six hundred fifty five now.", FAIL),
        ("phone-007", "Call double nine double eight double seven double six double five now.", PASS),
        ("phone-004", "Dial one hundred twelve in an emergency.", FAIL),
        # codes
        ("code-005", "Vehicle M H twelve A B twelve thirty four is parked outside.", PASS),
        ("code-005", "Vehicle M H twelve A B twelve thirty five is parked outside.", FAIL),
        ("code-008", "Transaction ID nine F three A seventy seven B two failed.", PASS),
        ("code-003", "IFSC code A B C D oh one two three four five six.", PASS),
        # dates and times
        ("date-001", "Your appointment is on the third of April twenty twenty six.", PASS),
        ("date-001", "Your appointment is on March fourth twenty twenty six.", FAIL),
        ("date-009", "This offer is valid till October twenty fourth twenty twenty six.", PASS),
        ("date-005", "Your train departs at seventeen thirty I S T.", PASS),
        ("date-006", "The meeting starts at nine oh five a m.", PASS),
        ("date-010", "Check in is from fourteen hundred hours.", PASS),
        # email and text
        ("contact-001", "Write to support at readback dot in for help.", PASS),
        ("contact-002", "Send the documents to priya dot sharma ninety nine at gmail dot com today.", PASS),
        ("contact-004", "Pay to UPI ID shop at ok I C I C I.", PASS),
        ("name-008", "The clinic is on Saint John's Road.", PASS),
        ("name-008", "The clinic is on Street John's Road.", UNCLEAR),  # rules defer to the judge
        # controls
        ("ctl-001", "The number is twenty five.", PASS),
        ("ctl-005", "Turn to page forty two of the report.", PASS),
    ],
)
def test_scoring(case_id, heard, expected):
    assert status(case_id, heard) == expected


def test_swapped_date_reason():
    v = score_row(row("date-001", "Your appointment is on March fourth twenty twenty six."), use_llm=False)
    assert "swapped" in v.reason


def test_error_rows():
    r = row("ctl-001", "")
    r["error"] = "TTSError: boom"
    assert score_row(r, use_llm=False).status == "ERROR"


def test_formatted_hides_it():
    r = row("money-001", "one fifty thousand rupees", formatted="Your balance is ₹1,50,000.")
    assert formatted_hides_it(r)


def test_spelled_windows():
    assert spelled_windows("vehicle m h twelve a b twelve thirty four is here") == ["MH12AB1234"]
    assert spelled_windows("the code is mh12ab1234") == ["MH12AB1234"]
