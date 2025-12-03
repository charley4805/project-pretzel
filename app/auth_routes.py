# app/auth_routes.py

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from app.deps import get_db
from app import models, schemas
from app.auth_utils import create_access_token  # you already use this for login

# NOTE: router already has prefix="/auth"
router = APIRouter(prefix="/auth", tags=["auth"])

# Try backend env first, then fall back to frontend one for dev convenience
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID") or os.getenv(
    "NEXT_PUBLIC_GOOGLE_CLIENT_ID"
)


class GoogleAuthRequest(BaseModel):
    id_token: str


@router.post("/google", response_model=schemas.TokenResponse)
def google_login(payload: GoogleAuthRequest, db: Session = Depends(get_db)):
    """
    Accepts a Google ID token from the frontend, verifies it with Google,
    finds or creates a User, and returns a normal JWT access token.
    """
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google auth not configured on server (missing GOOGLE_CLIENT_ID).",
        )

    # ---- Verify Google ID token ----
    try:
        idinfo = id_token.verify_oauth2_token(
            payload.id_token,
            google_requests.Request(),
            GOOGLE_CLIENT_ID,
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Google ID token.",
        )

    email = idinfo.get("email")
    email_verified = idinfo.get("email_verified", True)
    full_name = idinfo.get("name") or ""

    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google account did not provide an email address.",
        )

    if not email_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google account email is not verified.",
        )

    # ---- Find or create user ----
    user = db.query(models.User).filter(models.User.email == email).first()

    if not user:
        user = models.User(
            email=email,
            # For Google users we don't need a real password
            password_hash="",
            is_active=True,
        )

        # Only set these if the model actually has these attributes
        if hasattr(user, "full_name"):
            user.full_name = full_name
        if hasattr(user, "auth_provider"):
            user.auth_provider = "google"
        if hasattr(user, "created_at"):
            user.created_at = datetime.now(timezone.utc)

        db.add(user)
        db.commit()
        db.refresh(user)

    if getattr(user, "is_active", True) is False:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive.",
        )

    # ---- Issue Pretzel JWT ----
    access_token = create_access_token({"sub": str(user.id)})

    # ✅ Include `user` to satisfy TokenResponse schema
    user_payload = {
        "id": str(user.id),
        "email": user.email,
        "full_name": getattr(user, "full_name", None),
        "is_active": getattr(user, "is_active", True),
    }

    return schemas.TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=user_payload,
    )
