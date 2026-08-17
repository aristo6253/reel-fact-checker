import json

from app.history import get_cached, list_all, save_check


def test_get_cached_returns_none_when_not_present(tmp_path):
    db_path = str(tmp_path / "history.db")
    assert get_cached(db_path, "abc123") is None


def test_save_and_get_cached_round_trips(tmp_path):
    db_path = str(tmp_path / "history.db")
    result = {"headline_verdict": "ok", "trustworthiness_score": 90, "claims": []}

    save_check(db_path, "abc123", "https://www.instagram.com/reel/abc123/", "hello world", json.dumps(result))
    cached = get_cached(db_path, "abc123")

    assert cached["url"] == "https://www.instagram.com/reel/abc123/"
    assert cached["transcript"] == "hello world"
    assert cached["result"] == result
    assert cached["checked_at"]


def test_save_check_overwrites_existing_entry_for_same_shortcode(tmp_path):
    db_path = str(tmp_path / "history.db")
    save_check(db_path, "abc123", "https://x/", None, json.dumps({"headline_verdict": "old", "trustworthiness_score": None, "claims": []}))
    save_check(db_path, "abc123", "https://x/", None, json.dumps({"headline_verdict": "new", "trustworthiness_score": None, "claims": []}))

    cached = get_cached(db_path, "abc123")
    assert cached["result"]["headline_verdict"] == "new"


def test_save_check_creates_missing_parent_directory(tmp_path):
    db_path = str(tmp_path / "nested" / "dir" / "history.db")
    save_check(db_path, "abc123", "https://x/", None, json.dumps({"headline_verdict": "ok", "trustworthiness_score": None, "claims": []}))
    assert get_cached(db_path, "abc123") is not None


def test_list_all_returns_empty_list_when_nothing_saved(tmp_path):
    db_path = str(tmp_path / "history.db")
    assert list_all(db_path) == []


def test_list_all_includes_reel_metadata_newest_first(tmp_path):
    db_path = str(tmp_path / "history.db")
    save_check(
        db_path,
        "first",
        "https://x/first/",
        None,
        json.dumps({"headline_verdict": "first verdict", "trustworthiness_score": 40, "claims": []}),
        username="alice",
        caption="First caption",
        product_type="clips",
        thumbnail_url="https://x/thumb1.jpg",
    )
    save_check(
        db_path,
        "second",
        "https://x/second/",
        None,
        json.dumps({"headline_verdict": "second verdict", "trustworthiness_score": 90, "claims": []}),
        username="bob",
        caption="Second caption",
        product_type="carousel",
        thumbnail_url="https://x/thumb2.jpg",
    )

    entries = list_all(db_path)

    assert [e["shortcode"] for e in entries] == ["second", "first"]
    assert entries[0]["username"] == "bob"
    assert entries[0]["caption"] == "Second caption"
    assert entries[0]["product_type"] == "carousel"
    assert entries[0]["thumbnail_url"] == "https://x/thumb2.jpg"
    assert entries[0]["headline_verdict"] == "second verdict"
    assert entries[0]["trustworthiness_score"] == 90
