"""Verify Telegram Mini App ``initData`` — authenticate the WebApp user.

A Mini App sends ``window.Telegram.WebApp.initData`` (a signed query string) with
each request. We recompute its HMAC with the bot token to prove it really came
from Telegram and wasn't forged, then extract the user. This is the only trusted
source of "who is calling" for the Mini App — never trust a user id from the body.

Spec: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from app.core.logger import get_logger

_log = get_logger(__name__)


def verify_init_data(
    init_data: str, bot_token: str, *, max_age_seconds: int = 86_400
) -> dict | None:
    """Return the authenticated user dict if ``init_data`` is valid, else ``None``."""
    if not init_data or not bot_token:
        return None
    try:
        pairs = dict(parse_qsl(init_data, strict_parsing=False))
    except ValueError:
        return None

    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None

    # data_check_string: remaining fields as "key=value", sorted, joined by "\n".
    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, received_hash):
        _log.info("mini app initData signature mismatch")
        return None

    # Reject stale payloads (replay protection).
    auth_date = pairs.get("auth_date")
    if auth_date and auth_date.isdigit():
        if time.time() - int(auth_date) > max_age_seconds:
            _log.info("mini app initData expired")
            return None

    user_raw = pairs.get("user")
    if not user_raw:
        return None
    try:
        user = json.loads(user_raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(user, dict) or "id" not in user:
        return None
    return user
