"""LLM judge for results the rules can't decide, via AssemblyAI's LLM Gateway.

Only called for UNCLEAR results and for names/emails, where transcription spelling
noise makes exact rules unreliable. Verdicts are cached, so re-scoring is free.
"""

from __future__ import annotations

import hashlib
import json
import re

import httpx

from readback.config import CACHE_DIR, api_key

URL = "https://llm-gateway.assemblyai.com/v1/chat/completions"
MODEL = "claude-sonnet-4-6"
CACHE = CACHE_DIR / "judge"

PROMPT = """You are auditing a text-to-speech (TTS) system. It was given some written text and spoke it aloud; the speech was then transcribed word for word.

Written text: {text}
Critical part (must be conveyed exactly): {critical}
What the critical part means: {value}
Transcription of the speech (numbers appear as spoken words): {heard}
Examples of acceptable readings: {accept}

Would a typical listener in India understand the critical part exactly as written, with no ambiguity?
Judge only the critical part. Ignore minor spelling differences in how the transcription wrote names.
Reply with JSON only: {{"verdict": "PASS" | "FAIL" | "UNCLEAR", "reason": "<one short sentence>"}}"""


class JudgeUnavailable(RuntimeError):
    """The account can't use the gateway model (e.g. free plan); stop asking for this run."""


_unavailable: str | None = None


def judge(row: dict) -> tuple[str, str]:
    global _unavailable
    if _unavailable:
        raise JudgeUnavailable(_unavailable)
    prompt = PROMPT.format(
        text=row["text"],
        critical=row["critical"],
        value=json.dumps(row["value"], ensure_ascii=False),
        heard=row.get("verbatim", ""),
        accept="; ".join(row["accept"][:6]) or "(none listed)",
    )
    path = CACHE / f"{hashlib.sha1(f'{MODEL}\0{prompt}'.encode()).hexdigest()}.json"
    if path.exists():
        cached = json.loads(path.read_text())
        return cached["verdict"], cached["reason"]

    resp = httpx.post(
        URL,
        headers={"authorization": api_key()},
        json={"model": MODEL, "messages": [{"role": "user", "content": prompt}], "max_tokens": 200, "temperature": 0},
        timeout=60,
    )
    if resp.status_code in (400, 401, 403) and "access" in resp.text.lower():
        _unavailable = f"LLM Gateway model {MODEL} not available on this account"
        raise JudgeUnavailable(_unavailable)
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    match = re.search(r"\{.*\}", content, re.S)
    try:
        parsed = json.loads(match.group()) if match else {}
    except json.JSONDecodeError:
        parsed = {}
    verdict = str(parsed.get("verdict", "UNCLEAR")).upper()
    if verdict not in ("PASS", "FAIL", "UNCLEAR"):
        verdict = "UNCLEAR"
    reason = str(parsed.get("reason", content.strip()[:200]))

    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"verdict": verdict, "reason": reason, "raw": content}, ensure_ascii=False))
    return verdict, reason
