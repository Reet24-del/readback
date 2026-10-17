"""Test cases: what to say, which part matters, and every acceptable way to say it.

Suites live next to this file as <suite>.yaml. A case's `value` says what the critical
span means; `accept` lists extra spoken forms on top of the ones derived from `value`.

value types:
  amount  {value: 150000, unit: INR}        number  {value: 25}
  dose    {amount: 0.5, unit: mg}           digits  {digits: "919876543210"}
  code    {chars: "MH12AB1234"}             date    {day: 3, month: 4, year: 2026}
  time    {hour: 17, minute: 30}            email   {address: "a.b@x.in"}
  text    {value: "Thiruvananthapuram"}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from readback import verbalize

SUITE_DIR = Path(__file__).parent
SEVERITIES = ("critical", "high", "low")
VALUE_FIELDS = {
    "amount": {"value"},
    "number": {"value"},
    "dose": {"amount", "unit"},
    "digits": {"digits"},
    "code": {"chars"},
    "date": {"day", "month"},
    "time": {"hour", "minute"},
    "email": {"address"},
    "text": {"value"},
}

UNIT_WORDS = {
    "mg": ("milligram", "milligrams"),
    "mcg": ("microgram", "micrograms"),
    "g": ("gram", "grams"),
    "ml": ("millilitre", "millilitres"),
    "iu": ("international unit", "international units"),
    "tab": ("tablet", "tablets"),
    "drop": ("drop", "drops"),
}
CURRENCY_WORDS = {"INR": "rupees", "USD": "dollars"}


class CaseError(ValueError):
    pass


@dataclass
class Case:
    id: str
    suite: str
    category: str
    text: str
    critical: str
    value: dict
    severity: str
    accept: list[str] = field(default_factory=list)
    notes: str = ""

    @property
    def kind(self) -> str:
        return self.value["type"]

    def accept_forms(self) -> list[str]:
        """Explicit accept forms plus the standard readings derived from `value`."""
        return list(dict.fromkeys([*self.accept, *_derived_forms(self.value)]))


def _derived_forms(v: dict) -> list[str]:
    kind = v["type"]
    if kind in ("amount", "number"):
        n = v["value"]
        words = verbalize.decimal(n) if isinstance(n, float) else verbalize.cardinal(n)
        cur = CURRENCY_WORDS.get(v.get("unit", ""))
        return [f"{w} {cur}" for w in words] + [f"{cur} {w}" for w in words] if cur else words
    if kind == "dose":
        amount, unit = v["amount"], v["unit"].lower()
        singular, plural = UNIT_WORDS.get(unit, (unit, unit))
        unit_word = singular if amount == 1 else plural
        forms = [f"{w} {unit_word}" for w in verbalize.decimal(amount)]
        if amount == 0.5:
            forms += [f"half a {singular}", f"half {singular}"]
        return forms
    if kind == "digits":
        return [verbalize.digits(v["digits"])]
    if kind == "code":
        spelled = " ".join(verbalize.ONES[int(c)] if c.isdigit() else c.lower() for c in v["chars"] if c.isalnum())
        return [spelled]
    return []


def _parse(raw: dict, suite: str, where: str) -> Case:
    missing = {"id", "category", "text", "critical", "value", "severity"} - raw.keys()
    if missing:
        raise CaseError(f"{where}: missing {sorted(missing)}")
    value = raw["value"]
    kind = value.get("type")
    if kind not in VALUE_FIELDS:
        raise CaseError(f"{where} ({raw['id']}): unknown value type {kind!r}")
    if absent := VALUE_FIELDS[kind] - value.keys():
        raise CaseError(f"{where} ({raw['id']}): {kind} value needs {sorted(absent)}")
    if raw["severity"] not in SEVERITIES:
        raise CaseError(f"{where} ({raw['id']}): severity must be one of {SEVERITIES}")
    if raw["critical"] not in raw["text"]:
        raise CaseError(f"{where} ({raw['id']}): critical {raw['critical']!r} is not in the text")
    return Case(
        id=raw["id"],
        suite=suite,
        category=raw["category"],
        text=raw["text"],
        critical=raw["critical"],
        value=value,
        severity=raw["severity"],
        accept=list(raw.get("accept") or []),
        notes=raw.get("notes", ""),
    )


def suite_names() -> list[str]:
    return sorted(p.stem for p in SUITE_DIR.glob("*.yaml"))


def load_suite(name: str) -> list[Case]:
    path = SUITE_DIR / f"{name}.yaml"
    if not path.exists():
        raise CaseError(f"no suite {name!r}; available: {', '.join(suite_names())}")
    raw = yaml.safe_load(path.read_text()) or []
    return [_parse(r, name, f"{path.name}[{i}]") for i, r in enumerate(raw)]


def load(names: list[str] | None = None) -> list[Case]:
    """Load the named suites ("all" or None means every suite), checking ids are unique."""
    if not names or names == ["all"]:
        names = suite_names()
    cases = [c for n in names for c in load_suite(n)]
    seen: set[str] = set()
    for c in cases:
        if c.id in seen:
            raise CaseError(f"duplicate case id {c.id!r}")
        seen.add(c.id)
    return cases
