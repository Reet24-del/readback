from readback.tts.base import Clip, TTSEngine, TTSError, Word
from readback.tts.tts1 import TTS1
from readback.tts.voice_agent import DEFAULT_VOICES, VOICES, VoiceAgentTTS

ENGINES = {"voice-agent": VoiceAgentTTS, "tts1": TTS1}

__all__ = ["Clip", "TTSEngine", "TTSError", "Word", "VoiceAgentTTS", "TTS1", "ENGINES", "VOICES", "DEFAULT_VOICES"]
