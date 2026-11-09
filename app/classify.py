import base64
import json
import os
import re
import time

import httpx

DOC_TYPES = [
    "KYC",
    "POLICY_COPY",
    "DISCHARGE_SUMMARY",
    "HOSPITAL_BILL",
    "INVESTIGATION_REPORT",
    "CONSULTATION_PAPERS",
    "PHARMACY_BILL",
    "CANCELLED_CHEQUE",
    "UNKNOWN",
]

# Deployed (Vercel sets VERCEL=1) uses Gemini; local development uses Ollama.
PROVIDER = os.environ.get(
    "CLASSIFIER_PROVIDER", "gemini" if os.environ.get("VERCEL") else "ollama"
).lower()

MAX_ATTEMPTS = 6
MODELS = [
    os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest"),
    os.environ.get("GEMINI_FALLBACK_MODEL", "gemini-flash-latest"),
]

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3-vl:4b")
OLLAMA_MAX_PDF_PAGES = 8

PROMPT_BODY = f"""You classify documents sent by insurance claim patients.
Valid document types: {", ".join(DOC_TYPES)}.

What each type means:
- KYC: identity proof such as Aadhaar, PAN, voter ID, passport or driving licence
- POLICY_COPY: insurance policy schedule/certificate or a health insurance card
- DISCHARGE_SUMMARY: hospital discharge summary with diagnosis, treatment and advice
- HOSPITAL_BILL: final in-patient hospital bill with itemised charges
- INVESTIGATION_REPORT: laboratory, pathology or radiology reports
- CONSULTATION_PAPERS: doctor's OPD notes or prescriptions
- PHARMACY_BILL: medicine shop invoice with batch numbers and expiry
- CANCELLED_CHEQUE: a bank cheque marked cancelled
- UNKNOWN: anything else

A single file may contain MORE THAN ONE document (e.g. a PDF with a discharge
summary followed by a hospital bill) - list every distinct document you see.

For each document you find, return:
- type: one of the valid types above
- blurry: true if the image/scan is too unclear to read the key details confidently
- patient_name_on_document: the patient name printed on the document, if visible, else null
"""

SYSTEM_PROMPT = (
    PROMPT_BODY
    + """
Respond with ONLY a JSON array, no other text. Example:
[{"type": "DISCHARGE_SUMMARY", "blurry": false, "patient_name_on_document": "Ramesh Kumar"}]
"""
)

OLLAMA_PROMPT = (
    PROMPT_BODY
    + """
Respond with ONLY JSON of this form, no other text:
{"documents": [{"type": "DISCHARGE_SUMMARY", "blurry": false, "patient_name_on_document": "Ramesh Kumar"}]}
"""
)

OLLAMA_SCHEMA = {
    "type": "object",
    "properties": {
        "documents": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": DOC_TYPES},
                    "blurry": {"type": "boolean"},
                    "patient_name_on_document": {"type": ["string", "null"]},
                },
                "required": ["type", "blurry", "patient_name_on_document"],
            },
        }
    },
    "required": ["documents"],
}

UNKNOWN_RESULT = {"type": "UNKNOWN", "blurry": False, "patient_name_on_document": None}


def _normalise(results):
    if isinstance(results, dict):
        results = results.get("documents", [])
    cleaned = []
    for item in results if isinstance(results, list) else []:
        if not isinstance(item, dict):
            continue
        doc_type = item.get("type")
        name = item.get("patient_name_on_document")
        cleaned.append(
            {
                "type": doc_type if doc_type in DOC_TYPES else "UNKNOWN",
                "blurry": bool(item.get("blurry", False)),
                "patient_name_on_document": name if isinstance(name, str) and name.strip() else None,
            }
        )
    return cleaned or [dict(UNKNOWN_RESULT)]


# ---------------------------------------------------------------- Gemini

DAILY_COOLDOWN_SECONDS = 3600
DEFAULT_COOLDOWN_SECONDS = 60
MAX_WAIT_SECONDS = 40

_gemini_clients = {}
_cooldown_until = {}


