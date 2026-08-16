from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_healthz_returns_ok():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def _fake_pipeline(url, anthropic_client, http_client):
    yield {"event": "fetching", "data": {}}
    yield {"event": "done", "data": {"headline_verdict": "ok", "claims": []}}


def test_check_streams_sse_events_on_success():
    with patch("app.main.run_pipeline", _fake_pipeline):
        response = client.get("/api/v1/check?url=https://www.instagram.com/reel/abc123/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: fetching" in response.text
    assert "event: done" in response.text


def test_check_returns_429_when_rate_limited():
    with patch("app.main.rate_limiter") as mock_limiter:
        mock_limiter.allow.return_value = False
        response = client.get("/api/v1/check?url=https://www.instagram.com/reel/abc123/")

    assert response.status_code == 429
    assert "rate limit" in response.text.lower()


def test_check_returns_503_when_daily_cap_reached():
    with patch("app.main.daily_cap") as mock_cap:
        mock_cap.allow.return_value = False
        response = client.get("/api/v1/check?url=https://www.instagram.com/reel/abc123/")

    assert response.status_code == 503
    assert "daily" in response.text.lower()
