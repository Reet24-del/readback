"""Check every customer's reminder before dialling: plain TTS vs SafeSpeak, four at a time."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Awaitable, Callable

from readback.config import RUNS_DIR
from server.templates import TemplateError, render
from server import sms

CheckFn = Callable[[str, str], Awaitable[dict]]
CAMPAIGN_DIR = RUNS_DIR / "campaigns"


def action(check: dict | None, error: str | None) -> str:
    if error or not check:
        return "Error"
    safe = check["safespeak"]
    if safe.get("tampered"):
        return "Review: hidden characters in record"
    if safe["status"] == "DO_NOT_SPEAK":
        return "Held back: send as SMS"
    if safe["verdict"] != "correct":
        return "Review: values not verified"
    return "Ready to call"


@dataclass
class Campaign:
    template: str
    voice: str
    rows: list[dict]
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    send_sms: bool = False
    results: list[dict] = field(default_factory=list)
    done: int = 0
    status: str = "running"
    started: float = field(default_factory=time.time)
    finished: float | None = None

    def summary(self) -> dict:
        finished = [r for r in self.results if r.get("check") or r.get("error")]
        checked = [r for r in finished if r.get("check")]
        return {
            "total": len(self.rows),
            "checked": len(checked),
            "errors": sum(1 for r in finished if r.get("error")),
            "plain_misread": sum(1 for r in checked if r["check"]["plain"]["verdict"] == "misread"),
            "plain_values_misread": sum(
                sum(1 for c in r["check"]["plain"]["checks"] if c["status"] == "FAIL") for r in checked
            ),
            "ready": sum(1 for r in finished if r["action"].startswith("Ready")),
            "held_back": sum(1 for r in finished if r["action"].startswith("Held back")),
            "review": sum(1 for r in finished if r["action"].startswith("Review")),
            "safespeak_misread": sum(1 for r in checked if r["check"]["safespeak"]["verdict"] == "misread"),
            "sms_delivered": sum(r.get("sms", {}).get("status") == "delivered" for r in finished),
            "sms_pending": sum(r.get("sms", {}).get("status") in ("submitting", "unknown", "accepted", "queued", "sending", "sent") for r in finished),
            "sms_failed": sum(r.get("sms", {}).get("status") in ("failed", "undelivered", "canceled", "not_sent") for r in finished),
        }

    def view(self) -> dict:
        for r in self.results:
            if job_id := r.get("sms", {}).get("id"):
                r["sms"] = sms.get(job_id) or r["sms"]
        return {
            "id": self.id,
            "status": self.status,
            "done": self.done,
            "total": len(self.rows),
            "voice": self.voice,
            "results": self.results,
            "summary": self.summary(),
        }

    def save(self):
        CAMPAIGN_DIR.mkdir(parents=True, exist_ok=True)
        path = CAMPAIGN_DIR / f"{self.id}.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=1))
        temp.replace(path)


def load(cid: str) -> Campaign | None:
    # IDs are used in filenames; never accept arbitrary paths.
    if not cid.isalnum() or len(cid) > 32:
        return None
    path = CAMPAIGN_DIR / f"{cid}.json"
    if not path.exists():
        return None
    c = Campaign(**json.loads(path.read_text()))
    if c.status == "running":
        c.status = "interrupted"  # recovery never redials or resends automatically
    return c


async def run(c: Campaign, check: CheckFn, concurrency: int = 4) -> Campaign:
    c.results = [{"row_id": r.get("id"), "name": r.get("name", ""), "text": None, "check": None, "error": None, "action": "Pending"} for r in c.rows]
    sem = asyncio.Semaphore(concurrency)

    async def one(i: int, row: dict) -> None:
        result = c.results[i]
        try:
            result["text"] = render(c.template, row)
            async with sem:
                result["check"] = await check(result["text"], c.voice)
        except TemplateError as e:
            result["error"] = str(e)
        except Exception as e:  # one customer's failure must not stop the campaign
            result["error"] = f"{type(e).__name__}: {e}"
        result["action"] = action(result["check"], result["error"])
        if c.send_sms and result["action"].startswith("Held back"):
            try:
                result["sms"] = await sms.send_fallback(f"{c.id}:{i}", row, result["text"])
            except Exception:
                result["sms"] = {"status": "unknown", "error": "SMS processing interrupted; check Twilio before resending."}
        c.done += 1
        c.save()

    await asyncio.gather(*(one(i, row) for i, row in enumerate(c.rows)))
    c.status, c.finished = "done", time.time()
    c.save()
    return c


def report_csv(c: Campaign) -> str:
    c.view()  # include the latest signed delivery updates
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["customer", "message", "plain TTS", "plain TTS misread", "SafeSpeak said", "SafeSpeak", "action", "SMS status", "SMS SID", "SMS error"])
    for r in c.results:
        chk = r.get("check") or {}
        plain, safe = chk.get("plain", {}), chk.get("safespeak", {})
        misread = "; ".join(f"{x['value']} ({x['reason']})" for x in plain.get("checks", []) if x["status"] == "FAIL")
        w.writerow([r["name"], r.get("text") or r.get("error") or "", plain.get("verdict", ""), misread,
                    safe.get("said", ""), safe.get("verdict", ""), r["action"], r.get("sms", {}).get("status", "not_requested"),
                    r.get("sms", {}).get("sid", ""), r.get("sms", {}).get("error", "")])
    return out.getvalue()
