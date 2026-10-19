# 🔊 Readback: reminder calls that say numbers right

Banks, lenders and pharmacies in India call customers with reminders: *"Your EMI of ₹24,999 is due on 05/01/2027. Your outstanding balance is ₹10,00,000."* With AssemblyAI's voice agent, that opening line goes to the voice **word for word**, and the caller hears:

> "…due on **May first**… your outstanding balance is **ten zero rupees**."

Then, when the caller asks "what's my balance?", the agent repeats the digits it just read, and they're misread again.

**Readback is a tool for outbound reminder calls that say amounts, OTPs and dates right.** It checks every customer's message before you dial, fixes it with **SafeSpeak**, and checks the audio of every reply the agent speaks during the call.

Built for AssemblyAI's *Voice hackathon week: Hack into speech* (17–24 Oct 2026).

## The app

| Tab | What it does |
|---|---|
| **Compose** | Write a reminder template and pick a customer. Every amount, code and date is flagged instantly if plain TTS is known to misread it (with the bug it would hit), and you see exactly what SafeSpeak will say. **Check by voice** speaks it both ways and shows ✓/✗ per value with the audio. |
| **Campaign** | Check a whole customer list (12 demo customers or your CSV) before anyone is called. Values SafeSpeak can't verify are held back for SMS; records with hidden characters are flagged for review. Download the report as CSV. |
| **Live call** | Place the call from the browser. The agent opens with the reminder and answers questions in real time. After every reply, Readback compares what the agent meant to say with what the caller actually heard. Toggle SafeSpeak to hear the difference. |
| **Evidence** | The research behind it: 519 measured results and five bugs. |

**Demo campaign** (12 customers, EMI reminder, voice `anna`): plain TTS would misread **11 of 12 calls (27 values)**. With SafeSpeak: **11 ready to call, 1 tampered record flagged for review, 0 misreads.**

### Run it

```bash
uv venv .venv && uv pip install -p .venv -r requirements.txt
cp .env.example .env   # paste your ASSEMBLYAI_API_KEY into .env
.venv/bin/python -m uvicorn server.app:app --port 8000
```

Open http://localhost:8000 in **Chrome** (the live call needs the microphone; use headphones). Checks cost a few cents and are cached; a live call costs about $0.075 a minute. To host it publicly, set `READBACK_PASSCODE` so only people with the passcode can spend your credits.

## The research

AssemblyAI's TTS promises that "order numbers, prices, dates, and confirmation codes come out exactly as written." Readback tests that promise on what Indian voice agents read out every day: lakh/crore amounts, OTPs, PNRs, doses, DD/MM dates, and text that an attacker has tampered with.

<!-- results:start -->
**173 cases** (152 everyday messages + 21 attacks) × **3 voices** (anna, alba, george) = 519 results, scored on the word-for-word transcript:

| | Plain TTS | With SafeSpeak |
|---|---|---|
| Critical values correct (or safely held back) | **53%** | **99%** |
| Misreads | **230** | **0** |
| Refused to speak (couldn't verify, sends SMS instead) | – | 0 |
| Needs an ear check (names and URLs transcribed differently) | 16 | 7 |

Money 32% → 100% · codes 39% → 100% · phone 57% → 100% · dates 60% → 100% · attacks 32% → 100% · medical doses were already 100%. The three voices score within one point of each other, and the two voices the API accepts but the docs don't list (`iris`, `reid`) fail the same 18 of 18 bug cases. The misreads come from shared text normalization, not from any one voice.
Full table: [findings/SCORECARD.md](findings/SCORECARD.md).
<!-- results:end -->

| Bug | What happens | Example |
|---|---|---|
| [BUG-001](findings/BUG-001.md) | Indian digit grouping is misread (72/72 across three voices) | ₹10,00,000 → "ten **zero** rupees" |
| [BUG-002](findings/BUG-002.md) | OTPs, PNRs, pincodes and phone numbers are read as amounts | OTP 482910 → "four hundred eighty two thousand nine hundred ten" |
| [BUG-003](findings/BUG-003.md) | DD/MM dates are read in US order, even on an en-GB voice | 03/04/2026 → "**March fourth**" |
| [BUG-004](findings/BUG-004.md) | Letter runs in codes pronounced as words *(needs ear check)* | IFSC WYXK… → "Wix" |
| [BUG-005](findings/BUG-005.md) | Hidden characters and markup: the screen and the voice disagree | screen ₹500, voice "**five**" |

**Where it bites** ([findings/SCOPE.md](findings/SCOPE.md)): text the voice reads word for word, like an outbound call's opening line, and any digits the agent later repeats from it. Values the agent looks up with a tool are usually spelled out correctly by its own AI.

A side finding that matters for anyone testing TTS: **a formatted speech-to-text check would have hidden 128 of the 230 misreads**, because it turns "one fifty thousand rupees" back into "₹1,50,000". Readback scores the *verbatim* transcript (`format_text=false`) instead.

### How the testing works

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
               date, time, email, text) → PASS / FAIL / UNCLEAR → ear check
