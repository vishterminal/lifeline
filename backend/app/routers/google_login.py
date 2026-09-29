"""'Continue with Google' sign-in (OpenID Connect: openid email profile).

This is separate from Gmail access: signing in never grants mailbox access.
Gmail is connected afterwards with its own gmail.readonly consent.

The browser navigates to /api/auth/google/start directly (not via fetch), so the
CSRF `state` can be bound to a cookie. Without Google keys a mock sign-in is used.
"""
from __future__ import annotations

import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User
from app.security import create_jwt, hash_password

router = APIRouter(prefix="/auth/google", tags=["auth"])

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
COOKIE = "lifeline_g_state"


def _front(path: str) -> str:
    return get_settings().front_url(path)


@router.get("/start")
def start():
    s = get_settings()
    state = secrets.token_urlsafe(24)
    if s.google_login_live:
        url = AUTH_URL + "?" + urlencode({
            "client_id": s.google_client_id, "redirect_uri": s.google_login_redirect_uri,
            "response_type": "code", "scope": "openid email profile", "state": state,
            "prompt": "select_account",
        })
    else:
        url = "/api/auth/google/callback?" + urlencode({"code": "mock", "state": state})
    resp = RedirectResponse(url, status_code=302)
    resp.set_cookie(COOKIE, state, max_age=600, httponly=True, samesite="lax")
    return resp


def _fail(reason: str) -> RedirectResponse:
    resp = RedirectResponse(_front(f"/login?error={reason}"), status_code=302)
    resp.delete_cookie(COOKIE)
    return resp


@router.get("/callback")
def callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
             db: Session = Depends(get_db)):
    if error:
        return _fail("google_cancelled")
    expected = request.cookies.get(COOKIE)
    if not state or not expected or not secrets.compare_digest(state, expected):
        return _fail("state_mismatch")
    s = get_settings()
    if s.google_login_live:
        try:
            tok = httpx.post(TOKEN_URL, data={
                "code": code, "client_id": s.google_client_id, "client_secret": s.google_client_secret,
                "redirect_uri": s.google_login_redirect_uri, "grant_type": "authorization_code"}, timeout=20)
            if tok.status_code != 200:
                return _fail("google_token_error")
            info = httpx.get(USERINFO_URL, headers={"Authorization": f"Bearer {tok.json()['access_token']}"}, timeout=20)
            if info.status_code != 200:
                return _fail("google_userinfo_error")
            info = info.json()
        except httpx.HTTPError:
            return _fail("google_unreachable")
        if not info.get("email_verified"):
            return _fail("email_not_verified")
    else:
        info = {"sub": "mock-google-user", "email": "demo.google.user@gmail.com", "name": "Demo Google User"}

    sub, email = str(info["sub"]), str(info["email"]).lower()
    user = db.scalar(select(User).where(User.google_sub == sub)) or \
        db.scalar(select(User).where(func.lower(User.email) == email))
    is_new = user is None
    if is_new:
        # Google-only account: random unusable password.
        user = User(email=email, name=info.get("name"), password_hash=hash_password(secrets.token_urlsafe(32)))
        db.add(user)
    user.google_sub = sub
    if not user.name and info.get("name"):
        user.name = info["name"]
    db.commit()
    dest = "/connect" if is_new else "/inbox"
    resp = RedirectResponse(_front(f"/auth/callback#token={create_jwt(user.id)}&next={dest}"), status_code=302)
    resp.delete_cookie(COOKIE)
    return resp
