# Discord drafts. Nothing here has been posted.

Check the hackathon's bug-bounty format first and adapt these to it. Listen to the clips for each bug (the dashboard's **Failures** tab) before posting; only BUG-001's original case has been confirmed by ear so far.

---

## 1. Bug report: Indian digit grouping (BUG-001)

**TTS misreads Indian-format amounts: ₹10,00,000 → "ten zero rupees"**

Any amount written with Indian digit grouping (`X,XX,XXX`) is spoken wrong on every voice I tried (anna, alba, george: 30/30). The normalizer seems to read each lakh/crore group as its own number:

• ₹1,50,000 → "one fifty thousand rupees"
• ₹10,00,000 → "ten zero rupees"
• ₹1,00,000 → "one zero rupees" (alba: "ten rupees")
• ₹3,45,67,890 → "three forty five sixty seven thousand eight hundred ninety rupees"

The same amount as ₹150,000 or ₹150000 is read correctly. It happens with ₹, Rs., "rupees", or no currency at all ("population 1,50,000").
Repro: Voice Agent API, `greeting: "Your balance is ₹10,00,000."`, any voice.
Note: formatted STT turns the misread back into "₹1,50,000", so a pipeline that checks TTS with formatted STT won't catch this. Use `format_text=false`.
Clips + full table: [link to repo]/findings/BUG-001.md

---

## 2. Bug report: codes read as amounts (BUG-002)

**OTPs, PNRs and pincodes are read as cardinal numbers**

• OTP 482910 → "four hundred eighty two thousand nine hundred ten"
• OTP 033705 → "thirty three thousand seven hundred five" (leading zero lost)
• PNR 4521367890 → "four billion five hundred twenty one million…"
• (080) 4567 8901 → "eighty four thousand five hundred sixty seven eight thousand nine hundred one"
• +91-90000-00001 → "plus ninety one minus ninety thousand minus one"

9/9 OTPs, 5/5 PNRs and 5/5 pincodes were affected. `+91 98765 43210` was read correctly.
Details: [link]/findings/BUG-002.md

---

## 3. Bug report: DD/MM dates (BUG-003)

**03/04/2026 is read as "March fourth" on an en-GB voice**

03/04/2026 → "March fourth", 12/11/2026 → "December eleventh", 01.02.1990 → "January second". DD/MM is standard in India and the UK; voice `anna` is British English.
Details: [link]/findings/BUG-003.md

---

## 4. Security finding (BUG-005)

**Hidden characters and SSML in the input make the voice say something other than what the screen shows**

• `₹‮005‬` (right-to-left override) shows "₹500" but is spoken "five"
• `<sub alias="fifty thousand rupees">₹5</sub>` shows "₹5" in an HTML UI but is spoken "sub alias fifty thousand rupees"
• Word joiners inside an OTP drop its last two digits
• A zero-width space in ₹10000 → "ten rupees zero"
15/21 attack cases diverge. I'd suggest stripping Unicode format characters and either supporting or escaping SSML-like markup in `greeting`.
Details + mitigation: [link]/findings/BUG-005.md

---

## 5. Project submission

**Readback: does the TTS say exactly what's written?**

Readback stress-tests AssemblyAI's TTS on the things Indian voice agents read out every day: lakh/crore amounts, OTPs, PNRs, doses, DD/MM dates, and hidden-character attacks. It speaks 173 cases, transcribes them back with Universal (`format_text=false`), and scores every critical value automatically.

• Found 5 bugs: Indian digit grouping, codes read as amounts, DD/MM dates, letter codes read as words (unconfirmed), and display/speech divergence attacks
• 43 of the 76 misreads would be invisible to a formatted-STT check
• **SafeSpeak**, a drop-in layer, makes the text match what the screen shows, spells every value out in plain words, verifies the audio and refuses when it can't verify: 52% → 98% correct, with 0 misreads (76 before)
• Streamlit dashboard with ear-check workflow, attack table, before/after, and a live side-by-side demo

Repo: [link] · Demo: [video link]
