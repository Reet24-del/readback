"""Twilio SMS fallback with durable, at-most-once attempts and signed delivery updates.

No automatic resend on a timeout: Twilio may already have accepted the message.
The callback can resolve that unknown outcome, including after a process restart.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from twilio.request_validator import RequestValidator

from readback.config import RUNS_DIR
from readback.sanitize import sanitize

STATUSES = {"accepted", "queued", "sending", "sent", "delivered", "undelivered", "failed", "canceled"}
TERMINAL = {"delivered", "undelivered", "failed", "canceled"}
ORDER = {s: i for i, s in enumerate(("submitting", "unknown", "accepted", "queued", "sending", "sent"))}


def settings() -> dict:
    return {k: os.environ.get(k, "").strip() for k in (
        "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_MESSAGING_SERVICE_SID",
        "TWILIO_FROM_NUMBER", "READBACK_SMS_STATUS_URL", "READBACK_PASSCODE", "READBACK_SMS_ENABLED",
    )}


def configuration_error() -> str | None:
    s = settings()
    if s["READBACK_SMS_ENABLED"].lower() != "true":
        return "SMS is disabled. Set READBACK_SMS_ENABLED=true to enable it."
    if not s["READBACK_PASSCODE"]:
        return "Set READBACK_PASSCODE before enabling SMS."
    if not re.fullmatch(r"AC[0-9a-fA-F]{32}", s["TWILIO_ACCOUNT_SID"]) or not s["TWILIO_AUTH_TOKEN"]:
        return "Configure TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN."
    if s["TWILIO_MESSAGING_SERVICE_SID"]:
        if not re.fullmatch(r"MG[0-9a-fA-F]{32}", s["TWILIO_MESSAGING_SERVICE_SID"]):
            return "TWILIO_MESSAGING_SERVICE_SID must be a Messaging Service SID."
    elif not re.fullmatch(r"\+[1-9][0-9]{7,14}", s["TWILIO_FROM_NUMBER"]):
        return "Configure an SMS Messaging Service or TWILIO_FROM_NUMBER in E.164 format."
    u = urlsplit(s["READBACK_SMS_STATUS_URL"])
    if u.scheme != "https" or not u.netloc or u.path != "/api/sms/status" or u.query or u.fragment or u.username:
        return "READBACK_SMS_STATUS_URL must be https://your-host/api/sms/status (no query)."
    return None


def connect():
    path = Path(os.environ.get("READBACK_SMS_DB", str(RUNS_DIR / "sms.sqlite3")))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY, dedupe_key TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL,
        status TEXT NOT NULL, sid TEXT, error TEXT, error_code TEXT
    )""")
    db.commit()
    return db


