"""
Signed OAuth state tokens.

Carries org_id + integration-specific data (Jira's project_key, Slack's
bugs_channel, ...) through a third-party OAuth redirect without needing
server-side session storage — a plain HMAC + timestamp is enough for CSRF
protection and survives fine across multiple backend replicas, unlike an
in-process dict keyed by a random nonce would.
"""

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from dataclasses import dataclass, field

STATE_TTL_SECONDS = 600  # 10 minutes — plenty for a user to complete a consent screen


class InvalidState(ValueError):
    pass


def _secret() -> bytes:
    return os.environ["OAUTH_STATE_SECRET"].encode()


def _sign(payload: bytes) -> str:
    return hmac.new(_secret(), payload, hashlib.sha256).hexdigest()


@dataclass
class StatePayload:
    org_id: uuid.UUID
    data: dict = field(default_factory=dict)


def create_state(org_id: uuid.UUID, data: dict | None = None) -> str:
    body = json.dumps({"org_id": str(org_id), "data": data or {}, "ts": int(time.time())}).encode()
    body_b64 = base64.urlsafe_b64encode(body).decode()
    signature = _sign(body_b64.encode())
    return f"{body_b64}.{signature}"


def verify_state(token: str) -> StatePayload:
    try:
        body_b64, signature = token.split(".", 1)
    except ValueError:
        raise InvalidState("Malformed state token")

    expected_signature = _sign(body_b64.encode())
    if not hmac.compare_digest(signature, expected_signature):
        raise InvalidState("State signature mismatch — possible CSRF")

    try:
        payload = json.loads(base64.urlsafe_b64decode(body_b64.encode()))
    except (ValueError, json.JSONDecodeError):
        raise InvalidState("Malformed state payload")

    if time.time() - payload["ts"] > STATE_TTL_SECONDS:
        raise InvalidState("State token expired — please retry the connect flow")

    return StatePayload(org_id=uuid.UUID(payload["org_id"]), data=payload.get("data", {}))
