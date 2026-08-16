from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import jobs


def test_create_job_starts_in_running_state():
    job_id = jobs.create_job()
    assert jobs.get_job(job_id) == {"status": "running", "result": None}


def test_get_job_returns_none_for_unknown_id():
    assert jobs.get_job("does-not-exist") is None


async def _fake_pipeline_done(url, anthropic_client, http_client, history_db_path, force=False):
    yield {"event": "fetching", "data": {}}
    yield {"event": "done", "data": {"headline_verdict": "All good", "trustworthiness_score": 92, "claims": []}}


async def _fake_pipeline_failed(url, anthropic_client, http_client, history_db_path, force=False):
    yield {"event": "fetching", "data": {}}
    yield {"event": "failed", "data": {"message": "Couldn't access this reel."}}


@pytest.mark.asyncio
async def test_run_job_stores_final_result_on_success():
    job_id = jobs.create_job()

    with patch("app.jobs.run_pipeline", _fake_pipeline_done):
        await jobs._run_job(job_id, "https://x/", MagicMock(), "test.db", False, None, None, "mailto:a@b.com")

    job = jobs.get_job(job_id)
    assert job["status"] == "done"
    assert job["result"]["headline_verdict"] == "All good"


@pytest.mark.asyncio
async def test_run_job_stores_failure_status():
    job_id = jobs.create_job()

    with patch("app.jobs.run_pipeline", _fake_pipeline_failed):
        await jobs._run_job(job_id, "https://x/", MagicMock(), "test.db", False, None, None, "mailto:a@b.com")

    job = jobs.get_job(job_id)
    assert job["status"] == "failed"
    assert "couldn't access" in job["result"]["message"].lower()


@pytest.mark.asyncio
async def test_run_job_sends_push_when_subscription_provided():
    job_id = jobs.create_job()
    subscription = {"endpoint": "https://push.example.com/abc", "keys": {"p256dh": "x", "auth": "y"}}

    with patch("app.jobs.run_pipeline", _fake_pipeline_done), patch("app.jobs._send_push") as mock_send_push:
        await jobs._run_job(job_id, "https://x/", MagicMock(), "test.db", False, subscription, "priv-key", "mailto:a@b.com")

    mock_send_push.assert_called_once()
    args = mock_send_push.call_args.args
    assert args[0] == subscription
    assert args[1]["event"] == "done"
    assert args[2] == "priv-key"


@pytest.mark.asyncio
async def test_run_job_skips_push_when_no_subscription():
    job_id = jobs.create_job()

    with patch("app.jobs.run_pipeline", _fake_pipeline_done), patch("app.jobs._send_push") as mock_send_push:
        await jobs._run_job(job_id, "https://x/", MagicMock(), "test.db", False, None, "priv-key", "mailto:a@b.com")

    mock_send_push.assert_not_called()


@pytest.mark.asyncio
async def test_run_job_survives_pipeline_crash():
    job_id = jobs.create_job()

    async def _crashing_pipeline(*args, **kwargs):
        raise RuntimeError("boom")
        yield  # pragma: no cover - makes this an async generator

    with patch("app.jobs.run_pipeline", _crashing_pipeline):
        await jobs._run_job(job_id, "https://x/", MagicMock(), "test.db", False, None, None, "mailto:a@b.com")

    job = jobs.get_job(job_id)
    assert job["status"] == "failed"


def test_send_push_builds_score_in_title():
    subscription = {"endpoint": "https://push.example.com/abc", "keys": {"p256dh": "x", "auth": "y"}}
    final_event = {"event": "done", "data": {"headline_verdict": "Mostly true", "trustworthiness_score": 77}}

    with patch("app.jobs.webpush") as mock_webpush:
        jobs._send_push(subscription, final_event, "priv-key", "mailto:a@b.com")

    call_kwargs = mock_webpush.call_args.kwargs
    assert call_kwargs["subscription_info"] == subscription
    assert call_kwargs["vapid_private_key"] == "priv-key"
    assert "77/100" in call_kwargs["data"]
    assert "Mostly true" in call_kwargs["data"]


def test_send_push_handles_webpush_exception_gracefully():
    from pywebpush import WebPushException

    subscription = {"endpoint": "https://push.example.com/abc", "keys": {"p256dh": "x", "auth": "y"}}
    final_event = {"event": "done", "data": {"headline_verdict": "ok", "trustworthiness_score": 50}}

    with patch("app.jobs.webpush", side_effect=WebPushException("expired subscription")):
        jobs._send_push(subscription, final_event, "priv-key", "mailto:a@b.com")  # should not raise
