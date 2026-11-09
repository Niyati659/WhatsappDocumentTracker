import json
import os
import re
import time

from google import genai
from google.genai import errors, types

MAX_ATTEMPTS = 6

MODELS = [
    os.environ.get("GEMINI_MODEL", "gemini-flash-latest"),
    os.environ.get("GEMINI_FALLBACK_MODEL", "gemini-flash-lite-latest"),
]

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

SYSTEM_PROMPT = f"""You classify documents sent by insurance claim patients.
Valid document types: {", ".join(DOC_TYPES)}.

A single file may contain MORE THAN ONE document (e.g. a PDF with a discharge
summary followed by a hospital bill) - list every distinct document you see.

For each document you find, return:
- type: one of the valid types above
- blurry: true if the image/scan is too unclear to read the key details confidently
- patient_name_on_document: the patient name printed on the document, if visible, else null

Respond with ONLY a JSON array, no other text. Example:
[{{"type": "DISCHARGE_SUMMARY", "blurry": false, "patient_name_on_document": "Ramesh Kumar"}}]
"""

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


_exhausted_until = {}
EXHAUSTED_COOLDOWN_SECONDS = 3600


def _generate(file_bytes, content_type):
    for model in MODELS:
        is_last = model == MODELS[-1]
        if _exhausted_until.get(model, 0) > time.time() and not is_last:
            continue
        try:
            return _generate_with(model, file_bytes, content_type)
        except errors.APIError as exc:
            if exc.code == 429 and "per day" in str(exc) and not is_last:
                _exhausted_until[model] = time.time() + EXHAUSTED_COOLDOWN_SECONDS
                continue
            raise


def _generate_with(model, file_bytes, content_type):
    for attempt in range(MAX_ATTEMPTS):
        try:
            return client.models.generate_content(
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
        except errors.APIError as exc:
            daily = exc.code == 429 and "per day" in str(exc)
            retryable = exc.code in (429, 500, 503) and not daily
            if not retryable or attempt == MAX_ATTEMPTS - 1:
                raise
            match = re.search(r"retry in ([\d.]+)s", str(exc))
            time.sleep(float(match.group(1)) + 1 if match else 5 * (attempt + 1))


def classify_document(file_bytes, content_type):
    response = _generate(file_bytes, content_type)

    try:
        results = json.loads(response.text)
    except (json.JSONDecodeError, TypeError):
        results = [{"type": "UNKNOWN", "blurry": False, "patient_name_on_document": None}]

    return results
