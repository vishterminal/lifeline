"""Gmail connect + poll (spec F2). Scope: gmail.readonly only.

IMPLEMENTATION DECISION: Google OAuth and the Gmail REST API are called with
httpx directly (small surface, easy to mock) instead of google-api-python-client.
In CONNECTOR_MODE=mock (or without Google keys) fixture emails are used.
"""
from __future__ import annotations

import base64
import html
import json
import logging
import re
import secrets
from dataclasses import dataclass, field
from datetime import timedelta
from email.utils import parseaddr
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from app.config import DATA_DIR, get_settings
from app.models import ConnectedSource, Consent, User
from app.security import decrypt_secret, encrypt_secret
from app.services import pipeline
from app.timeutil import now_utc, today_local

log = logging.getLogger("lifeline.gmail")

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://gmail.googleapis.com/gmail/v1/users/me"
MAX_BODY = 20_000
FIXTURE_DIR = DATA_DIR / "fixtures" / "emails"


class NeedsReconnect(Exception):
    pass


class UpstreamError(Exception):
    pass


class WrongAccount(Exception):
    """The Google account chosen on the consent screen isn't the one this Lifeline account belongs to."""


@dataclass
class EmailMessage:
    id: str
    internal_ms: int
    sender: str | None
    sender_name: str | None
    subject: str
    auth_results: str | None
    body: str
    links: list[tuple[str, str]] = field(default_factory=list)


def is_live(user: User | None = None) -> bool:
    """Real Gmail only for real accounts; judge demo accounts always use the sample inbox."""
    return get_settings().gmail_live and not (user is not None and user.is_demo)


def get_source(db: Session, user: User) -> ConnectedSource:
    src = db.query(ConnectedSource).filter_by(user_id=user.id, kind="GMAIL").one_or_none()
    if src is None:
        src = ConnectedSource(user_id=user.id, kind="GMAIL", status="DISCONNECTED")
        db.add(src)
        db.flush()
    return src


# --- OAuth ------------------------------------------------------------------------
def build_auth_url(db: Session, user: User) -> str:
    s = get_settings()
    src = get_source(db, user)
    src.oauth_state = secrets.token_urlsafe(32)
    if not is_live(user):
        # Mock: the "consent screen" is our own callback with a fake code.
        return "/api/sources/gmail/callback?" + urlencode({"code": "mock-code", "state": src.oauth_state})
    return AUTH_URL + "?" + urlencode({
        "client_id": s.google_client_id,
        "redirect_uri": s.google_redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "false",
        "state": src.oauth_state,
    })


def complete_oauth(db: Session, code: str, state: str) -> ConnectedSource:
    if not state or not code:
        raise ValueError("missing code/state")
    src = db.query(ConnectedSource).filter_by(kind="GMAIL", oauth_state=state).one_or_none()
    if src is None:
        raise PermissionError("invalid state")
    src.oauth_state = None  # single use
    owner = db.get(User, src.user_id)
    if is_live(owner):
        s = get_settings()
        r = httpx.post(TOKEN_URL, data={
            "code": code, "client_id": s.google_client_id, "client_secret": s.google_client_secret,
            "redirect_uri": s.google_redirect_uri, "grant_type": "authorization_code",
        }, timeout=20)
        if r.status_code != 200:
            src.status, src.last_error = "ERROR", f"token_exchange_{r.status_code}"
            raise UpstreamError("token exchange failed")
        tok = r.json()
        granted = set((tok.get("scope") or "").split())
        if granted - {SCOPE}:
            _revoke(tok.get("refresh_token") or tok.get("access_token"))
            src.status, src.last_error = "ERROR", "extra_scopes_refused"
            raise PermissionError("scopes beyond gmail.readonly were granted; refused")
        if not tok.get("refresh_token"):
            src.status, src.last_error = "ERROR", "no_refresh_token"
            raise UpstreamError("no refresh token returned")
        src.encrypted_refresh_token = encrypt_secret(tok["refresh_token"])
        prof = httpx.get(f"{API}/profile", headers={"Authorization": f"Bearer {tok['access_token']}"}, timeout=20)
        address = prof.json().get("emailAddress") if prof.status_code == 200 else None
        # Only the mailbox of the account owner may be connected: knowing someone's email and
        # signing up with it must never be enough to read their mail.
        if not address or address.strip().lower() != (owner.email or "").strip().lower():
            _revoke(tok.get("refresh_token") or tok.get("access_token"))
            src.status, src.last_error = "ERROR", "wrong_google_account"
            raise WrongAccount(address or "unknown")
        src.gmail_address = address
    else:
        src.encrypted_refresh_token = None
        src.gmail_address = "mock-inbox@lifeline.local"
    src.status = "CONNECTED"
    src.last_error = None
    src.consented_at = now_utc()
    # Start from "now minus 2 days" to match the newer_than:2d query.
    src.gmail_cursor_ms = int((now_utc() - timedelta(days=2)).timestamp() * 1000)
    db.add(Consent(user_id=src.user_id, kind="GMAIL"))
    db.flush()
    return src


