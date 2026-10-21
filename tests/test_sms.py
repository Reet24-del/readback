"""Exercise the real Twilio REST adapter using a mock network transport; never send SMS."""

import asyncio
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from server import app as srv
from server import campaign, sms

ACCOUNT = "AC" + "1" * 32
SERVICE = "MG" + "2" * 32
SID = "SM" + "3" * 32
RECIPIENT = "+15005550006"  # Twilio test number, used only inside mocked requests
ROW = {"sms_to": RECIPIENT, "sms_consent": "true", "phone": "+15005550009"}
TEXT = "Your balance is ₹500."


@pytest.fixture(autouse=True)
def isolated_sms(monkeypatch, tmp_path):
    values = {"TWILIO_ACCOUNT_SID": ACCOUNT, "TWILIO_AUTH_TOKEN": "test-token",
              "TWILIO_MESSAGING_SERVICE_SID": SERVICE, "TWILIO_FROM_NUMBER": "",
              "READBACK_PASSCODE": "test-passcode", "READBACK_SMS_ENABLED": "true",
              "READBACK_SMS_STATUS_URL": "https://readback.example/api/sms/status",
              "READBACK_SMS_DB": str(tmp_path / "sms.sqlite3")}
    for k, v in values.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(campaign, "CAMPAIGN_DIR", tmp_path / "campaigns")
    monkeypatch.setattr(srv, "CAMPAIGNS", {})


