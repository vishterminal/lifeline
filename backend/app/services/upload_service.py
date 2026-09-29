"""Photo/PDF upload (spec F5). PDF -> text; image -> local OCR, else the consented
cloud vision path, else a blank confirmation for the user to type in."""
from __future__ import annotations

import io
import logging
import shutil

from sqlalchemy.orm import Session

from app.models import User
from app.services import pipeline
from app.services.extraction import llm_extractor
from app.timeutil import today_local

log = logging.getLogger("lifeline.upload")

MAX_BYTES = 10 * 1024 * 1024
ALLOWED = {"application/pdf": "pdf", "image/jpeg": "image", "image/png": "image", "image/jpg": "image"}


class UnsupportedType(Exception):
    pass


class TooLarge(Exception):
    pass


def sniff_type(data: bytes, declared: str | None) -> str:
    if data[:5] == b"%PDF-":
        return "application/pdf"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    raise UnsupportedType(declared or "unknown")


def pdf_text(data: bytes, max_pages: int = 10) -> str:
    import pdfplumber

    parts = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages[:max_pages]:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)


def ocr_available() -> bool:
    return shutil.which("tesseract") is not None


def image_text(data: bytes) -> str | None:
    if not ocr_available():
        return None
    try:
        import pytesseract
        from PIL import Image

        return pytesseract.image_to_string(Image.open(io.BytesIO(data)))
    except Exception as e:
        log.warning("local OCR failed: %s", type(e).__name__)
        return None


def _blank_confirmation(db: Session, user: User, source_kind: str, origin: str, why: str) -> pipeline.PipelineResult:
    conf = pipeline.create_confirmation(db, user.id, source_kind, origin, "MISSING_FIELDS", {
        "biller": None, "biller_norm": None, "type": "OTHER", "amount": None, "due_date": None,
        "vehicle_ref": None, "message_kind": "DUE_NOTICE", "recurrence_hint": None,
    })
    conf.draft = {**conf.draft, "note": why}
    return pipeline.PipelineResult("NEEDS_CONFIRMATION", confirmation_id=conf.id, reason=why,
                                   summary="Couldn't read that file — please type the details in the app.")


def process_upload(db: Session, user: User, data: bytes, declared_type: str | None,
                   source_kind: str = "UPLOAD", origin: str = "REAL") -> pipeline.PipelineResult:
    if len(data) > MAX_BYTES:
        raise TooLarge()
    media_type = sniff_type(data, declared_type)
    meta = pipeline.IncomingMeta(origin=origin, skip_new_biller_check=source_kind == "UPLOAD")

    if media_type == "application/pdf":
        try:
            text = pdf_text(data)
        except Exception as e:
            log.warning("pdf parse failed: %s", type(e).__name__)
            text = ""
        if text.strip():
            return pipeline.process_incoming(db, user, source_kind, text, meta)
        return _blank_confirmation(db, user, source_kind, origin, "pdf_no_text")

    text = image_text(data)
    if text and text.strip():
        return pipeline.process_incoming(db, user, source_kind, text, meta)
    if user.allow_cloud_image_processing:
        ext, fail = llm_extractor.extract_from_image(data, media_type, today_local())
        if ext and ext.is_bill:
            fields = {
                "biller": ext.biller, "biller_norm": None, "type": ext.obligation_type or "OTHER",
                "amount": str(ext.amount) if ext.amount is not None else None,
                "due_date": ext.due_date.isoformat() if ext.due_date else None,
                "vehicle_ref": ext.vehicle_ref, "message_kind": ext.message_kind,
                "recurrence_hint": ext.recurrence_hint,
            }
            # Single extractor only (no text for rules) -> always ask the user.
            conf = pipeline.create_confirmation(db, user.id, source_kind, origin, "LOW_CONFIDENCE", fields)
            return pipeline.PipelineResult("NEEDS_CONFIRMATION", confirmation_id=conf.id, reason="vision_single_extractor")
        return _blank_confirmation(db, user, source_kind, origin, f"vision_failed:{fail}")
    return _blank_confirmation(db, user, source_kind, origin,
                               "no_local_ocr_and_cloud_image_processing_not_allowed")
