"""Experiment: does the bug survive a real conversational turn with the Voice Agent API's own LLM?

A typed user question (conversation.message + reply.create) makes the agent call a fake bank tool;
we return raw values or SafeSpeak-spelled values, then record what the LLM wrote and what the voice said.

    .venv/bin/python experiments/agent_probe.py
"""

import asyncio
import base64
import json
import sys
from pathlib import Path

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from readback.config import api_key  # noqa: E402
from readback.stt import cached_transcribe  # noqa: E402
from readback.tts import Clip  # noqa: E402

URL = "wss://agents.assemblyai.com/v1/ws"
PROMPT = (
    "You are the phone assistant for Sahayak Bank in India. Answer in one or two short sentences. "
    "Use the get_account tool for any account question. Read amounts, dates and codes exactly as the tool gives them."
)
TOOL = {
    "type": "function",
    "name": "get_account",
    "description": "Get the caller's balance, last debit, its date, and the current OTP.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}
RAW = {"balance": "₹10,00,000", "last_debit": "₹1,50,000", "last_debit_date": "03/04/2026", "otp": "482910"}
SAFE = {
    "balance": "ten lakh rupees",
    "last_debit": "one lakh fifty thousand rupees",
    "last_debit_date": "the third of April, twenty twenty six",
    "otp": "four eight two, nine one zero",
}
QUESTION = "What is my balance, how much was my last debit and when, and what is my OTP?"


async def turn(values: dict) -> dict:
    events, audio, agent_text, pending = [], bytearray(), [], []
    last, answered = None, False
    async with websockets.connect(URL, additional_headers={"Authorization": f"Bearer {api_key()}"}, max_size=None) as ws:
        await ws.send(json.dumps({"type": "session.update", "session": {"system_prompt": PROMPT, "output": {"voice": "anna"}, "tools": [TOOL]}}))
        try:
            async with asyncio.timeout(90):
                while True:
                    ev = json.loads(await ws.recv())
                    kind = ev.get("type")
                    events.append(kind)
                    if kind == "session.ready":
                        await ws.send(json.dumps({"type": "conversation.message", "role": "user", "content": QUESTION}))
                        await ws.send(json.dumps({"type": "reply.create"}))
                    elif kind in ("reply.started", "input.speech.started"):
                        last = kind
                    elif kind == "tool.call":
                        pending.append({"call_id": ev["call_id"], "result": json.dumps(values, ensure_ascii=False)})
                        answered = True
                    elif kind == "reply.audio" and answered and not pending:
                        audio += base64.b64decode(ev["data"])  # only the reply spoken after the tool result
                    elif kind == "transcript.agent":
                        agent_text.append(ev.get("text", ""))
                    elif kind == "reply.done":
                        last = "reply.done"
                        if pending:
                            for p in pending:
                                await ws.send(json.dumps({"type": "tool.result", **p}))
                            pending.clear()
                        elif answered and audio:
                            break
                    elif kind in ("session.error", "error"):
                        raise RuntimeError(ev)
        finally:
            await ws.send(json.dumps({"type": "session.end"}))
    clip = Clip(bytes(audio), 24000)
    heard = cached_transcribe("verbatim", clip)["text"] if audio else ""
    return {"events": events, "llm_text": agent_text, "heard": heard, "audio_ms": clip.duration_ms}


async def main() -> None:
    for label, values in (("RAW tool values", RAW), ("SAFESPEAK tool values", SAFE)):
        r = await turn(values)
        print(f"\n=== {label} ===")
        print("event types :", sorted(set(r["events"])))
        print("LLM wrote   :", r["llm_text"])
        print(f"voice said  : {r['heard']}  ({r['audio_ms']} ms)")


asyncio.run(main())
