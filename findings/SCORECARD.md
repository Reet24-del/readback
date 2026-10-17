# Readback scorecard

Plain TTS: `20261017-131808-voice-agent` + `20261017-132811-voice-agent` (attacks) · SafeSpeak: `20261017-132920-voice-agent-safespeak`
Engine: AssemblyAI Voice Agent API, voice `anna`, text sent via `greeting` (spoken word for word).
Heard: AssemblyAI Universal transcription with `format_text=False`.

| Category | Cases | Plain TTS correct | SafeSpeak correct or safely blocked |
|---|---|---|---|
| adversarial | 21 | 29% | 100% |
| codes | 41 | 39% | 100% |
| contact | 6 | 83% | 100% |
| controls | 5 | 100% | 100% |
| dates | 10 | 60% | 100% |
| medical | 22 | 100% | 100% |
| money | 38 | 32% | 100% |
| names | 10 | 60% | 70% |
| phone | 20 | 60% | 100% |
| **all** | **173** | **52%** | **98%** |

- Plain TTS misread **76** critical values; a formatted-STT check would have hidden **43** of them.
- "Correct" means every critical value was heard as written. UNCLEAR results (abbreviations, names) need an ear check and count as not correct.
- With SafeSpeak, 3 case(s) are still not clean: name-003, name-008, name-010.
