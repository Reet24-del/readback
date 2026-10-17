"""Transcribe TTS output back to text with AssemblyAI speech-to-text.

Two independent passes, so a misread can be pinned on the TTS rather than the STT:
  verbatim  - pre-recorded API with format_text=False: "zero point five milligrams"
  formatted - Sync STT (one request, no polling) with keyterms: "0.5 mg"
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import httpx

from readback.config import api_key
from readback.tts.base import Clip, Word

API = "https://api.assemblyai.com/v2"
# Server + path from the Sync STT OpenAPI spec. If this 404s, check the docs for a /v1 prefix.
SYNC_URL = "https://sync.assemblyai.com/transcribe"
SPEECH_MODELS = ["universal-3-5-pro", "universal-2"]


class STTError(RuntimeError):
    pass


@dataclass
class Transcript:
    text: str
    source: str  # "verbatim" | "formatted"
    words: list[Word] = field(default_factory=list)
    raw: dict = field(default_factory=dict, repr=False)


def _request(method: str, url: str, *, attempts: int = 3, **kwargs) -> httpx.Response:
    for i in range(attempts):
        resp = httpx.request(method, url, timeout=60, **kwargs)
        if resp.status_code == 429 or resp.status_code >= 500:
            time.sleep(2**i)
            continue
        if resp.status_code >= 400:
            raise STTError(f"{method} {url} -> {resp.status_code}: {resp.text[:300]}")
        return resp
    raise STTError(f"{method} {url} kept failing ({resp.status_code}): {resp.text[:300]}")


def transcribe_verbatim(clip: Clip, timeout_s: float = 120.0) -> Transcript:
    headers = {"authorization": api_key()}
    upload_url = _request("POST", f"{API}/upload", headers=headers, content=clip.to_wav_bytes()).json()["upload_url"]

    job = _request(
        "POST",
        f"{API}/transcript",
        headers=headers,
        json={
            "audio_url": upload_url,
            "speech_models": SPEECH_MODELS,
            "language_code": "en",
            "format_text": False,
        },
    ).json()

    deadline = time.monotonic() + timeout_s
    while True:
        res = _request("GET", f"{API}/transcript/{job['id']}", headers=headers).json()
        if res["status"] == "completed":
            break
        if res["status"] == "error":
            raise STTError(f"transcript {job['id']} failed: {res.get('error')}")
        if time.monotonic() > deadline:
            raise STTError(f"transcript {job['id']} not done after {timeout_s}s")
        time.sleep(1)

    words = [Word(w["text"], w.get("start"), w.get("end")) for w in res.get("words") or []]
    return Transcript(res.get("text") or "", "verbatim", words, res)


def transcribe_formatted(clip: Clip, keyterms: list[str] | None = None) -> Transcript:
    config: dict = {"timestamps": True}
    if keyterms:
        config["keyterms_prompt"] = keyterms
    res = _request(
        "POST",
        SYNC_URL,
        headers={"Authorization": api_key(), "X-AAI-Model": "universal-3-5-pro"},
        files={
            "audio": ("clip.wav", clip.to_wav_bytes(), "audio/wav"),
            "config": (None, json.dumps(config), "application/json"),
        },
    ).json()
    words = [Word(w["text"], w.get("start"), w.get("end")) for w in res.get("words") or []]
    return Transcript(res.get("text") or "", "formatted", words, res)