def get(job_id: str) -> dict | None:
    with closing(connect()) as db:
        row = db.execute("SELECT id,status,sid,error,error_code FROM messages WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None


def update(job_id: str, status: str, sid: str | None = None, error: str | None = None, error_code: str | None = None) -> dict:
    with closing(connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM messages WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise ValueError("unknown SMS attempt")
        if sid and row["sid"] and row["sid"] != sid:
            raise ValueError("message SID does not match this SMS attempt")
        # Duplicate / late callbacks must not regress a delivered or failed message.
        if row["status"] not in TERMINAL and (status in TERMINAL or ORDER.get(status, -1) >= ORDER.get(row["status"], -1)):
            db.execute("UPDATE messages SET status=?,sid=COALESCE(?,sid),error=?,error_code=? WHERE id=?",
                       (status, sid, error, error_code, job_id))
    return get(job_id)


def callback_url(job_id: str) -> str:
    return settings()["READBACK_SMS_STATUS_URL"] + "?job=" + job_id


def accept_callback(job_id: str, form, signature: str) -> dict:
    s = settings()
    if not re.fullmatch(r"[0-9a-f]{32}", job_id) or not s["TWILIO_AUTH_TOKEN"] or not s["READBACK_SMS_STATUS_URL"]:
        raise PermissionError("invalid callback")
    if not RequestValidator(s["TWILIO_AUTH_TOKEN"]).validate(callback_url(job_id), form, signature):
        raise PermissionError("invalid Twilio signature")
    if form.get("AccountSid") != s["TWILIO_ACCOUNT_SID"]:
        raise PermissionError("wrong Twilio account")
    status, sid = form.get("MessageStatus"), form.get("MessageSid", "")
    if status not in STATUSES or not re.fullmatch(r"SM[0-9a-fA-F]{32}", sid):
        raise ValueError("invalid message status or SID")
    code = form.get("ErrorCode") or None
    return update(job_id, status, sid, f"Twilio delivery error {code}" if code else None, code)


async def send_fallback(key: str, row: dict, text: str) -> dict:
    """Only called for held, untampered campaign records when SMS was selected."""
    if error := configuration_error():
        return {"status": "not_sent", "error": error}
    if str(row.get("sms_consent", "")).lower().strip() not in ("true", "yes", "1"):
        return {"status": "not_sent", "error": "Customer SMS consent is missing."}
    # phone is the BUSINESS helpline in the existing templates, never a recipient.
    recipient = str(row.get("sms_to", "")).strip()
    if not re.fullmatch(r"\+[1-9][0-9]{7,14}", recipient):
        return {"status": "not_sent", "error": "sms_to must be the customer's E.164 number."}
    clean = sanitize(text)
    if clean.critical:
        return {"status": "not_sent", "error": "Tampered content requires manual review."}
    if not clean.text or len(clean.text) > 1600:
        return {"status": "not_sent", "error": "SMS must contain 1–1600 characters."}
    fingerprint = hashlib.sha256((recipient + "\0" + clean.text).encode()).hexdigest()
    job_id = uuid.uuid4().hex
    with closing(connect()) as db, db:
        cur = db.execute("INSERT OR IGNORE INTO messages(id,dedupe_key,fingerprint,status) VALUES (?,?,?,?)",
                         (job_id, key, fingerprint, "submitting"))
        existing = db.execute("SELECT * FROM messages WHERE dedupe_key=?", (key,)).fetchone()
        inserted = cur.rowcount == 1
    if existing["fingerprint"] != fingerprint:
        return {"status": "not_sent", "error": "SMS attempt already exists for different content."}
    if not inserted:
        return get(existing["id"])
    s = settings()
    data = {"To": recipient, "Body": clean.text, "StatusCallback": callback_url(job_id)}
    if s["TWILIO_MESSAGING_SERVICE_SID"]:
        data["MessagingServiceSid"] = s["TWILIO_MESSAGING_SERVICE_SID"]
    else:
        data["From"] = s["TWILIO_FROM_NUMBER"]
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{s['TWILIO_ACCOUNT_SID']}/Messages.json",
                auth=(s["TWILIO_ACCOUNT_SID"], s["TWILIO_AUTH_TOKEN"]), data=data,
            )
        if response.status_code >= 500:
            return update(job_id, "unknown", error="Provider error; check Twilio before any manual resend.")
        if response.status_code >= 400:
            # Do not expose provider response text containing credentials or message content.
            try:
                rejection = response.json()
                code = str(rejection.get("code", response.status_code)) if isinstance(rejection, dict) else str(response.status_code)
            except ValueError:
                code = str(response.status_code)
            return update(job_id, "failed", error=f"Twilio rejected the SMS ({code}).", error_code=code)
        result = response.json()
        if (not isinstance(result, dict) or not isinstance(result.get("status"), str)
                or result["status"] not in STATUSES or not isinstance(result.get("sid"), str)
                or not re.fullmatch(r"SM[0-9a-fA-F]{32}", result["sid"])):
            return update(job_id, "unknown", error="Unrecognized provider response; check Twilio before resending.")
        return update(job_id, result["status"], result["sid"])
    except (httpx.RequestError, ValueError):
        return update(job_id, "unknown", error="SMS outcome unknown; no automatic retry to avoid duplicates.")
