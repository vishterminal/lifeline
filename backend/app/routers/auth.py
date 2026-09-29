from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.errors import ApiError
from app.models import User
from app.ratelimit import auth_limit, limiter
from app.schemas import AuthOut, LoginIn, ProfileIn, RegisterIn, UserOut
from app.security import create_jwt, hash_password, verify_password

router = APIRouter(tags=["auth"])


@router.post("/auth/register", response_model=AuthOut, status_code=201)
@limiter.limit(auth_limit)
def register(request: Request, body: RegisterIn, db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalar(select(User.id).where(func.lower(User.email) == email)):
        raise ApiError(409, "An account with this email already exists")
    # IMPLEMENTATION DECISION (hackathon build): email/password accounts are judge demo accounts —
    # sources run on sample data. Real, live accounts sign in with Google.
    user = User(email=email, password_hash=hash_password(body.password), name=body.name, is_demo=True)
    db.add(user)
    db.commit()
    return {"token": create_jwt(user.id), "user": user}


@router.post("/auth/demo", response_model=AuthOut, status_code=201)
@limiter.limit(auth_limit)
def judge_demo(request: Request, db: Session = Depends(get_db)):
    """'Enter judge demo': a fresh private demo account (so judges never collide).
    Its sources always run on sample data, even when live Google/Twilio keys exist."""
    import secrets

    user = User(email=f"judge-{secrets.token_hex(4)}@demo.lifeline", name="Judge",
                password_hash=hash_password(secrets.token_urlsafe(24)), is_demo=True)
    db.add(user)
    db.commit()
    return {"token": create_jwt(user.id), "user": user}


@router.post("/auth/login", response_model=AuthOut)
@limiter.limit(auth_limit)
def login(request: Request, body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise ApiError(401, "Wrong email or password")
    return {"token": create_jwt(user.id), "user": user}


@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    return {"user": UserOut.model_validate(user)}


@router.get("/profile", response_model=UserOut)
def get_profile(user: User = Depends(current_user)):
    return user


@router.put("/profile", response_model=UserOut)
def put_profile(body: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    data = body.model_dump(exclude_unset=True)
    if "phone_e164" in data and data["phone_e164"]:
        taken = db.scalar(select(User.id).where(User.phone_e164 == data["phone_e164"], User.id != user.id))
        if taken:
            raise ApiError(409, "That phone number is linked to another account")
    if "balance_amount" in data and "balance_as_of" not in data and data["balance_amount"] is not None:
        from app.timeutil import now_utc

        data["balance_as_of"] = now_utc()
    for k, v in data.items():
        setattr(user, k, v)
    db.merge(user)
    db.commit()
    return user
