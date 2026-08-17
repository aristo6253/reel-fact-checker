import json
import os

# ponytail: single global subscription in a flat file — fine for a personal/single-device
# app with no accounts; a real multi-user version would key subscriptions per user.


def save_subscription(path: str, subscription: dict) -> None:
    dirname = os.path.dirname(path)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    with open(path, "w") as f:
        json.dump(subscription, f)


def load_subscription(path: str) -> dict | None:
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)
