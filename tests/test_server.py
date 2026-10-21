"""The product's API, offline: TTS, speech-to-text and the AssemblyAI token call are stubbed."""

import base64
import time

import pytest
from fastapi.testclient import TestClient

import server.app as srv
from server.templates import TEMPLATES, load_customers, render

ROWS = load_customers()
EMI = TEMPLATES["emi"]["text"]


async def fake_check(text: str, voice: str) -> dict:
    """Plain TTS 'misreads' any Indian-grouped amount; SafeSpeak holds one back and flags the tampered record."""
    misread = "," in text and "₹" in text
    held = "Priya" in text
    tampered = "Tampered" in text
    return {
        "text": text,
        "voice": voice,
        "plain": {"heard": "…", "checks": [{"value": "₹x", "status": "FAIL" if misread else "PASS", "reason": "stub"}],
                  "verdict": "misread" if misread else "correct", "audio": "/api/audio/x.wav"},
        "safespeak": {"said": "…", "heard": "…", "checks": [], "verdict": "correct", "alerts": [],
                      "status": "DO_NOT_SPEAK" if held else "SPOKEN", "tampered": tampered, "audio": "/api/audio/y.wav"},
    }


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(srv, "check_message", fake_check)
    monkeypatch.setattr(srv.campaign_lib, "CAMPAIGN_DIR", tmp_path / "campaigns")
    monkeypatch.setattr(srv, "CAMPAIGNS", {})
    monkeypatch.delenv("READBACK_PASSCODE", raising=False)
    with TestClient(srv.app) as c:
        yield c


def test_templates_and_customers(client):
    t = client.get("/api/templates").json()
    assert set(t) == {"emi", "otp", "pharmacy", "loan"}
    assert "balance" in t["emi"]["placeholders"]
    rows = client.get("/api/customers").json()
    assert len(rows) == 12 and rows[0]["name"] == "Aarav Sharma"


def test_every_template_renders_for_every_demo_customer():
    for tpl in TEMPLATES.values():
        for row in ROWS:
            render(tpl["text"], row)


def test_preview_flags_known_risks(client):
    p = client.post("/api/preview", json={"template": EMI, "row": ROWS[0]}).json()
    risks = {v["written"]: (v["risk"] or {}).get("bug") for v in p["values"]}
    assert risks["₹10,00,000"] == "BUG-001"
    assert risks["05/01/2027"] == "BUG-003"
    assert risks["1800 425 1111"] == "BUG-002"
    assert risks["₹24,999"] is None  # under a lakh: plain TTS reads it fine
    assert "ten lakh rupees" in p["spoken_text"]


def test_preview_of_tampered_record_raises_alerts(client):
    p = client.post("/api/preview", json={"template": TEMPLATES["otp"]["text"], "row": ROWS[11]}).json()
    assert any(a["severity"] == "critical" for a in p["alerts"])
    assert "five hundred rupees" in p["spoken_text"]


def test_preview_reports_missing_values(client):
    r = client.post("/api/preview", json={"template": "Hi {name}, pay {nothing}", "row": ROWS[0]})
    assert r.status_code == 400 and "{nothing}" in r.json()["detail"]


def test_check_uses_the_checker(client):
    r = client.post("/api/check", json={"text": "Your balance is ₹10,00,000.", "voice": "anna"}).json()
    assert r["plain"]["verdict"] == "misread" and r["safespeak"]["status"] == "SPOKEN"
    assert client.post("/api/check", json={"text": "hi", "voice": "nobody"}).status_code == 400


def test_campaign_lifecycle_and_report(client):
    started = client.post("/api/campaigns", json={"template": EMI, "rows": ROWS, "voice": "anna"}).json()
    cid = started["id"]
    for _ in range(100):
        view = client.get(f"/api/campaigns/{cid}").json()
        if view["status"] == "done":
            break
        time.sleep(0.05)
    assert view["status"] == "done" and view["done"] == 12
    s = view["summary"]
    assert s["total"] == 12 and s["errors"] == 0
    assert s["held_back"] == 1 and s["review"] == 1 and s["ready"] == 10
    assert s["plain_misread"] >= 10
    csv_text = client.get(f"/api/campaigns/{cid}/report.csv").text
    assert csv_text.splitlines()[0].startswith("customer,message")
    assert len(csv_text.strip().splitlines()) == 13
    assert "Held back: send as SMS" in csv_text and "Review: hidden characters in record" in csv_text


