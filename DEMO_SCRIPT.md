# Demo video script (under 3 minutes)

**Before recording**
- Start the app: `.venv/bin/python -m uvicorn server.app:app --port 8000`, then open http://localhost:8000 in **Chrome**.
- Run **Check by voice** once for Aarav (EMI reminder), and run the demo campaign once, so both respond instantly from cache.
- Wear headphones for the live call. Record with QuickTime (File → New Screen Recording, microphone on for the voice-over).

---

### 0:00–0:20 · The hook: a real reminder call
*On screen:* **Live call** → customer Aarav Sharma, reminder **EMI reminder**, **SafeSpeak off** → **Start call**. Let the opening line play.

> "This is a loan reminder call. Listen to the balance."

*(Agent: "…due on **May first**… your outstanding loan balance is **ten zero rupees**.")*

Ask: *"Sorry, what's my outstanding balance?"* → *"…ten zero rupees."* Point at the red ✗ under each reply.

> "The written reminder said ten lakh rupees on the fifth of January. The caller heard 'ten zero rupees' on May first, and the agent repeats the mistake when asked."

### 0:20–0:45 · The fix, live
*On screen:* Hang up → toggle **SafeSpeak on** → **Start call** → ask the same question.

> "Same agent, same data, with SafeSpeak: ten lakh rupees, the fifth of January, and green checks on everything the caller heard. The follow-up answer says ten lakh rupees too, because the agent never saw the raw digits."

### 0:45–1:15 · Before you dial: Compose
*On screen:* **Compose** tab, Aarav, EMI reminder.

> "Readback flags risky values the moment you write the reminder. The balance hits the lakh bug, the date the DD/MM bug, the helpline number the phone bug. And here's exactly what SafeSpeak will say instead."

Click **Check by voice** → plain card shows **Misread**, SafeSpeak card shows **Correct**. Play both.

### 1:15–1:45 · A whole campaign
*On screen:* **Campaign** → **Check all** (cached, completes fast).

> "Before calling a customer list, check every message. Plain TTS would misread 11 of these 12 calls: 27 wrong values. With SafeSpeak, 11 are ready to call. The twelfth record has hidden characters in it, an attack that makes the screen show ₹500 while the voice says 'five', so Readback holds it for review instead of dialling."

### 1:45–2:30 · Why: the evidence
*On screen:* **Evidence** tab.

> "This comes from testing AssemblyAI's TTS on 173 Indian cases across three voices. Plain TTS got 53% of critical values right; with SafeSpeak, 99% with zero misreads. Five bugs: lakh amounts, OTPs read as amounts, day-month dates, letter codes, and hidden-character attacks. And 128 of the 230 misreads would be invisible if you checked with formatted speech-to-text, because it turns 'ten zero rupees' back into ₹10,00,000."

### 2:30–2:50 · Close
> "Readback: check every reminder before you dial, fix it, and watch every reply during the call. Because if a voice agent reads out your money, it should say what's written."

---

**Tips:** zoom the browser to about 110%, mute notifications, and record the live call first, since it's the strongest moment. If the agent phrases its answer differently, just ask about the balance again.
