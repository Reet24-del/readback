"""End-to-end check of the Live call flow without a microphone, through the running app's own API.

Starts from the server (token, call config, tool), talks to AssemblyAI's Voice Agent API exactly like
static/call.js does, asks one typed follow-up question, and sends the greeting audio to /api/call/check.

    .venv/bin/python -m uvicorn server.app:app --port 8000     # in another terminal
    .venv/bin/python experiments/call_probe.py
"""

import asyncio
import base64
import json
import sys
from pathlib import Path

import httpx
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
APP = "http://127.0.0.1:8000"
WS = "wss://agents.assemblyai.com/v1/ws"


async def call(safespeak: bool) -> dict:
    async with httpx.AsyncClient(base_url=APP, timeout=120) as http:
        templates = (await http.get("/api/templates")).json()
        row = (await http.get("/api/customers")).json()[0]
        cfg = (await http.post("/api/call/config", json={"template": templates["emi"]["text"], "template_id": "emi", "row": row, "safespeak": safespeak})).json()
        token = (await http.get("/api/call/token")).json()["token"]

        greeting_audio, answer_audio, transcripts, pending, last = [], [], [], [], None
        greeting_done = asked = False
        asked_at = 0
        tool_calls = 0
        async with websockets.connect(f"{WS}?token={token}", max_size=None) as ws:
            await ws.send(json.dumps({"type": "session.update", "session": cfg["session"]}))
            async with asyncio.timeout(120):
                while True:
                    ev = json.loads(await ws.recv())
                    kind = ev.get("type")
                    if kind in ("reply.started", "input.speech.started"):
                        last = kind
                    elif kind == "reply.audio":
                        (answer_audio if greeting_done else greeting_audio).append(base64.b64decode(ev["data"]))
                    elif kind == "transcript.agent":
                        transcripts.append(ev["text"])
                    elif kind == "tool.call":
                        tool_calls += 1
                        result = (await http.post("/api/call/tool", json={"name": ev["name"], "row": row, "safespeak": safespeak})).json()["result"]
                        pending.append({"call_id": ev["call_id"], "result": json.dumps(result, ensure_ascii=False)})
                    elif kind == "reply.done":
                        last = "reply.done"
                        if not greeting_done:
                            greeting_done = True
                        for p in pending:
                            await ws.send(json.dumps({"type": "tool.result", **p}))
                        sent, pending = bool(pending), []
                        if not asked:
                            asked, asked_at = True, len(transcripts)
                            await ws.send(json.dumps({"type": "conversation.message", "role": "user", "content": "Sorry, what is my outstanding balance and when is the EMI due?"}))
                            await ws.send(json.dumps({"type": "reply.create"}))
                        elif not sent and len(transcripts) > asked_at:
                            break  # the agent has answered the question (with or without its tool)
                    elif kind in ("session.error", "error"):
                        raise RuntimeError(ev)
            await ws.send(json.dumps({"type": "session.end"}))

        audio = base64.b64encode(b"".join(greeting_audio)).decode()
        check = (await http.post("/api/call/check", json={"audio": audio, "rendered": cfg["rendered"], "greeting": cfg["greeting"], "safespeak": safespeak})).json()
        from readback.stt import cached_transcribe
        from readback.tts import Clip

        answer_heard = cached_transcribe("verbatim", Clip(b"".join(answer_audio), 24000))["text"] if answer_audio else ""
        return {"transcripts": transcripts, "tool_calls": tool_calls, "check": check, "answer_heard": answer_heard}


async def main() -> None:
    for safespeak in (False, True):
        r = await call(safespeak)
        print(f"\n=== SafeSpeak {'ON' if safespeak else 'OFF'} ===")
        for t in r["transcripts"]:
            print("  agent:", t)
        print("  tool calls:", r["tool_calls"])
        print("  greeting heard:", r["check"]["heard"])
        print("  greeting check:", r["check"]["verdict"], [(c["value"], c["status"]) for c in r["check"]["checks"]])
        print("  follow-up heard:", r["answer_heard"])


asyncio.run(main())
