# Demo video script (under 3 minutes)

**Before recording:** run `.venv/bin/python -m streamlit run app.py`, open the **Live demo** tab, and play each preset once so it's cached and responds instantly. Record the screen with sound (QuickTime → File → New Screen Recording, with the microphone on for the voice-over).

---

### 0:00–0:20 · The hook
*On screen:* Live demo → preset **Bank debit alert** → **▶ Speak both**. Play the **Plain TTS** audio first.

> "This is a bank alert: ten lakh rupees debited. Listen to what the voice agent actually says."

*(Audio: "ten **zero** rupees has been debited…", "**March fourth**…")*

> "Ten zero rupees. On March fourth. The text said ten lakh rupees, on the third of April."

### 0:20–0:45 · The problem
> "AssemblyAI's TTS promises that prices, dates and confirmation codes come out exactly as written. In India we write money as lakhs, dates as day-month, and we read OTPs digit by digit. So I built **Readback** to test that promise."

### 0:45–1:25 · The scorecard
*On screen:* **Scorecard** tab.

> "Readback speaks 173 hard cases on three voices through the TTS, transcribes them back with AssemblyAI's own verbatim speech-to-text, and checks every critical value."

Point at the numbers:
- "Every Indian-format amount of a lakh or more was misread. Every OTP and PNR was read as an amount: 'four **billion**…' for a train PNR."
- "Medical doses were perfect, which is good news."
- "And this column: **128 of the 230 failures would be hidden** if you checked with formatted speech-to-text, because it turns 'one fifty thousand' back into ₹1,50,000."

*On screen:* **Failures** tab → expand **money-006** → play **Just the critical part**.

### 1:25–1:55 · Security
*On screen:* **Attacks** tab.

> "Then I attacked it. A right-to-left override makes the screen show ₹500 while the voice says **five**. An SSML tag makes a screen showing ₹5 say **fifty thousand rupees**. Invisible characters drop the last digits of an OTP. The user sees one thing and hears another."

### 1:55–2:35 · The fix: SafeSpeak
*On screen:* **Live demo** → play the **SafeSpeak** audio for the bank alert, then switch to the **Hidden-character attack** preset.

> "SafeSpeak sits in front of the TTS. It makes the text match what the screen shows, spells every value out in plain words, speaks it, then transcribes the audio and checks every value. If a value can't be verified, it refuses to speak and falls back to SMS."

*On screen:* **Before / after** tab.

> "Across three voices, plain TTS got 53% of critical values right. With SafeSpeak: 99%, with zero misreads. The last 1% are names the transcriber spelled differently."

### 2:35–2:55 · Close
> "Five bugs found, with reproductions and audio, and a drop-in fix. Readback: if a voice agent reads out your money, it should say what's written."

---

**Tips:** keep the browser zoomed to about 110% so the numbers are readable, mute notifications, and record the bank alert first, since it's the strongest moment.
