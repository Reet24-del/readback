"""Placeholder for AssemblyAI's standalone TTS-1 model (roadmap: Q4 2026).

If the hackathon grants early access, implement synthesize/asynthesize here with the
same Clip return type and pass `--engine tts1` to the runner. Nothing else changes.
"""

from readback.tts.base import Clip, TTSError


class TTS1:
    name = "tts1"

    def __init__(self, use_cache: bool = True):
        self.use_cache = use_cache

    def synthesize(self, text: str, voice: str) -> Clip:
        raise TTSError("TTS-1 is not available yet; use the voice-agent engine")

    async def asynthesize(self, text: str, voice: str) -> Clip:
        return self.synthesize(text, voice)
