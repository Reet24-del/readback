"""Engine-agnostic audio types. Every TTS adapter returns a Clip."""

from __future__ import annotations

import io
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol


class TTSError(RuntimeError):
    pass


@dataclass
class Word:
    text: str
    start_ms: int | None = None
    end_ms: int | None = None


@dataclass
class Clip:
    """Mono 16-bit little-endian PCM plus the engine's own word timings."""

    pcm: bytes
    sample_rate: int
    words: list[Word] = field(default_factory=list)
    engine_text: str = ""  # what the engine says it spoke (transcript.agent)

    @property
    def duration_ms(self) -> int:
        return len(self.pcm) // 2 * 1000 // self.sample_rate

    def to_wav_bytes(self) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.sample_rate)
            w.writeframes(self.pcm)
        return buf.getvalue()

    def save_wav(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.to_wav_bytes())
        return path

    def slice_ms(self, start_ms: int, end_ms: int, pad_ms: int = 150) -> Clip:
        """Cut out [start, end] (plus padding) so a reviewer hears only the misread span."""
        lo = max(0, start_ms - pad_ms) * self.sample_rate // 1000 * 2
        hi = min(self.duration_ms, end_ms + pad_ms) * self.sample_rate // 1000 * 2
        return Clip(self.pcm[lo:hi], self.sample_rate)

    def words_as_dicts(self) -> list[dict]:
        return [asdict(w) for w in self.words]

    @classmethod
    def from_wav(cls, path: Path, words: list[dict] | None = None, engine_text: str = "") -> Clip:
        with wave.open(str(path), "rb") as w:
            if w.getnchannels() != 1 or w.getsampwidth() != 2:
                raise TTSError(f"{path} is not mono 16-bit PCM")
            pcm = w.readframes(w.getnframes())
            rate = w.getframerate()
        return cls(pcm, rate, [Word(**d) for d in words or []], engine_text)


class TTSEngine(Protocol):
    name: str

    def synthesize(self, text: str, voice: str) -> Clip: ...

    async def asynthesize(self, text: str, voice: str) -> Clip: ...
