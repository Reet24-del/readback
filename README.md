# 🔊 Readback

**Does the TTS say exactly what's written?**

AssemblyAI's TTS promises that "order numbers, prices, dates, and confirmation codes come out exactly as written." Readback tests that promise on what Indian voice agents read out every day: lakh/crore amounts, OTPs, PNRs, doses, DD/MM dates, and text that an attacker has tampered with. **SafeSpeak** is a drop-in layer that makes the voice say what the screen shows, or say nothing.

Built for AssemblyAI's *Voice hackathon week: Hack into speech* (17–24 Oct 2026).

## Results

<!-- results:start -->
**173 cases** (152 everyday + 21 attacks), voice `anna`, scored on the verbatim transcript:

| | Plain TTS | With SafeSpeak |
|---|---|---|
| Critical values correct (or safely blocked) | **52%** | **98%** |
| Misreads | **76** | **0** |
| Refused to speak (couldn't verify, sends SMS instead) | – | 1 |
| Needs an ear check (names transcribed differently) | 7 | 3 |

Money 32% → 100% · codes 39% → 100% · phone 60% → 100% · dates 60% → 100% · attacks 29% → 100% · medical doses were already 100%.
Full table: [findings/SCORECARD.md](findings/SCORECARD.md).
<!-- results:end -->

| Bug | What happens | Example |
|---|---|---|
| [BUG-001](findings/BUG-001.md) | Indian digit grouping is misread (every voice, 30/30) | ₹10,00,000 → "ten **zero** rupees" |
| [BUG-002](findings/BUG-002.md) | OTPs, PNRs, pincodes and phone numbers are read as amounts | OTP 482910 → "four hundred eighty two thousand nine hundred ten" |
| [BUG-003](findings/BUG-003.md) | DD/MM dates are read in US order, even on an en-GB voice | 03/04/2026 → "**March fourth**" |
| [BUG-004](findings/BUG-004.md) | Letter runs in codes pronounced as words *(needs ear check)* | IFSC WYXK… → "Wix" |
| [BUG-005](findings/BUG-005.md) | Hidden characters and markup: the screen and the voice disagree | screen ₹500, voice "**five**" |

A side finding that matters for anyone testing TTS: **a formatted speech-to-text check would have hidden 43 of the 76 misreads**, because it turns "one fifty thousand rupees" back into "₹1,50,000". Readback scores the *verbatim* transcript (`format_text=false`) instead.

## How it works

```
case (text + the value that must survive)
   │
   ├─► TTS ─ AssemblyAI Voice Agent API, text sent via `greeting`
   │         (spoken word for word, no LLM involved) + word timings
   │
   ├─► STT ─ Universal, format_text=false → "zero point five milligrams"
   │         Sync STT, formatted          → "0.5 mg" (shows what a formatted check would miss)
   │
   └─► score ─ accepted readings → value checkers (amount, dose, digits, code,
               date, time, email, text) → PASS / FAIL / UNCLEAR → ear check in the dashboard
```

**SafeSpeak** (`readback/safespeak.py`):
1. **Sanitize** so the text matches what the screen shows: apply bidi overrides the way the screen does, strip invisible characters, map look-alike letters and non-ASCII digits, remove SSML and markdown.
2. **Find values:** money (₹/Rs./INR, lakh/crore/L), doses and units, prescription shorthand (1-0-1, BD, TDS), phone numbers, OTPs/PNRs, alphanumeric codes, dates, times, emails, UPI IDs, URLs, abbreviations.
3. **Spell them out** in plain words, so the TTS normalizer never has to guess: "₹1,50,000" → "one lakh fifty thousand rupees", "03/04/2026" → "the third of April, twenty twenty six".
4. **Verify:** speak, transcribe, check every value.
5. **Fall back:** re-say failed values one word at a time. If a value still fails, return `DO_NOT_SPEAK` so the app sends it as an SMS instead.

## Setup

```bash
uv venv .venv && uv pip install -p .venv -r requirements.txt
cp .env.example .env   # then paste your ASSEMBLYAI_API_KEY into .env
```

## Use it

```bash
# one sentence, end to end
.venv/bin/python -m readback.smoke "Your balance is ₹10,00,000." --voice anna

# the full suite (152 cases + 21 attacks), then score it
.venv/bin/python -m readback.runner --suite all --voices anna
.venv/bin/python -m readback.score

# the same cases through SafeSpeak
.venv/bin/python -m readback.runner --suite all --voices anna --safespeak

# dashboard: scorecard, failures with audio + ear-check buttons, attacks, before/after, live demo
.venv/bin/python -m streamlit run app.py

# evidence
.venv/bin/python -m readback.report scorecard
.venv/bin/python -m readback.report clips runs/<run> BUG-00X <case-id> ...

# tests (no API calls)
.venv/bin/python -m pytest -q
```

Everything the API returns is cached by content in `.cache/`, so re-running or re-scoring costs nothing. `--voices` defaults to anna, alba and george; the runs above use only anna, because the misreads were identical across voices.

## Layout

| Path | What it does |
|---|---|
| `readback/tts/voice_agent.py` | Word-for-word TTS from the Voice Agent API `greeting`, with word timings, a cache, and always `session.end` |
| `readback/tts/tts1.py` | Placeholder for AssemblyAI's standalone TTS-1 (roadmap: Q4 2026) |
| `readback/stt.py` | Verbatim and formatted transcription, with retries and a cache |
| `readback/cases/*.yaml` | 80 hand-written cases, 72 generated (`generate.py`, fake data), 21 attacks (`attacks.py`) |
| `readback/numparse.py` / `verbalize.py` | Spoken words ↔ numbers, lakh/crore aware; round-trip tested on 2,500 numbers |
| `readback/score.py` | Checkers for each value type; the LLM judge (`judge.py`) is optional and off on the free plan |
| `readback/sanitize.py` / `safespeak.py` | The SafeSpeak layer |
| `readback/runner.py` | Runs cases × voices with concurrency, `--safespeak` mode |
| `readback/report.py` | Clips of the misread span, and `SCORECARD.md` |
| `app.py` | Streamlit dashboard |
| `findings/` | Bug reports with clips, plus the scorecard |
| `DEMO_SCRIPT.md` / `DISCORD_POSTS.md` | Demo video script and draft posts (not posted) |

## Limits
- Speech-to-text can be wrong too. Every FAIL is flagged for an ear check, and only confirmed misreads should be reported.
- There's no Indian English voice yet, so these tests use en-GB and en-US voices.
- The LLM judge needs LLM Gateway access, which isn't on the free plan. Without it, cases the rules can't decide stay UNCLEAR.
