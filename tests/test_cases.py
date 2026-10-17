import pytest
import yaml

from readback import cases
from readback.cases import generate


def test_every_suite_loads_with_unique_ids():
    allc = cases.load()
    assert len(allc) >= 140
    assert len({c.id for c in allc}) == len(allc)


def test_every_case_has_an_accept_form_or_is_text_like():
    for c in cases.load():
        if c.kind in ("amount", "number", "dose", "digits", "code"):
            assert c.accept_forms(), c.id


def test_derived_forms():
    by_id = {c.id: c for c in cases.load()}
    assert "one lakh fifty thousand rupees" in by_id["money-001"].accept_forms()
    assert "one hundred fifty thousand rupees" in by_id["money-001"].accept_forms()
    assert "half a milligram" in by_id["med-001"].accept_forms()
    assert "m h one two a b one two three four" in by_id["code-005"].accept_forms()


def test_generated_file_is_up_to_date():
    on_disk = yaml.safe_load(generate.OUT.read_text())
    assert on_disk == generate.generate(), "run `python -m readback.cases.generate`"


def test_generator_is_deterministic():
    assert generate.generate() == generate.generate()


def test_indian_commas():
    assert generate.indian_commas(150000) == "1,50,000"
    assert generate.indian_commas(34567890) == "3,45,67,890"
    assert generate.indian_commas(999) == "999"


def test_bad_case_is_rejected(tmp_path, monkeypatch):
    (tmp_path / "bad.yaml").write_text(
        "- {id: x, category: c, text: 'Pay 5', critical: '6', value: {type: number, value: 5}, severity: low}\n"
    )
    monkeypatch.setattr(cases, "SUITE_DIR", tmp_path)
    with pytest.raises(cases.CaseError, match="not in the text"):
        cases.load_suite("bad")
