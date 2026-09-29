from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import User
from app.security import decode_jwt


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise ApiError(401, "Not signed in")
    uid = decode_jwt(auth[7:].strip())
    user = db.get(User, uid) if uid else None
    if user is None:
        raise ApiError(401, "Session expired — please sign in again")
    return user