def test_campaign_records_bad_rows_without_stopping(client):
    rows = [ROWS[0], {"id": "x", "name": "No data"}]
    cid = client.post("/api/campaigns", json={"template": EMI, "rows": rows}).json()["id"]
    for _ in range(100):
        view = client.get(f"/api/campaigns/{cid}").json()
        if view["status"] == "done":
            break
        time.sleep(0.05)
    assert view["summary"]["errors"] == 1 and view["results"][1]["action"] == "Error"
    assert client.get("/api/campaigns/nope").status_code == 404


def test_call_config_raw_vs_safespeak(client):
    raw = client.post("/api/call/config", json={"template": EMI, "row": ROWS[0], "safespeak": False}).json()
    safe = client.post("/api/call/config", json={"template": EMI, "row": ROWS[0], "safespeak": True}).json()
    assert raw["session"]["greeting"] == render(EMI, ROWS[0])
    assert "ten lakh rupees" in safe["session"]["greeting"] and "₹" not in safe["session"]["greeting"]
    assert safe["session"]["tools"][0]["name"] == "get_account"
    assert safe["session"]["output"]["voice"] == "anna"


def test_call_tool(client):
    safe = client.post("/api/call/tool", json={"name": "get_account", "row": ROWS[0], "safespeak": True}).json()["result"]
    raw = client.post("/api/call/tool", json={"name": "get_account", "row": ROWS[0], "safespeak": False}).json()["result"]
    assert safe["balance"] == "ten lakh rupees" and raw["balance"] == "₹10,00,000"
    assert safe["name"] == "Aarav Sharma"
    assert client.post("/api/call/tool", json={"name": "transfer_money", "row": ROWS[0]}).status_code == 400


def test_call_token_and_check(client, monkeypatch):
    async def fake_token():
        return "tok123"

    monkeypatch.setattr(srv, "fetch_call_token", fake_token)
    assert client.get("/api/call/token").json() == {"token": "tok123"}

    heard = {"text": "Hello Aarav Sharma, your balance is ten zero rupees."}
    monkeypatch.setattr(srv, "cached_transcribe", lambda *a, **k: heard)
    audio = base64.b64encode(b"\0\0" * 24_000).decode()
    body = {"audio": audio, "rendered": "Hello Aarav Sharma, your balance is ₹10,00,000.", "greeting": "…", "safespeak": False}
    r = client.post("/api/call/check", json=body).json()
    assert r["verdict"] == "misread"
    assert client.post("/api/call/check", json={**body, "audio": "!!"}).status_code == 400

    heard["text"] = "Your outstanding balance is ten rupees."
    followup = {**body, "rendered": "Your outstanding balance is ten lakh rupees.",
                "greeting": "Your outstanding balance is ten lakh rupees."}
    result = client.post("/api/call/check", json=followup).json()
    assert result["verdict"] == "misread" and len(result["checks"]) == 1
    heard["text"] = "Welcome back."
    result = client.post("/api/call/check", json={**body, "rendered": "Welcome back.", "greeting": "Welcome back."}).json()
    assert result["verdict"] == "not_checked"


def test_audio_keys_are_validated(client):
    assert client.get("/api/audio/../../.env.wav").status_code == 404
    assert client.get("/api/audio/" + "0" * 40 + ".wav").status_code == 404


def test_evidence_comes_from_the_snapshot(client):
    e = client.get("/api/evidence").json()
    assert e["results"] == 519 and e["misreads_before"] == 230 and e["misreads_after"] == 0


def test_passcode_gate(client, monkeypatch):
    monkeypatch.setenv("READBACK_PASSCODE", "letmein")
    assert client.get("/api/customers").status_code == 401
    assert client.get("/api/customers", headers={"x-passcode": "letmein"}).status_code == 200
    assert client.get("/api/config").json()["passcode_required"] is True
