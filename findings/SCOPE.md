# Where the misreads happen in a real voice agent

All five bugs come from the TTS **text normalizer**: the step that turns "₹10,00,000" into words before the voice speaks. Live tests with the Voice Agent API (on 18–19 Oct 2026) show where that matters in a real agent.

## 1. Text the voice reads word for word: always affected
An outbound call's opening line (the `greeting`) goes straight to the voice with no AI in between. This is where businesses put account data: EMI reminders, OTP calls, refill and appointment reminders.

Reproduced through the app's live-call flow (`experiments/call_probe.py`, voice `anna`):

| Written in the opening line | The caller heard |
|---|---|
| Your EMI … is due on **05/01/2027** | "due on **May first**, twenty twenty seven" |
| Your outstanding loan balance is **₹10,00,000** | "**ten zero** rupees" |

## 2. Values the agent's AI looks up: usually fine
When the agent fetched values with a tool call, its AI wrote them out as words itself: "ten lakh rupees", "April third", the OTP digit by digit (`experiments/agent_probe.py`). The normalizer had nothing to get wrong.

## 3. Digits the agent has already seen: the misread spreads
The agent's AI copies digits it has seen earlier in the conversation. After an opening line containing "₹10,00,000", the caller asked "what is my outstanding balance?":

| | Agent's text | The caller heard |
|---|---|---|
| Plain | "Your outstanding loan balance is **₹10,00,000** …" | "**ten zero** rupees" |
| With SafeSpeak | "Your outstanding loan balance is **ten lakh rupees** …" | "ten lakh rupees" |

So one raw value in the opening line causes misreads later in the conversation too. SafeSpeak fixes both, because the agent only ever sees the spelled-out words.

## Not tested
- Agents connected to their own LLM ("bring your own LLM"). These are affected whenever that LLM writes digits, which most do.
- AssemblyAI's upcoming standalone TTS model (TTS-1). Its promise ("prices … come out exactly as written") is exactly what these tests check.