```

### SafeSpeak (`readback/safespeak.py`)
1. **Sanitize** so the text matches what the screen shows: apply bidi overrides the way the screen does, strip invisible characters, map look-alike letters and non-ASCII digits, remove SSML and markdown.
2. **Find values:** money (₹/Rs./INR, lakh/crore/L), doses and units, prescription shorthand (1-0-1, BD, TDS), phone numbers, OTPs/PNRs, alphanumeric codes, dates, times, emails, UPI IDs, URLs, abbreviations.
3. **Spell them out** in plain words, so the TTS normalizer never has to guess: "₹1,50,000" → "one lakh fifty thousand rupees", "03/04/2026" → "the third of April, twenty twenty six", "90000" → "nine double zero double zero".
4. **Verify:** speak, transcribe, check every value.
5. **Fall back:** re-say failed values one word at a time. If a value still fails, return `DO_NOT_SPEAK` so the app sends it as an SMS instead.

### Research tools

```bash
# one sentence, end to end
.venv/bin/python -m readback.smoke "Your balance is ₹10,00,000." --voice anna

# the full suite (152 cases + 21 attacks), then score it; then the same through SafeSpeak
.venv/bin/python -m readback.runner --suite all --voices anna
.venv/bin/python -m readback.score
.venv/bin/python -m readback.runner --suite all --voices anna --safespeak

# research dashboard: scorecard, failures with audio + ear-check buttons, attacks, before/after
# (works without an API key from the committed results/ snapshot)
.venv/bin/python -m streamlit run app.py

# listen to plain TTS vs SafeSpeak for each bug
.venv/bin/python listen/play.py --auto

# evidence
.venv/bin/python -m readback.report scorecard
.venv/bin/python -m readback.report snapshot

# live-agent experiments (needs the app running for call_probe)
.venv/bin/python experiments/agent_probe.py
.venv/bin/python experiments/call_probe.py

# tests (no API calls; includes fuzzing, the product API and a headless render of the dashboard)
.venv/bin/python -m pytest -q
```

Everything the API returns is cached by content in `.cache/`, so re-running or re-scoring costs nothing.

## Layout

| Path | What it does |
|---|---|
| `server/app.py` | The product's API: preview, voice check, campaigns, live-call token/config/tool/check |
| `server/templates.py` | Reminder templates, demo customers, and the instant risk check |
| `server/campaign.py` | Checks a customer list four at a time; CSV report |
| `server/static/` | The web app (plain HTML/CSS/JS); `call.js` runs the live call over the Voice Agent API |
| `readback/tts/voice_agent.py` | Word-for-word TTS from the Voice Agent API `greeting`, with word timings, a cache, and always `session.end` |
| `readback/stt.py` | Verbatim and formatted transcription, with retries and a cache |
| `readback/cases/*.yaml` | 80 hand-written cases, 72 generated (`generate.py`, fake data), 21 attacks (`attacks.py`) |
| `readback/numparse.py` / `verbalize.py` | Spoken words ↔ numbers, lakh/crore aware; round-trip tested on 2,500 numbers |
| `readback/score.py` | Checkers for each value type; the LLM judge (`judge.py`) is optional and off on the free plan |
| `readback/sanitize.py` / `safespeak.py` | The SafeSpeak layer |
| `readback/runner.py` / `report.py` | Run cases × voices; clips, scorecard and snapshot |
| `app.py` | Research dashboard (Streamlit) |
| `findings/` | Bug reports with clips, the scorecard, and SCOPE.md |
| `results/` | Text-only snapshot of the published runs |
| `experiments/` | Live Voice Agent experiments behind SCOPE.md |
| `site/` | The project page (cheque-style write-up with audio) |

## Limits
- Speech-to-text can be wrong too. Every FAIL is flagged for an ear check, and only confirmed misreads should be reported.
- There's no Indian English voice yet, so these tests use en-GB and en-US voices.
- The live call needs a microphone; it was tested end to end with a scripted client (`experiments/call_probe.py`) and needs a person for the real conversation.
- The LLM judge needs LLM Gateway access, which isn't on the free plan. Without it, cases the rules can't decide stay UNCLEAR.
