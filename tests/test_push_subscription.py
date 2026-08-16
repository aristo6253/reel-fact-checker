from app.push_subscription import load_subscription, save_subscription


def test_load_subscription_returns_none_when_not_present(tmp_path):
    path = str(tmp_path / "sub.json")
    assert load_subscription(path) is None


def test_save_and_load_subscription_round_trips(tmp_path):
    path = str(tmp_path / "sub.json")
    subscription = {"endpoint": "https://push.example.com/x", "keys": {"p256dh": "a", "auth": "b"}}

    save_subscription(path, subscription)

    assert load_subscription(path) == subscription


def test_save_subscription_overwrites_previous(tmp_path):
    path = str(tmp_path / "sub.json")
    save_subscription(path, {"endpoint": "https://push.example.com/old", "keys": {}})
    save_subscription(path, {"endpoint": "https://push.example.com/new", "keys": {}})

    assert load_subscription(path)["endpoint"] == "https://push.example.com/new"


def test_save_subscription_creates_missing_parent_directory(tmp_path):
    path = str(tmp_path / "nested" / "dir" / "sub.json")
    save_subscription(path, {"endpoint": "https://push.example.com/x", "keys": {}})

    assert load_subscription(path)["endpoint"] == "https://push.example.com/x"