def _revoke(token: str | None) -> None:
    if not token:
        return
    try:
        httpx.post(REVOKE_URL, params={"token": token}, timeout=10)
    except httpx.HTTPError:
        log.warning("gmail revoke failed")


def disconnect(db: Session, user: User) -> None:
    src = get_source(db, user)
    if src.encrypted_refresh_token and is_live(user):
        _revoke(decrypt_secret(src.encrypted_refresh_token))
    src.encrypted_refresh_token = None
    src.status = "DISCONNECTED"
    src.gmail_cursor_ms = None
    for c in db.query(Consent).filter_by(user_id=user.id, kind="GMAIL", revoked_at=None):
        c.revoked_at = now_utc()


# --- Fetching ------------------------------------------------------------------
def _b64(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


_A_TAG = re.compile(r"<a\b[^>]*?href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")


def html_to_text(h: str) -> str:
    h = re.sub(r"(?is)<(script|style).*?</\1>", " ", h)
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", h)
    return html.unescape(_TAG.sub(" ", h))


def extract_links(h: str) -> list[tuple[str, str]]:
    return [(href, html.unescape(_TAG.sub("", text)).strip()) for href, text in _A_TAG.findall(h)][:50]


def parse_message(msg: dict) -> EmailMessage:
    payload = msg.get("payload", {})
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
    plain, htm = [], []

    def walk(part):
        mt = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data and mt == "text/plain":
            plain.append(_b64(data))
        elif data and mt == "text/html":
            htm.append(_b64(data))
        for p in part.get("parts", []) or []:
            walk(p)

    walk(payload)
    html_all = "\n".join(htm)
    body = "\n".join(plain) if plain else html_to_text(html_all)
    name, addr = parseaddr(headers.get("from", ""))
    subject = headers.get("subject", "")
    return EmailMessage(
        id=msg["id"], internal_ms=int(msg.get("internalDate", 0)), sender=addr or None,
        sender_name=name or None, subject=subject, auth_results=headers.get("authentication-results"),
        body=f"{subject}\n{body}"[:MAX_BODY], links=extract_links(html_all),
    )


def _access_token(src: ConnectedSource) -> str:
    s = get_settings()
    refresh = decrypt_secret(src.encrypted_refresh_token or "")
    if not refresh:
        raise NeedsReconnect("no token")
    r = httpx.post(TOKEN_URL, data={"client_id": s.google_client_id, "client_secret": s.google_client_secret,
                                    "refresh_token": refresh, "grant_type": "refresh_token"}, timeout=20)
    if r.status_code in (400, 401) and "invalid_grant" in r.text:
        raise NeedsReconnect("invalid_grant")  # Testing-mode tokens expire after ~7 days
    if r.status_code != 200:
        raise UpstreamError(f"token_refresh_{r.status_code}")
    return r.json()["access_token"]


def _explain(r: httpx.Response) -> str:
    """Turn a Gmail API error into a message the user can act on (no mail content)."""
    try:
        err = r.json().get("error", {})
    except ValueError:
        err = {}
    reasons = {d.get("reason") for d in err.get("details", []) if isinstance(d, dict)}
    reasons |= {e.get("reason") for e in err.get("errors", []) if isinstance(e, dict)}
    if "SERVICE_DISABLED" in reasons or "accessNotConfigured" in reasons:
        return ("Gmail API is not enabled in your Google Cloud project. Enable it (APIs & Services → "
                "Library → Gmail API → Enable), wait 2-3 minutes, then check again.")
    if "ACCESS_TOKEN_SCOPE_INSUFFICIENT" in reasons or "insufficientPermissions" in reasons:
        return "Gmail read permission was not granted. Disconnect and connect Gmail again, and allow access."
    if r.status_code == 429:
        return "Gmail rate limit reached. Try again in a minute."
    return f"Gmail API error {r.status_code}: {(err.get('message') or '')[:200]}"


def _get(client: httpx.Client, url: str, token: str, params=None) -> dict:
    for attempt in range(2):  # one retry with backoff for idempotent GETs
        try:
            r = client.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
        except httpx.HTTPError as e:
            if attempt:
                raise UpstreamError(type(e).__name__) from e
            continue
        if r.status_code == 401:
            raise NeedsReconnect("unauthorized")
        if r.status_code in (429, 500, 502, 503) and not attempt:
            import time

            time.sleep(1.5)
            continue
        if r.status_code != 200:
            raise UpstreamError(_explain(r))
        return r.json()
    raise UpstreamError("gmail_retry_exhausted")


def fetch_live(src: ConnectedSource) -> list[EmailMessage]:
    s = get_settings()
    token = _access_token(src)
    cursor = src.gmail_cursor_ms or 0
    q = s.gmail_query + (f" after:{cursor // 1000}" if cursor else "")
    out: list[EmailMessage] = []
    with httpx.Client(timeout=20) as c:
        if not src.gmail_address:  # profile lookup may have failed at connect time
            src.gmail_address = _get(c, f"{API}/profile", token).get("emailAddress")
        page = None
        ids: list[str] = []
        for _ in range(3):
            params = {"q": q, "maxResults": 50}
            if page:
                params["pageToken"] = page
            data = _get(c, f"{API}/messages", token, params)
            ids += [m["id"] for m in data.get("messages", [])]
            page = data.get("nextPageToken")
            if not page:
                break
        for mid in ids:  # only messages that matched the bill query are fetched
            m = parse_message(_get(c, f"{API}/messages/{mid}", token, {"format": "full"}))
            if m.internal_ms > cursor:
                out.append(m)
    return out


# --- Mock fixtures ----------------------------------------------------------------
_DATE_TOKEN = re.compile(r"\{\{date:([+-]\d+)(?::([^}]+))?\}\}")


def render_fixture_text(s: str) -> str:
    today = today_local()
    return _DATE_TOKEN.sub(lambda m: (today + timedelta(days=int(m.group(1)))).strftime(m.group(2) or "%d %b %Y"), s)


def load_fixture(name: str) -> EmailMessage:
    raw = json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8-sig"))
    body_html = render_fixture_text(raw.get("html", ""))
    body = render_fixture_text(raw.get("text", "")) or html_to_text(body_html)
    subject = render_fixture_text(raw.get("subject", ""))
    name_, addr = parseaddr(raw["from"])
    internal = int((now_utc() - timedelta(hours=raw.get("hours_ago", 1))).timestamp() * 1000)
    return EmailMessage(id=f"fixture-{name}", internal_ms=internal, sender=addr, sender_name=name_ or None,
                        subject=subject, auth_results=raw.get("authentication_results"),
                        body=f"{subject}\n{body}"[:MAX_BODY], links=extract_links(body_html))


def mock_inbox_names() -> list[str]:
    return sorted(p.stem for p in FIXTURE_DIR.glob("*.json") if not p.stem.startswith("_"))


def fetch_mock(src: ConnectedSource) -> list[EmailMessage]:
    cursor = src.gmail_cursor_ms or 0
    msgs = [load_fixture(n) for n in mock_inbox_names()]
    return [m for m in msgs if m.internal_ms > cursor]


# --- Poll -----------------------------------------------------------------------
def sync(db: Session, user: User) -> dict:
    src = get_source(db, user)
    if src.status not in ("CONNECTED", "ERROR"):
        return {"fetched": 0, "saved": 0, "needs_review": 0, "flagged": 0, "status": src.status, "error": src.last_error}
    try:
        msgs = fetch_live(src) if is_live(user) else fetch_mock(src)
    except NeedsReconnect as e:
        src.status, src.last_error = "NEEDS_RECONNECT", f"reconnect_required:{e}"
        return {"fetched": 0, "saved": 0, "needs_review": 0, "flagged": 0, "status": src.status, "error": src.last_error}
    except UpstreamError as e:
        src.status, src.last_error = "ERROR", str(e)[:500]
        return {"fetched": 0, "saved": 0, "needs_review": 0, "flagged": 0, "status": src.status, "error": src.last_error}
    counts = {"fetched": len(msgs), "saved": 0, "needs_review": 0, "flagged": 0}
    items = []  # per-email result for the UI (sender + subject + outcome; nothing is stored)
    origin = "REAL" if is_live(user) else "DEMO"
    for m in sorted(msgs, key=lambda x: x.internal_ms):
        res = pipeline.process_incoming(db, user, "GMAIL", m.body, pipeline.IncomingMeta(
            sender=m.sender, sender_name=m.sender_name, auth_results=m.auth_results, links=m.links, origin=origin))
        items.append({"from": m.sender_name or m.sender, "address": m.sender, "subject": m.subject[:120],
                      "outcome": res.outcome, "summary": res.summary, "reason": res.reason})
        if res.outcome in ("SAVED", "PAID_DETECTED", "CHARGE_RECORDED"):
            counts["saved"] += 1
        elif res.outcome == "NEEDS_CONFIRMATION":
            counts["needs_review"] += 1
        elif res.outcome == "SUSPICIOUS":
            counts["flagged"] += 1
        src.gmail_cursor_ms = max(src.gmail_cursor_ms or 0, m.internal_ms)
    if not is_live(user):
        # Fixture timestamps are relative to "now"; mark the mock inbox read up to now.
        src.gmail_cursor_ms = int(now_utc().timestamp() * 1000)
    src.status, src.last_error, src.last_sync_at = "CONNECTED", None, now_utc()
    return {**counts, "status": src.status, "error": None, "items": items}
