"""TTS through AssemblyAI's Voice Agent API.

There is no standalone TTS endpoint yet (TTS-1 is on the roadmap for Q4 2026), but the
Voice Agent API sends `greeting` straight to TTS without the LLM touching it, so one
session per test string gives us verbatim synthesis plus word timings.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json

import websockets

from readback.config import CACHE_DIR, api_key
from readback.tts.base import Clip, TTSError, Word

URL = "wss://agents.assemblyai.com/v1/ws"
SAMPLE_RATE = 24_000  # reply.audio is base64 PCM16 mono 24 kHz

VOICES = {
    "en-US": ["alba", "eve", "george", "jane", "jean", "mary", "michael"],
    "en-GB": ["anna", "charles", "paul", "vera"],
    # Accepted by the API (it lists them in its invalid-voice error) but not in the docs as of Oct 2026.
    "undocumented": ["iris", "reid"],
}
DEFAULT_VOICES = ["anna", "alba", "george"]

# Never spoken: the greeting bypasses the LLM, and we end the session after it.
_SYSTEM_PROMPT = "You are a silent test fixture. Do not say anything beyond the greeting."


class VoiceAgentTTS:
    name = "voice-agent"

    def __init__(self, use_cache: bool = True, timeout_s: float = 45.0):
        self.use_cache = use_cache
        self.timeout_s = timeout_s
        self.cache_dir = CACHE_DIR / "tts" / self.name

    def synthesize(self, text: str, voice: str = "anna") -> Clip:
        return asyncio.run(self.asynthesize(text, voice))

    async def asynthesize(self, text: str, voice: str = "anna") -> Clip:
        key = hashlib.sha1(f"{voice}\0{text}".encode()).hexdigest()
        wav_path = self.cache_dir / f"{key}.wav"
        meta_path = self.cache_dir / f"{key}.json"

        if self.use_cache and wav_path.exists() and meta_path.exists():
            meta = json.loads(meta_path.read_text())
            return Clip.from_wav(wav_path, meta["words"], meta["engine_text"])

        clip = await self._fetch(text, voice)
        clip.save_wav(wav_path)
        meta_path.write_text(
            json.dumps(
                {"text": text, "voice": voice, "engine_text": clip.engine_text, "words": clip.words_as_dicts()},
                ensure_ascii=False,
                indent=2,
            )
        )
        return clip

    async def _fetch(self, text: str, voice: str) -> Clip:
        headers = {"Authorization": f"Bearer {api_key()}"}
        audio = bytearray()
        words: list[Word] = []
        engine_text = ""
        done = False

        async with websockets.connect(URL, additional_headers=headers, max_size=None) as ws:
            await ws.send(
                json.dumps(
                    {
                        "type": "session.update",
                        "session": {
                            "system_prompt": _SYSTEM_PROMPT,
                            "greeting": text,
                            "output": {"voice": voice},
                        },
                    }
                )
            )
            try:
                async with asyncio.timeout(self.timeout_s):
                    while True:
                        # After reply.done, give transcript.agent a moment in case it lands second.
                        try:
                            raw = await (asyncio.wait_for(ws.recv(), 1.0) if done else ws.recv())
                        except TimeoutError:
                            break
                        ev = json.loads(raw)
                        kind = ev.get("type")
                        if kind == "reply.audio":
                            audio += base64.b64decode(ev["data"])
                        elif kind == "transcript.agent.delta":
                            words.append(Word(ev.get("delta", ""), ev.get("start_ms"), ev.get("end_ms")))
                        elif kind == "transcript.agent":
                            engine_text = ev.get("text", "")
                            if done:
                                break
                        elif kind == "reply.done":
                            if ev.get("status") != "completed":
                                raise TTSError(f"reply ended with status {ev.get('status')!r}")
                            done = True
                            if engine_text:
                                break
                        elif kind == "session.error":
                            raise TTSError(f"{ev.get('code')}: {ev.get('message')}")
            except TimeoutError:
                raise TTSError(f"no reply.done within {self.timeout_s}s") from None
            finally:
                # Closing without session.end keeps the session billable for 30 s.
                with contextlib.suppress(Exception):
                    await ws.send(json.dumps({"type": "session.end"}))

        if not audio:
            raise TTSError("session finished without any audio")
        return Clip(bytes(audio), SAMPLE_RATE, words, engine_text)
