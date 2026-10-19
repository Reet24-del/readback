"""Reminder templates, demo customers, and the instant (offline) risk check.

A template is the agent's opening line on an outbound call. It reaches the voice word for word,
which is exactly the path where the TTS misreads Indian amounts, codes and dates (see findings/).
"""

from __future__ import annotations

import csv
import io
import re
import string
from pathlib import Path

from readback.safespeak import Entity, Plan, prepare

DEMO_CSV = Path(__file__).parent / "demo" / "customers.csv"

TEMPLATES = {
    "emi": {
        "label": "EMI reminder",
        "business": "Sahayak Bank",
        "text": "Hello {name}, this is Sahayak Bank. Your EMI of {emi} is due on {due_date}. "
        "Your outstanding loan balance is {balance}. For help, call {phone}.",
    },
    "otp": {
        "label": "OTP call",
        "business": "Sahayak Bank",
        "text": "Hello {name}, this is Sahayak Bank. Your one-time password to approve the transfer of {amount} is {otp}. "
        "Do not share it with anyone.",
    },
    "pharmacy": {
        "label": "Pharmacy refill",
        "business": "CareWell Pharmacy",
        "text": "Hello {name}, this is CareWell Pharmacy. Your {medicine} refill is ready. Take {dose} at night, dosage {schedule}. "
        "Your pickup code is {otp}, and your next refill is due on {due_date}.",
    },
    "loan": {
        "label": "Loan approved",
        "business": "Sahayak Bank",
        "text": "Congratulations {name}! Your home loan of {amount} has been approved. "
        "Your first EMI of {emi} starts on {due_date}. Your reference number is {reference}.",
    },
}

FIELDS = ["name", "phone", "amount", "balance", "emi", "due_date", "otp", "medicine", "dose", "schedule", "reference"]


class TemplateError(ValueError):
    pass


def placeholders(text: str) -> list[str]:
    return [f for _, f, _, _ in string.Formatter().parse(text) if f]


def render(text: str, row: dict) -> str:
    try:
        names = placeholders(text)
    except ValueError as e:
        raise TemplateError(f"template has a broken placeholder: {e}") from None
    missing = [n for n in names if not str(row.get(n, "")).strip()]
    if missing:
        raise TemplateError(f"missing value for {', '.join('{' + m + '}' for m in missing)}")
    return text.format_map({n: row[n] for n in names})


def load_customers(data: str | None = None) -> list[dict]:
    """Rows from a CSV (the demo file by default). Every row gets an id."""
    text = data if data is not None else DEMO_CSV.read_text(encoding="utf-8")
    rows = []
    for i, raw in enumerate(csv.DictReader(io.StringIO(text)), 1):
        row = {k.strip(): (v or "").strip() for k, v in raw.items() if k}
        row.setdefault("id", str(i))
        rows.append(row)
    return rows


# ---------------------------------------------------------------- instant risk check

_INDIAN_GROUPED = re.compile(r"\d{1,2}(?:,\d{2})+,\d{3}")
_SAFE_PHONE = re.compile(r"\+91[\s-]?\d{5}\s\d{5}$")  # the one phone format plain TTS read correctly


def risk(entity: Entity) -> dict | None:
    """Would plain TTS likely misread this value? Based on the patterns measured in findings/."""
    v, original = entity.value or {}, entity.original
    if entity.kind in ("money", "number") and _INDIAN_GROUPED.search(original):
        return {"bug": "BUG-001", "why": "Indian digit grouping: read group by group (e.g. 'ten zero rupees')"}
    if entity.kind == "digits":
        return {"bug": "BUG-002", "why": "a code read as an amount (e.g. 'four hundred eighty two thousand…')"}
    if entity.kind == "phone" and not _SAFE_PHONE.search(original):
        return {"bug": "BUG-002", "why": "phone number read as amounts; hyphens may become 'minus'"}
    if entity.kind == "date" and v.get("day", 99) <= 12 and v.get("month", 99) <= 12 and re.match(r"\d", original):
        return {"bug": "BUG-003", "why": "DD/MM date likely read in US order (03/04 → 'March fourth')"}
    if entity.kind == "code" and re.search(r"[A-Z]{3,}", original):
        return {"bug": "BUG-004", "why": "letter run may be pronounced as a word (needs ear check)"}
    return None


def preview(text: str) -> dict:
    """Everything the Compose tab shows before any audio is made."""
    plan: Plan = prepare(text)
    values = []
    for e in plan.entities:
        if e.value is None:
            continue
        values.append({"kind": e.kind, "written": e.original, "safespeak": e.spoken, "risk": risk(e)})
    alerts = [{"kind": f.kind, "severity": f.severity, "detail": f.detail} for f in plan.sanitized.findings]
    return {
        "text": text,
        "spoken_text": plan.spoken_text,
        "values": values,
        "alerts": alerts,
        "at_risk": sum(1 for v in values if v["risk"]) + (1 if any(a["severity"] == "critical" for a in alerts) else 0),
    }
