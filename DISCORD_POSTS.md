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
Clips + full table: https://github.com/Reet24-del/readback/blob/main/findings/BUG-001.md

---

## 2. Bug report: codes read as amounts (BUG-002)

**OTPs, PNRs and pincodes are read as cardinal numbers**

• OTP 482910 → "four hundred eighty two thousand nine hundred ten"
• OTP 033705 → "thirty three thousand seven hundred five" (leading zero lost)
• PNR 4521367890 → "four billion five hundred twenty one million…"
• (080) 4567 8901 → "eighty four thousand five hundred sixty seven eight thousand nine hundred one"
• +91-90000-00001 → "plus ninety one minus ninety thousand minus one"

27/27 OTPs, 15/15 PNRs and 15/15 pincodes were affected across three voices. `+91 98765 43210` was read correctly.
Details: https://github.com/Reet24-del/readback/blob/main/findings/BUG-002.md

---

## 3. Bug report: DD/MM dates (BUG-003)

**03/04/2026 is read as "March fourth" on an en-GB voice**

03/04/2026 → "March fourth", 12/11/2026 → "December eleventh", 01.02.1990 → "January second". DD/MM is standard in India and the UK; voice `anna` is British English.
Details: https://github.com/Reet24-del/readback/blob/main/findings/BUG-003.md

---

## 4. Security finding (BUG-005)

**Hidden characters and SSML in the input make the voice say something other than what the screen shows**

• `₹‮005‬` (right-to-left override) shows "₹500" but is spoken "five"
• `<sub alias="fifty thousand rupees">₹5</sub>` shows "₹5" in an HTML UI but is spoken "sub alias fifty thousand rupees"
• Word joiners inside an OTP drop its last two digits
• A zero-width space in ₹10000 → "ten rupees zero"
43/63 attack results diverge across three voices. I'd suggest stripping Unicode format characters and either supporting or escaping SSML-like markup in `greeting`.
Details + mitigation: https://github.com/Reet24-del/readback/blob/main/findings/BUG-005.md

---

## 5. Project submission

**Readback: reminder calls that say numbers right**

Banks and pharmacies in India call customers with reminders like "Your EMI of ₹24,999 is due on 05/01/2027, balance ₹10,00,000". On AssemblyAI's voice agent, that opening line is spoken word for word, and callers hear "due on May first… ten zero rupees". When they ask again, the agent repeats the raw digits and misreads them again.

Readback is the tool for those calls:
• **Compose:** write a reminder; risky amounts, codes and dates are flagged instantly, and you hear the plain vs SafeSpeak version with ✓/✗ per value
• **Campaign:** check a whole customer list before dialling. Demo: plain TTS misreads 11 of 12 calls (27 values); with SafeSpeak, 11 ready, 1 tampered record held for review, 0 misreads
• **Live call:** talk to the agent in your browser; after every reply, Readback checks what the caller actually heard against what the agent meant
• **Evidence:** 173 Indian cases × 3 voices: plain TTS 53% correct → 99% with SafeSpeak, 230 → 0 misreads; 5 bugs found (lakh grouping, codes read as amounts, DD/MM dates, letter codes, hidden-character attacks); 128 of the misreads would be invisible to a formatted-STT check

Built on the Voice Agent API (greeting, tools, browser tokens) and Universal speech-to-text (`format_text=false`).

Repo: https://github.com/Reet24-del/readback · Demo: [video link]
