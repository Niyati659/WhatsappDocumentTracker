import difflib
import hashlib
import os
import re
import secrets
import traceback

from dotenv import load_dotenv

load_dotenv()

from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from twilio.request_validator import RequestValidator

from app import db
from app.classify import DOC_TYPES, classify_document
from app.whatsapp import download_media, send_whatsapp_message

CHECKLIST_TYPES = [t for t in DOC_TYPES if t != "UNKNOWN"]

LABELS = {
    "KYC": "KYC (Aadhaar/PAN)",
    "POLICY_COPY": "Policy copy / health card",
    "DISCHARGE_SUMMARY": "Discharge summary",
    "HOSPITAL_BILL": "Final hospital bill",
    "INVESTIGATION_REPORT": "Investigation reports",
    "CONSULTATION_PAPERS": "Consultation papers",
    "PHARMACY_BILL": "Pharmacy bills",
    "CANCELLED_CHEQUE": "Cancelled cheque",
}

@asynccontextmanager
async def lifespan(_app):
    db.init_db()
    yield


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
basic_auth = HTTPBasic()
twilio_validator = RequestValidator(os.environ["TWILIO_AUTH_TOKEN"])
PORTAL_USER = os.environ.get("PORTAL_USER", "agent")
PORTAL_PASSWORD = os.environ["PORTAL_PASSWORD"]
PUBLIC_BASE_URL = os.environ["PUBLIC_BASE_URL"].rstrip("/")


def require_agent(credentials: HTTPBasicCredentials = Depends(basic_auth)):
    user_ok = secrets.compare_digest(credentials.username.encode(), PORTAL_USER.encode())
    pass_ok = secrets.compare_digest(credentials.password.encode(), PORTAL_PASSWORD.encode())
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": 'Basic realm="Claim tracker"'},
        )


PORTAL_PATH = Path(__file__).parent / "templates" / "index.html"


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_agent)])
def portal():
    return PORTAL_PATH.read_text(encoding="utf-8")


@app.get("/api/checklist", dependencies=[Depends(require_agent)])
def api_checklist():
    phones = db.get_all_phones()
    patients = []
    for phone in phones:
        docs = db.get_documents_for_phone(phone)
        pages = db.get_page_counts(phone)
        reviews = db.get_review_counts(phone)
        checklist = [
            {
                "type": t,
                "label": LABELS[t],
                "status": docs.get(t, "missing"),
                "files": pages.get(t, 0),
                "to_check": reviews.get(t, 0),
            }
            for t in CHECKLIST_TYPES
        ]
        patients.append(
            {"phone": phone, "name": db.get_expected_name(phone), "checklist": checklist}
        )
    return {"patients": patients, "events": db.get_recent_events()}


def require_portal_request(request: Request):
    if request.headers.get("X-Requested-With") != "portal":
        raise HTTPException(status_code=400, detail="Missing portal header")


class PatientAction(BaseModel):
    phone: str
    doc_type: str | None = None


@app.post(
    "/api/patients/approve",
    dependencies=[Depends(require_agent), Depends(require_portal_request)],
)
def approve_document(action: PatientAction):
    if action.doc_type not in CHECKLIST_TYPES:
        raise HTTPException(status_code=400, detail="Unknown document type")
    changed = db.approve_documents(action.phone, action.doc_type)
    if changed:
        db.log_event(action.phone, action.doc_type, "approved_by_agent")
    return {"approved": changed}


@app.post(
    "/api/patients/reset-name",
    dependencies=[Depends(require_agent), Depends(require_portal_request)],
)
def reset_name(action: PatientAction):
    db.clear_expected_name(action.phone)
    db.log_event(action.phone, None, "name_reset_by_agent")
    return {"ok": True}


@app.post(
    "/api/patients/clear",
    dependencies=[Depends(require_agent), Depends(require_portal_request)],
)
def clear_patient(action: PatientAction):
    db.clear_patient(action.phone)
    return {"ok": True}


@app.post(
    "/api/clear-all",
    dependencies=[Depends(require_agent), Depends(require_portal_request)],
)
def clear_all():
    db.clear_all()
    return {"ok": True}


def _name_tokens(name):
    return [t for t in re.findall(r"[a-z]+", name.lower()) if len(t) > 1]


def names_roughly_match(a, b):
    ta, tb = _name_tokens(a), _name_tokens(b)
    if not ta or not tb:
        return True
    need = min(2, len(ta), len(tb))
    used, matched = set(), 0
    for x in ta:
        for i, y in enumerate(tb):
            if i not in used and difflib.SequenceMatcher(None, x, y).ratio() >= 0.8:
                used.add(i)
                matched += 1
                break
    return matched >= need


def handle_classified_document(phone, file_bytes, item):
    doc_type = item.get("type", "UNKNOWN")
    if doc_type not in CHECKLIST_TYPES:
        db.log_event(phone, doc_type, "unrecognised_document")
        return

    is_blurry = item.get("blurry", False)
    patient_name = item.get("patient_name_on_document")
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    if db.is_duplicate(phone, doc_type, file_hash):
        db.log_event(phone, doc_type, "duplicate_ignored")
        return

    expected_name = db.get_expected_name(phone)
    if expected_name and patient_name and not names_roughly_match(expected_name, patient_name):
        db.add_document(phone, doc_type, "review", file_hash)
        db.log_event(phone, doc_type, "wrong_patient_suspected", detail=patient_name)
        return
    if not expected_name and patient_name:
        db.set_expected_name(phone, patient_name)

    db.add_document(phone, doc_type, "blurry" if is_blurry else "received", file_hash)
    db.log_event(phone, doc_type, "blurry" if is_blurry else "received")


def build_pending_message(missing_labels):
    lines = "\n".join(f"- {label}" for label in missing_labels)
    return (
        "Thanks for sending your documents! Here's what we still need from you:\n"
        f"{lines}\n"
        "Please send these whenever you can so we can keep processing your claim."
    )


def process_media(from_number, media_items):
    try:
        for media_url, content_type in media_items:
            file_bytes = download_media(media_url)
            if db.has_file(from_number, hashlib.sha256(file_bytes).hexdigest()):
                db.log_event(from_number, None, "duplicate_ignored")
                continue
            for item in classify_document(file_bytes, content_type):
                handle_classified_document(from_number, file_bytes, item)
    except Exception as exc:
        traceback.print_exc()
        db.log_event(from_number, None, "processing_failed", detail=type(exc).__name__)
        return

    docs = db.get_documents_for_phone(from_number)
    missing = [LABELS[t] for t in CHECKLIST_TYPES if docs.get(t) != "received"]
    if missing:
        try:
            send_whatsapp_message(from_number, build_pending_message(missing))
        except Exception:
            db.log_event(from_number, None, "auto_reply_failed")


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    form = await request.form()
    params = {k: v for k, v in form.items()}
    signature = request.headers.get("X-Twilio-Signature", "")
    if not twilio_validator.validate(PUBLIC_BASE_URL + "/webhook/whatsapp", params, signature):
        raise HTTPException(status_code=403, detail="Invalid signature")

    from_number = params.get("From")
    num_media = int(params.get("NumMedia", 0))
    media_items = [
        (params[f"MediaUrl{i}"], params[f"MediaContentType{i}"]) for i in range(num_media)
    ]
    if media_items:
        await run_in_threadpool(process_media, from_number, media_items)

    return PlainTextResponse("", status_code=200)
