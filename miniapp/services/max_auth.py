from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

# MAX recommends treating initData as valid for one hour.
MAX_INIT_DATA_AGE_SECONDS = 60 * 60


def verify_init_data(init_data: str, bot_token: str) -> dict | None:
    """Validate MAX WebAppData according to the official HMAC algorithm."""
    if not init_data or not bot_token:
        return None
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return None
    if sum(1 for key, _ in pairs if key == "hash") != 1:
        return None

    received_hash = next(value for key, value in pairs if key == "hash")
    launch_params = "\n".join(
        f"{key}={value}" for key, value in sorted(pairs) if key != "hash"
    )
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, launch_params.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed_hash, received_hash):
        return None

    parsed = {key: value for key, value in pairs if key != "hash"}
    auth_date = parsed.get("auth_date", "")
    if not auth_date.isdigit():
        return None
    age = time.time() - int(auth_date)
    if age < -60 or age > MAX_INIT_DATA_AGE_SECONDS:
        return None
    return parsed


def extract_user_id(parsed_init_data: dict) -> int | None:
    raw_user = parsed_init_data.get("user")
    if not raw_user:
        return None
    try:
        value = json.loads(raw_user).get("id")
        return int(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
