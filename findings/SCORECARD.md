# Readback scorecard

Plain TTS: `20261017-155750-voice-agent` · SafeSpeak: `20261017-160028-voice-agent-safespeak`
Engine: AssemblyAI Voice Agent API, voices `alba`, `anna`, `george`, text sent via `greeting` (spoken word for word).
Heard: AssemblyAI Universal transcription with `format_text=False`.

| Category | Results | Plain TTS correct | SafeSpeak correct or safely blocked |
|---|---|---|---|
| adversarial | 63 | 32% | 100% |
| codes | 123 | 39% | 100% |
| contact | 18 | 78% | 94% |
| controls | 15 | 100% | 100% |
| dates | 30 | 60% | 100% |
| medical | 66 | 100% | 100% |
| money | 114 | 32% | 100% |
| names | 30 | 73% | 80% |
| phone | 60 | 57% | 100% |
| **all** | **519** | **53%** | **99%** |

| Voice | Results | Plain TTS correct | SafeSpeak correct or safely blocked |
|---|---|---|---|
| alba | 173 | 53% | 99% |
| anna | 173 | 52% | 98% |
| george | 173 | 53% | 98% |
| **all** | **519** | **53%** | **99%** |

- Plain TTS misread **230** critical values; a formatted-STT check would have hidden **128** of them.
- "Correct" means every critical value was heard as written. UNCLEAR results (abbreviations, names) need an ear check and count as not correct.
- With SafeSpeak: **0** misreads, **0** refused because they couldn't be verified (sent as SMS instead).
- Still not clean with SafeSpeak (7, needs an ear check): contact-005 (george), name-003 (anna), name-008 (anna), name-008 (george), name-010 (alba), name-010 (anna), name-010 (george).
