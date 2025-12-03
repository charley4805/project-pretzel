# app/auth_utils.py

import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

from jose import JWTError, jwt

# 🔐 Secret & algorithm (same for encode + decode)
SECRET_KEY = (
    os.getenv("JWT_SECRET_KEY")
    or os.getenv("SECRET_KEY")
    or "dev-secret-change-me"  # only for local dev
)
ALGORITHM = "HS256"

# Token lifetime – 7 days by default for dev
ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "10080")
)


def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create a signed JWT containing the fields in `data`.

    We EXPECT at least:
        {"sub": "<user-id-uuid-string>"}
    but this function is agnostic and just encodes what you pass.
    """
    to_encode = data.copy()
    now = datetime.now(timezone.utc)

    if expires_delta is None:
        expires_delta = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    expire = now + expires_delta

    # Standard JWT claims
    to_encode.update(
        {
            "iat": now,
            "exp": expire,
        }
    )

    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Decode a JWT and return its payload dict, or None if invalid/expired.

    ✅ Supports multiple legacy claim names:
      - "sub"
      - "user_id"
      - "uid"

    We normalize them so that caller can always read payload["sub"].
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None

    # Try the known user-id style claims
    user_id = (
        payload.get("sub")
        or payload.get("user_id")
        or payload.get("uid")
    )

    if not user_id:
        return None

    # Normalize so downstream always uses "sub"
    payload["sub"] = str(user_id)
    return payload
