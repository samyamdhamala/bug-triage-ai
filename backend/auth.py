"""
Password hashing + JWT bearer sessions.

Deliberately minimal: no refresh tokens, no email verification, no password
reset flow. Just enough to replace DEFAULT_ORG_SLUG with real per-org
identity — those are separate features to add if/when they're needed, not
prerequisites for multi-tenancy to work at all.
"""

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Header, HTTPException

JWT_ALGORITHM = "HS256"
DEFAULT_JWT_EXPIRES_MINUTES = 10080  # 7 days


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def _jwt_secret() -> str:
    return os.environ["JWT_SECRET"]


def create_access_token(user_id: uuid.UUID, org_id: uuid.UUID, role: str) -> str:
    expires_minutes = int(os.environ.get("JWT_EXPIRES_MINUTES", DEFAULT_JWT_EXPIRES_MINUTES))
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "org_id": str(org_id),
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)


class InvalidToken(ValueError):
    pass


@dataclass
class AuthedUser:
    user_id: uuid.UUID
    org_id: uuid.UUID
    role: str


def decode_access_token(token: str) -> AuthedUser:
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise InvalidToken("Token expired")
    except jwt.InvalidTokenError:
        raise InvalidToken("Invalid token")

    return AuthedUser(
        user_id=uuid.UUID(payload["sub"]),
        org_id=uuid.UUID(payload["org_id"]),
        role=payload["role"],
    )


def get_current_user(authorization: str = Header(default="")) -> AuthedUser:
    """FastAPI dependency: resolves the caller's identity from a `Bearer <jwt>`
    Authorization header. This is what replaced DEFAULT_ORG_SLUG — org_id now
    comes from who's actually logged in, not a hardcoded env var."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")

    token = authorization[len("Bearer "):]
    try:
        return decode_access_token(token)
    except InvalidToken as e:
        raise HTTPException(status_code=401, detail=str(e))