@pytest.fixture
def provider(monkeypatch):
    requests = []
    responses = []

    def handle(request):
        requests.append(request)
        response = responses.pop(0) if responses else httpx.Response(201, json={"sid": SID, "status": "queued"})
        if isinstance(response, Exception):
            raise response
        return response

    original = httpx.AsyncClient
    monkeypatch.setattr(sms.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    return requests, responses


def send(key="campaign:0", row=None, text=TEXT):
    return asyncio.run(sms.send_fallback(key, ROW if row is None else row, text))


def test_send_uses_customer_and_service_with_durable_deduplication(provider):
    requests, _ = provider
    result = send()
    assert result["status"] == "queued" and result["sid"] == SID
    req = requests[0]
    data = parse_qs(req.content.decode())
    assert str(req.url) == f"https://api.twilio.com/2010-04-01/Accounts/{ACCOUNT}/Messages.json"
    assert req.headers["authorization"].startswith("Basic ")
    assert data["To"] == [RECIPIENT] and data["Body"] == [TEXT]
    assert data["MessagingServiceSid"] == [SERVICE] and "From" not in data
    assert data["StatusCallback"] == [sms.callback_url(result["id"])]
    assert send() == result  # second call opens the persisted DB, no process-local cache
    assert len(requests) == 1
    assert send(text="Different content")["status"] == "not_sent"
    assert len(requests) == 1


def test_sender_number_fallback(provider, monkeypatch):
    monkeypatch.setenv("TWILIO_MESSAGING_SERVICE_SID", "")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+15005550009")
    send()
    data = parse_qs(provider[0][0].content.decode())
    assert data["From"] == ["+15005550009"] and "MessagingServiceSid" not in data


@pytest.mark.parametrize("row,text", [
    ({"phone": RECIPIENT, "sms_consent": "true"}, TEXT),
    ({**ROW, "sms_consent": "false"}, TEXT),
    ({**ROW, "sms_to": "whatsapp:" + RECIPIENT}, TEXT),
    ({**ROW, "sms_to": "5551234"}, TEXT),
    (ROW, "Your balance is ₹\u202e005\u202c."),
    (ROW, "x" * 1601),
])
def test_invalid_or_unconsented_messages_never_reach_provider(provider, row, text):
    assert send(row=row, text=text)["status"] == "not_sent"
    assert not provider[0]


@pytest.mark.parametrize("setting,value", [
    ("READBACK_SMS_ENABLED", "false"), ("READBACK_PASSCODE", ""),
    ("TWILIO_AUTH_TOKEN", ""), ("TWILIO_ACCOUNT_SID", "bad"),
    ("TWILIO_MESSAGING_SERVICE_SID", "bad"), ("READBACK_SMS_STATUS_URL", "http://localhost/api/sms/status"),
])
def test_missing_configuration_prevents_sends(provider, monkeypatch, setting, value):
    monkeypatch.setenv(setting, value)
    assert send()["status"] == "not_sent"
    assert not provider[0]


@pytest.mark.parametrize("response,status", [
    (httpx.Response(400, json={"code": 21610}), "failed"),
    (httpx.Response(503), "unknown"),
    (httpx.ReadTimeout("timeout"), "unknown"),
    (httpx.Response(201, json={"status": "queued"}), "unknown"),
    (httpx.Response(201, json={"status": "queued", "sid": None}), "unknown"),
    (httpx.Response(201, json=["unexpected"]), "unknown"),
    (httpx.Response(400, json=["unexpected"]), "failed"),
])
def test_failures_and_timeouts_are_not_automatically_retried(provider, response, status):
    requests, responses = provider
    responses.append(response)
    result = send()
    assert result["status"] == status
    assert send() == result and len(requests) == 1


def callback(client, job, status="delivered", **overrides):
    form = {"AccountSid": ACCOUNT, "MessageSid": SID, "MessageStatus": status, **overrides}
    signature = RequestValidator("test-token").compute_signature(sms.callback_url(job), form)
    return client.post(f"/api/sms/status?job={job}", data=form, headers={"x-twilio-signature": signature})


def test_signed_callbacks_and_out_of_order_updates(provider):
    result = send()
    with TestClient(srv.app) as client:
        assert client.post(f"/api/sms/status?job={result['id']}", data={"MessageStatus": "delivered"}).status_code == 403
        assert callback(client, result["id"], AccountSid="AC" + "9" * 32).status_code == 403
        assert callback(client, result["id"], MessageSid="SM" + "9" * 32).status_code == 400
        assert callback(client, result["id"]).status_code == 204
        assert callback(client, result["id"], "sent").status_code == 204
        assert callback(client, result["id"]).status_code == 204
    assert sms.get(result["id"])["status"] == "delivered"


def test_timeout_can_be_resolved_by_delivery_callback(provider):
    provider[1].append(httpx.ReadTimeout("timeout"))
    result = send()
    assert result["status"] == "unknown"
    with TestClient(srv.app) as client:
        assert callback(client, result["id"], "undelivered", ErrorCode="30003").status_code == 204
    assert sms.get(result["id"])["status"] == "undelivered"
    assert sms.get(result["id"])["error_code"] == "30003"


def test_callback_before_rest_response_does_not_regress(provider):
    result = send()
    sms.update(result["id"], "delivered", SID)
    assert sms.update(result["id"], "queued", SID)["status"] == "delivered"


def check_result(status="DO_NOT_SPEAK", tampered=False):
    return {"plain": {"verdict": "misread", "checks": []},
            "safespeak": {"status": status, "verdict": "unclear" if status == "DO_NOT_SPEAK" else "correct", "tampered": tampered}}


def test_campaign_sends_only_held_untampered_rows_and_refreshes_reports(provider):
    rows = [{**ROW, "name": name} for name in ("Held", "Safe", "Tampered")]

    async def check(text, voice):
        return check_result("SPOKEN" if "Safe" in text else "DO_NOT_SPEAK", "Tampered" in text)

    c = campaign.Campaign("Hello {name}, pay ₹500.", "anna", rows, send_sms=True)
    asyncio.run(campaign.run(c, check))
    assert len(provider[0]) == 1
    assert c.view()["summary"]["sms_pending"] == 1
    sms.update(c.results[0]["sms"]["id"], "delivered", SID)
    restored = campaign.load(c.id)
    assert restored.view()["summary"]["sms_delivered"] == 1
    assert "delivered" in campaign.report_csv(restored)
    c2 = campaign.Campaign("Hello {name}, pay ₹500.", "anna", rows)
    asyncio.run(campaign.run(c2, check))
    assert len(provider[0]) == 1  # default is check-only


def test_campaign_api_idempotency_and_auth(provider, monkeypatch):
    async def check(text, voice):
        return check_result()

    monkeypatch.setattr(srv, "check_message", check)
    body = {"template": TEXT, "rows": [ROW], "send_sms": True, "request_id": "12345678-1234-1234-1234-123456789abc"}
    headers = {"x-passcode": "test-passcode"}
    with TestClient(srv.app) as client:
        assert client.post("/api/campaigns", json=body).status_code == 401
        assert client.post("/api/campaigns", json={**body, "request_id": None}, headers=headers).status_code == 400
        first = client.post("/api/campaigns", json=body, headers=headers)
        assert first.status_code == 200
        cid = first.json()["id"]
        # Poll the actual background task rather than relying on scheduling order.
        import time
        for _ in range(100):
            view = client.get(f"/api/campaigns/{cid}", headers=headers).json()
            if view["status"] == "done":
                break
            time.sleep(0.01)
        assert view["status"] == "done"
        srv.CAMPAIGNS.clear()  # restart: find the request in durable campaign storage
        assert client.post("/api/campaigns", json=body, headers=headers).json()["id"] == cid
        assert client.post("/api/campaigns", json={**body, "template": "changed"}, headers=headers).status_code == 409
        assert callback(client, view["results"][0]["sms"]["id"]).status_code == 204
        assert client.get(f"/api/campaigns/{cid}", headers=headers).json()["summary"]["sms_delivered"] == 1
    assert len(provider[0]) == 1