def _gemini_keys():
    pattern = re.compile(r"^GEMINI_API_KEY_?(\d*)$")
    numbered = sorted(
        (int(m.group(1) or 1), name) for name in os.environ if (m := pattern.match(name))
    )
    values = [os.environ[name] for _, name in numbered]
    values += os.environ.get("GEMINI_API_KEYS", "").split(",")
    keys = []
    for value in values:
        value = value.strip()
        if value and value not in keys:
            keys.append(value)
    if not keys:
        raise KeyError("GEMINI_API_KEY")
    return keys


def _gemini(key):
    if key not in _gemini_clients:
        from google import genai

        _gemini_clients[key] = genai.Client(api_key=key)
    return _gemini_clients[key]


def _call_gemini(key, model, file_bytes, content_type):
    from google.genai import types

    return _gemini(key).models.generate_content(
        model=model,
        contents=[
            types.Part.from_bytes(data=file_bytes, mime_type=content_type),
            "Classify this.",
        ],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
        ),
    )


def _cooldown_for(exc):
    if "per day" in str(exc):
        return DAILY_COOLDOWN_SECONDS
    match = re.search(r"retry in ([\d.]+)s", str(exc))
    return float(match.group(1)) + 1 if match else DEFAULT_COOLDOWN_SECONDS


def _gemini_generate(file_bytes, content_type):
    """Try every key and model, moving on whenever one hits its rate limit."""
    from google.genai import errors

    keys = _gemini_keys()
    last_error = None
    for _round in range(2):
        for key in keys:
            for model in MODELS:
                if _cooldown_until.get((key, model), 0) > time.time():
                    continue
                for attempt in range(3):
                    try:
                        return _call_gemini(key, model, file_bytes, content_type)
                    except errors.APIError as exc:
                        last_error = exc
                        if exc.code == 429:
                            _cooldown_until[(key, model)] = time.time() + _cooldown_for(exc)
                            break
                        if exc.code in (500, 503) and attempt < 2:
                            time.sleep(2 * (attempt + 1))
                            continue
                        raise
        soonest = min((t for t in _cooldown_until.values() if t > time.time()), default=0)
        wait = soonest - time.time()
        if wait <= 0 or wait > MAX_WAIT_SECONDS:
            break
        time.sleep(wait + 0.5)
    raise last_error or RuntimeError("All Gemini keys are currently rate limited")


def _classify_gemini(file_bytes, content_type):
    response = _gemini_generate(file_bytes, content_type)
    try:
        return _normalise(json.loads(response.text))
    except (json.JSONDecodeError, TypeError):
        return [dict(UNKNOWN_RESULT)]


# ---------------------------------------------------------------- Ollama


def _pdf_pages_as_png(pdf_bytes):
    import io

    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(pdf_bytes)
    pages = []
    for index in range(min(len(pdf), OLLAMA_MAX_PDF_PAGES)):
        buffer = io.BytesIO()
        pdf[index].render(scale=1.6).to_pil().save(buffer, format="PNG")
        pages.append(buffer.getvalue())
    return pages


def _ollama_chat(image_bytes):
    response = httpx.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": OLLAMA_MODEL,
            "stream": False,
            "format": OLLAMA_SCHEMA,
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": OLLAMA_PROMPT},
                {
                    "role": "user",
                    "content": "Classify this.",
                    "images": [base64.b64encode(image_bytes).decode("ascii")],
                },
            ],
        },
        timeout=900,
    )
    response.raise_for_status()
    return json.loads(response.json()["message"]["content"])


def _classify_ollama(file_bytes, content_type):
    images = _pdf_pages_as_png(file_bytes) if content_type == "application/pdf" else [file_bytes]
    found = []
    for image in images:
        try:
            found.extend(_normalise(_ollama_chat(image)))
        except (json.JSONDecodeError, KeyError):
            found.append(dict(UNKNOWN_RESULT))
    known = [item for item in found if item["type"] != "UNKNOWN"]
    return known or found[:1]


def classify_document(file_bytes, content_type):
    if PROVIDER == "ollama":
        return _classify_ollama(file_bytes, content_type)
    return _classify_gemini(file_bytes, content_type)
