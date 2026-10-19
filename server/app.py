"""Readback: outbound reminder calls that say numbers right.

    .venv/bin/python -m uvicorn server.app:app --port 8000

Set READBACK_PASSCODE to require a passcode on every API call (for a public deployment).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import re
from pathlib import Path

import httpx
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from readback.config import CACHE_DIR, SNAPSHOT_DIR, api_key
from readback.report import headline
from readback.safespeak import check_raw, prepare, speak, speak_raw, verify
from readback.stt import cached_transcribe
from readback.tts import VOICES, Clip, VoiceAgentTTS
from server import campaign as campaign_lib
from server.templates import FIELDS, TEMPLATES, TemplateError, load_customers, preview, render

STATIC = Path(__file__).parent / "static"
AUDIO_DIR = CACHE_DIR / "tts" / "voice-agent"
ALL_VOICES = sorted({v for vs in VOICES.values() for v in vs})
MAX_ROWS = 200

app = FastAPI(title="Readback", docs_url="/api/docs", openapi_url="/api/openapi.json")
CAMPAIGNS: dict[str, campaign_lib.Campaign] = {}


@app.middleware("http")
async def passcode_gate(request: Request, call_next):
    code = os.environ.get("READBACK_PASSCODE")
    path = request.url.path
    if code and path.startswith("/api/") and path not in ("/api/health", "/api/config") and request.headers.get("x-passcode") != code:
        return JSONResponse({"detail": "Enter the demo passcode to use this app."}, status_code=401)
    return await call_next(request)


# ---------------------------------------------------------------- helpers


def audio_url(voice: str, text: str) -> str:
    return f"/api/audio/{hashlib.sha1(f'{voice}\0{text}'.encode()).hexdigest()}.wav"


def verdict(checks: list[dict]) -> str:
    statuses = {c["status"] for c in checks}
    return "misread" if "FAIL" in statuses else "unclear" if "UNCLEAR" in statuses else "correct"


def checks_list(plan, verdicts: dict) -> list[dict]:
    return [{"value": plan.entities[i].original, "status": v.status, "reason": v.reason} for i, v in verdicts.items()]


async def check_message(text: str, voice: str) -> dict:
    """Speak one message both ways and check every value. Audio and transcripts are cached."""
    engine = VoiceAgentTTS()
    (_, plain_heard, plain_checks), safe = await asyncio.gather(speak_raw(text, voice, engine), speak(text, voice, engine))
    said = safe.attempts[-1]["said"]
    safe_checks = safe.attempts[-1]["checks"]
    return {
        "text": text,
        "voice": voice,
        "plain": {"heard": plain_heard, "checks": plain_checks, "verdict": verdict(plain_checks), "audio": audio_url(voice, text)},
        "safespeak": {
            "said": said,
            "heard": safe.heard,
            "checks": safe_checks,
            "verdict": verdict(safe_checks),
            "status": safe.status,
            "alerts": safe.alerts,
            "tampered": safe.plan.sanitized.critical,  # hidden characters or look-alikes in the record itself
            "audio": audio_url(voice, said),
        },
    }


async def fetch_call_token() -> str:
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(
            "https://agents.assemblyai.com/v1/token",
            params={"expires_in_seconds": 60, "max_session_duration_seconds": 600},
            headers={"Authorization": f"Bearer {api_key()}"},
        )
    if r.status_code != 200:
        raise HTTPException(502, f"AssemblyAI token request failed ({r.status_code})")
    return r.json()["token"]


def check_voice(voice: str) -> str:
    if voice not in ALL_VOICES:
        raise HTTPException(400, f"unknown voice {voice!r}")
    return voice


# ---------------------------------------------------------------- basics


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/config")
def config() -> dict:
    return {"passcode_required": bool(os.environ.get("READBACK_PASSCODE")), "voices": ALL_VOICES, "default_voice": "anna"}


@app.get("/api/templates")
def templates() -> dict:
    return {k: {**v, "placeholders": sorted(set(re.findall(r"{(\w+)}", v["text"])))} for k, v in TEMPLATES.items()}


@app.get("/api/customers")
def customers() -> list[dict]:
    return load_customers()


@app.post("/api/customers/upload")
async def upload_customers(file: UploadFile = File(...)) -> list[dict]:
    data = await file.read(1_000_001)
    if len(data) > 1_000_000:
        raise HTTPException(413, "CSV must be under 1 MB")
    try:
        rows = load_customers(data.decode("utf-8-sig"))
    except UnicodeDecodeError:
        raise HTTPException(400, "CSV must be UTF-8") from None
    if not rows:
        raise HTTPException(400, "CSV has no rows")
    return rows[:MAX_ROWS]


@app.get("/api/audio/{key}.wav")
def audio(key: str):
    if not re.fullmatch(r"[0-9a-f]{40}", key) or not (AUDIO_DIR / f"{key}.wav").exists():
        raise HTTPException(404, "no such audio")
    return FileResponse(AUDIO_DIR / f"{key}.wav", media_type="audio/wav")


@app.get("/api/evidence")
def evidence() -> dict:
    h = headline(SNAPSHOT_DIR)
    return {k: h[k] for k in ("voices", "results", "cases", "before", "after", "misreads_before", "misreads_after", "blocked", "hidden")} | {
        "categories": {c: {"plain": a, "safespeak": b, "results": n} for c, (a, b, n) in h["categories"].items()}
    }


# ---------------------------------------------------------------- compose


class PreviewIn(BaseModel):
    template: str = Field(max_length=1000)
    row: dict


@app.post("/api/preview")
def preview_message(body: PreviewIn) -> dict:
    try:
        return preview(render(body.template, body.row))
    except TemplateError as e:
        raise HTTPException(400, str(e)) from None


class CheckIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    voice: str = "anna"


@app.post("/api/check")
async def check(body: CheckIn) -> dict:
    return await check_message(body.text, check_voice(body.voice))


# ---------------------------------------------------------------- campaign


class CampaignIn(BaseModel):
    template: str = Field(max_length=1000)
    rows: list[dict]
    voice: str = "anna"


@app.post("/api/campaigns")
async def start_campaign(body: CampaignIn) -> dict:
    if not body.rows or len(body.rows) > MAX_ROWS:
        raise HTTPException(400, f"send between 1 and {MAX_ROWS} customers")
    c = campaign_lib.Campaign(template=body.template, voice=check_voice(body.voice), rows=body.rows)
    CAMPAIGNS[c.id] = c
    asyncio.create_task(campaign_lib.run(c, lambda text, voice: check_message(text, voice)))
    return c.view()


def get_campaign(cid: str) -> campaign_lib.Campaign:
    if cid not in CAMPAIGNS:
        raise HTTPException(404, "no such campaign")
    return CAMPAIGNS[cid]


@app.get("/api/campaigns/{cid}")
def campaign_status(cid: str) -> dict:
    return get_campaign(cid).view()


@app.get("/api/campaigns/{cid}/report.csv")
def campaign_report(cid: str):
    c = get_campaign(cid)
    return PlainTextResponse(
        campaign_lib.report_csv(c),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="readback-campaign-{cid}.csv"'},
    )


# ---------------------------------------------------------------- live call


class CallConfigIn(BaseModel):
    template: str = Field(max_length=1000)
    template_id: str = "emi"
    row: dict
    safespeak: bool = True
    voice: str = "anna"


def account_data(row: dict, safespeak: bool) -> dict:
    data = {k: row[k] for k in FIELDS if str(row.get(k, "")).strip()}
    if safespeak:
        data = {k: (v if k == "name" else prepare(v).spoken_text) for k, v in data.items()}
    return data


@app.post("/api/call/config")
def call_config(body: CallConfigIn) -> dict:
    try:
        rendered = render(body.template, body.row)
    except TemplateError as e:
        raise HTTPException(400, str(e)) from None
    greeting = prepare(rendered).spoken_text if body.safespeak else rendered
    business = TEMPLATES.get(body.template_id, TEMPLATES["emi"])["business"]
    phone = account_data(body.row, body.safespeak).get("phone", "our helpline")
    prompt = (
        f"You are the voice assistant for {business}, on an outbound call to {body.row.get('name', 'the customer')}. "
        f'You have just read them this reminder: "{greeting}" '
        "Answer their follow-up questions in one or two short sentences. Use the get_account tool for any detail about "
        "their account, payment, medicine or reference number, and say amounts, dates and codes exactly as the tool gives them. "
        f"If they want to pay now or speak to a person, ask them to call {phone}. Never ask for passwords or card numbers."
    )
    tool = {
        "type": "function",
        "name": "get_account",
        "description": "Look up this customer's account: amounts, balance, EMI, due date, OTP, medicine, dose, schedule, reference.",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "execution_mode": "interactive",
    }
    return {
        "session": {"system_prompt": prompt, "greeting": greeting, "output": {"voice": check_voice(body.voice)}, "tools": [tool]},
        "rendered": rendered,
        "greeting": greeting,
    }


@app.get("/api/call/token")
async def call_token() -> dict:
    return {"token": await fetch_call_token()}


class ToolIn(BaseModel):
    name: str
    row: dict
    safespeak: bool = True


@app.post("/api/call/tool")
def call_tool(body: ToolIn) -> dict:
    if body.name != "get_account":
        raise HTTPException(400, f"unknown tool {body.name!r}")
    return {"result": account_data(body.row, body.safespeak)}


class CallCheckIn(BaseModel):
    audio: str = Field(description="base64 PCM16 mono 24 kHz: the greeting as the caller heard it")
    rendered: str = Field(max_length=1000)
    greeting: str = Field(max_length=2000)
    safespeak: bool = True


@app.post("/api/call/check")
async def call_check(body: CallCheckIn) -> dict:
    try:
        pcm = base64.b64decode(body.audio, validate=True)
    except ValueError:
        raise HTTPException(400, "audio must be base64") from None
    if len(pcm) < 4800:  # under 0.1 s
        raise HTTPException(400, "not enough audio to check")
    heard = (await asyncio.to_thread(cached_transcribe, "verbatim", Clip(pcm, 24_000)))["text"]
    plan = prepare(body.rendered)
    checks = checks_list(plan, verify(plan, body.greeting, heard, set())) if body.safespeak else check_raw(plan, heard)
    return {"heard": heard, "checks": checks, "verdict": verdict(checks)}


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
