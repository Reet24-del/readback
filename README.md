# Readback

AssemblyAI says its TTS makes "order numbers, prices, dates, and confirmation codes come out exactly as written." Readback checks that claim.

It speaks hard Indian money, medicine, code and phone-number cases through the TTS, transcribes the audio with AssemblyAI's own speech-to-text, and flags every important value that comes out wrong. Then **SafeSpeak** catches and fixes those misreads before a user hears them.

Built for AssemblyAI's *Voice hackathon week: Hack into speech* (17–24 Oct 2026).

## Setup

```bash
uv venv .venv && uv pip install -p .venv -r requirements.txt
cp .env.example .env   # then paste your ASSEMBLYAI_API_KEY into .env
```

## Smoke test (day 1)

```bash
.venv/bin/python -m readback.smoke "Take 0.5 mg of Clonazepam at night." --voice anna
```

This runs the full loop: text → Voice Agent TTS (through `greeting`, which is spoken word for word) → WAV in `runs/smoke/` → a verbatim transcription (`format_text=False`) and a formatted one (Sync STT). It then prints the numbers it heard.

TTS audio is cached in `.cache/tts/`, so re-running the same text and voice costs nothing. Use `--no-cache` to force a fresh call.

## Tests

```bash
.venv/bin/python -m pytest -q
```

## What's here so far

| Module | What it does |
|---|---|
| `readback/tts/voice_agent.py` | Gets word-for-word TTS from the Voice Agent API, with word timings and always ending the session with `session.end` |
| `readback/tts/tts1.py` | Placeholder for AssemblyAI's standalone TTS-1, if early access arrives |
| `readback/stt.py` | Two independent transcriptions (verbatim and formatted), so a misread can be blamed on the TTS rather than the transcription |
| `readback/numparse.py` | Turns spoken words back into values: lakh/crore, "zero point five", "double five", digit-by-digit phone numbers |
| `readback/sanitize.py` | Catches tricks that make the speech differ from what's on screen: invisible characters, right-to-left overrides, look-alike letters, non-ASCII digits, SSML tags |
| `readback/verbalize.py` | Number → correct words (lakh/crore and international), the inverse of `numparse` |
| `readback/cases/*.yaml` | 152 test cases: 80 hand-written across 8 suites, plus 72 generated with fake data (`python -m readback.cases.generate`) |
| `readback/runner.py` | Runs cases × voices through TTS and both transcriptions; output goes to `runs/<ts>/results.jsonl` plus WAVs, with caching |
| `findings/` | Confirmed and candidate bugs, with clips |

## Running cases

```bash
.venv/bin/python -m readback.runner --suite medical --voices anna --limit 3
.venv/bin/python -m readback.runner --suite all            # 152 cases × 3 default voices
```

## Findings so far

- **[BUG-001](findings/BUG-001.md):** Indian digit grouping is misread on every voice (30/30). ₹10,00,000 comes out as "ten zero rupees", and ₹1,00,000 as "ten rupees" on one voice.

Next: scoring, SafeSpeak, and the dashboard (see the build plan).
