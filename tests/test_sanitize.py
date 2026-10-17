from readback.sanitize import sanitize


def kinds(result):
    return [f.kind for f in result.findings]


def test_clean_text_is_untouched():
    for text in ["Pay ₹1,00,000 by 03/04/2026.", "Take ½ tab twice daily (1-0-1).", "नमस्ते, आपका OTP 482910 है"]:
        r = sanitize(text)
        assert r.text == text and not r.findings, r.findings


def test_zero_width_space_inside_number():
    r = sanitize("Transfer ₹10​000 now")
    assert r.text == "Transfer ₹10000 now"
    assert kinds(r) == ["invisible"] and r.critical


def test_rtl_override_is_laid_out_like_the_screen():
    # The screen shows the overridden run reversed; speaking the logical order is the attack.
    r = sanitize("You will be charged ₹‮005‬ today.")
    assert r.text == "You will be charged ₹500 today."
    assert kinds(r) == ["bidi"] and r.critical


def test_unclosed_rtl_override_runs_to_the_end():
    r = sanitize("Account ‮4321")
    assert r.text == "Account 1234" and r.critical


def test_letter_o_inside_a_number():
    r = sanitize("Your refund of ₹5О00 is ready.")  # Cyrillic O
    assert r.text == "Your refund of ₹5000 is ready." and r.critical
    assert sanitize("PNR 45213O7890").text == "PNR 4521307890"  # Latin O
    assert sanitize("Call 1800 now. Order O1 is late.").text == "Call 1800 now. Order O1 is late."


def test_markdown_emphasis_is_stripped():
    r = sanitize("Your balance is **₹5,000**.")
    assert r.text == "Your balance is ₹5,000." and "markup" in kinds(r)
    assert sanitize("Contact rahul_k@company.co.in").text == "Contact rahul_k@company.co.in"


def test_non_ascii_digits_become_ascii():
    assert sanitize("OTP ४८२९१०").text == "OTP 482910"
    assert sanitize("OTP ٤٨٢").text == "OTP 482"
    r = sanitize("OTP １２３")
    assert r.text == "OTP 123" and set(kinds(r)) == {"digit"}


def test_cyrillic_letter_inside_code():
    r = sanitize("Vehicle MН12AB1234")  # the H is Cyrillic
    assert r.text == "Vehicle MH12AB1234"
    assert kinds(r) == ["confusable"] and r.critical


def test_all_cyrillic_word_is_left_alone():
    r = sanitize("Привет 42")
    assert r.text == "Привет 42" and not r.findings


def test_fullwidth_letters_are_normalised():
    r = sanitize("PNR ＡＢ12")
    assert r.text == "PNR AB12" and "compat" in kinds(r)


def test_ssml_tags_are_stripped():
    r = sanitize('Pay <say-as interpret-as="characters">499</say-as> rupees')
    assert r.text == "Pay 499 rupees"
    assert kinds(r) == ["markup", "markup"]


def test_joiner_inside_indic_word_is_kept():
    word = "क्‍ष"
    assert sanitize(word).text == word
