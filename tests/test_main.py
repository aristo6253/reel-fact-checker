from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_healthz_returns_ok():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def _fake_pipeline(url, anthropic_client, http_client, history_db_path, force=False):
    yield {"event": "fetching", "data": {}}
    yield {"event": "done", "data": {"headline_verdict": "ok", "claims": []}}


def test_check_streams_sse_events_on_success():
    with patch("app.main.run_pipeline", _fake_pipeline):
        response = client.get("/api/v1/check?url=https://www.instagram.com/reel/abc123/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: fetching" in response.text
    assert "event: done" in response.text


def test_check_returns_200_with_failed_event_when_rate_limited():
    with patch("app.main.rate_limiter") as mock_limiter:
        mock_limiter.allow.return_value = False
        response = client.get("/api/v1/check?url=https://www.instagram.com/reel/abc123/")

    assert response.status_code == 200
    assert "event: failed" in response.text
    assert "rate limit" in response.text.lower()


def test_check_returns_200_with_failed_event_when_daily_cap_reached():
    with patch("app.main.daily_cap") as mock_cap:
        mock_cap.allow.return_value = False
        response = client.get("/api/v1/check?url=https://www.instagram.com/reel/abc123/")

    assert response.status_code == 200
    assert "event: failed" in response.text
    assert "daily" in response.text.lower()


def test_index_page_renders_form():
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="reel-url"' in response.text
    assert 'id="results"' in response.text


def test_history_page_shows_empty_state_when_no_checks(tmp_path):
    with patch("app.main.settings") as mock_settings:
        mock_settings.history_db_path = str(tmp_path / "history.db")
        response = client.get("/history")

    assert response.status_code == 200
    assert "No reels checked yet" in response.text


def test_history_page_lists_saved_entries(tmp_path):
    from app.history import save_check

    db_path = str(tmp_path / "history.db")
    save_check(
        db_path,
        "abc123",
        "https://www.instagram.com/reel/abc123/",
        None,
        '{"headline_verdict": "Looks accurate", "trustworthiness_score": 85, "claims": []}',
        username="someuser",
        caption="A caption",
        product_type="clips",
        thumbnail_url="https://x/thumb.jpg",
    )

    with patch("app.main.settings") as mock_settings:
        mock_settings.history_db_path = db_path
        response = client.get("/history")

    assert response.status_code == 200
    assert "@someuser" in response.text
    assert "Looks accurate" in response.text
    assert "85" in response.text
    assert "/?url=https%3A//www.instagram.com/reel/abc123/" in response.text


def test_service_worker_served_at_root_scope():
    response = client.get("/sw.js", follow_redirects=False)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/javascript")
    assert "CACHE_NAME" in response.text


def test_manifest_is_served_and_declares_share_target():
    response = client.get("/static/manifest.json")
    assert response.status_code == 200
    data = response.json()
    assert data["share_target"]["action"] == "/share-target"
    assert data["start_url"] == "/"


def test_share_target_redirects_to_foreground_flow_when_no_subscription():
    shared_text = "Check this out https://www.instagram.com/reel/abc123/?utm_source=ig_web_copy_link nice"
    with patch("app.main.load_subscription", return_value=None):
        response = client.get("/share-target", params={"text": shared_text}, follow_redirects=False)

    assert response.status_code in (302, 307)
    location = response.headers["location"]
    assert location.startswith("/?url=")
    assert "instagram.com%2Freel%2Fabc123" in location


def test_share_target_prefers_url_field_over_text():
    with patch("app.main.load_subscription", return_value=None):
        response = client.get(
            "/share-target",
            params={
                "url": "https://www.instagram.com/reel/from-url/",
                "text": "https://www.instagram.com/reel/from-text/",
            },
            follow_redirects=False,
        )

    location = response.headers["location"]
    assert "from-url" in location
    assert "from-text" not in location


def test_share_target_falls_back_to_home_when_no_instagram_url_found():
    response = client.get("/share-target", params={"text": "just some random text"}, follow_redirects=False)

    assert response.headers["location"] == "/"


def test_share_target_starts_background_job_when_subscription_exists():
    subscription = {"endpoint": "https://push.example.com/x", "keys": {"p256dh": "a", "auth": "b"}}
    with patch("app.main.load_subscription", return_value=subscription), patch(
        "app.main.start_job"
    ) as mock_start_job, patch("app.main.create_job", return_value="job-123"):
        response = client.get(
            "/share-target",
            params={"text": "https://www.instagram.com/reel/abc123/"},
            follow_redirects=False,
        )

    assert response.status_code == 200
    assert "checking your reel" in response.text.lower()
    mock_start_job.assert_called_once()
    assert mock_start_job.call_args.args[0] == "job-123"
    assert mock_start_job.call_args.args[1] == "https://www.instagram.com/reel/abc123/"
    assert mock_start_job.call_args.args[5] == subscription


def test_share_target_falls_back_when_rate_limited_even_with_subscription():
    subscription = {"endpoint": "https://push.example.com/x", "keys": {"p256dh": "a", "auth": "b"}}
    with patch("app.main.load_subscription", return_value=subscription), patch(
        "app.main.rate_limiter"
    ) as mock_limiter, patch("app.main.start_job") as mock_start_job:
        mock_limiter.allow.return_value = False
        response = client.get(
            "/share-target",
            params={"text": "https://www.instagram.com/reel/abc123/"},
            follow_redirects=False,
        )

    mock_start_job.assert_not_called()
    assert response.headers["location"].startswith("/?url=")


def test_subscribe_saves_subscription():
    subscription = {"endpoint": "https://push.example.com/x", "keys": {"p256dh": "a", "auth": "b"}}
    with patch("app.main.save_subscription") as mock_save:
        response = client.post("/api/v1/subscribe", json={"subscription": subscription})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    mock_save.assert_called_once()
    assert mock_save.call_args.args[1] == subscription


def test_share_target_actually_schedules_real_background_task(tmp_path):
    # Regression test: exercises the real create_job/start_job path (not mocked), which
    # is the only way to catch "no running event loop" — a plain `def` route handler
    # runs FastAPI's sync routes in a worker thread with no event loop, so
    # asyncio.create_task() inside start_job silently blew up there. Mocking start_job
    # (as the other share-target tests do, deliberately, to avoid real network/AI calls)
    # hides that class of bug entirely.
    import time

    from app import jobs as jobs_module

    subscription = {"endpoint": "https://push.example.com/x", "keys": {"p256dh": "a", "auth": "b"}}

    with patch("app.main.settings") as mock_settings, patch(
        "app.main.load_subscription", return_value=subscription
    ), patch("app.main.create_job", return_value="job-real-123"), patch(
        "app.jobs.run_pipeline", _fake_pipeline
    ), patch("app.jobs._send_push"):
        mock_settings.history_db_path = str(tmp_path / "history.db")
        mock_settings.vapid_private_key = None
        mock_settings.vapid_claims_sub = "mailto:a@b.com"
        mock_settings.anthropic_api_key = "test"
        mock_settings.anthropic_auth_token = None
        mock_settings.anthropic_base_url = "https://api.anthropic.com"

        response = client.get(
            "/share-target",
            params={"text": "https://www.instagram.com/reel/abc123/"},
            follow_redirects=False,
        )
        assert response.status_code == 200

        job = None
        for _ in range(50):
            job = jobs_module.get_job("job-real-123")
            if job is not None and job["status"] != "running":
                break
            time.sleep(0.05)

    assert job == {"status": "done", "result": {"headline_verdict": "ok", "claims": []}}
