import mimetypes
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from app import db, main

LIVE = "--live" in sys.argv
if not LIVE:
    db.DATABASE_URL = None
    db.DB_PATH = str(Path(__file__).parent / "e2e_test.db")
    Path(db.DB_PATH).unlink(missing_ok=True)
db.init_db()

SAMPLES = Path(__file__).parent / "samples"
P1, P2, P3 = "whatsapp:+919999900001", "whatsapp:+919999900002", "whatsapp:+919999900003"
failures = []


def send(phone, filename):
    path = SAMPLES / filename
    mime = mimetypes.guess_type(filename)[0] or "image/jpeg"
    data = path.read_bytes()
    for item in main.classify_document(data, mime):
        main.handle_classified_document(phone, data, item)


def rows(phone, doc_type):
    conn = db.get_conn()
    n = conn.execute(
        "SELECT COUNT(*) FROM documents WHERE phone=? AND doc_type=?", (phone, doc_type)
    ).fetchone()[0]
    conn.close()
    return n


def last_event(phone):
    conn = db.get_conn()
    row = conn.execute(
        "SELECT event FROM events WHERE phone=? ORDER BY id DESC LIMIT 1", (phone,)
    ).fetchone()
    conn.close()
    return row["event"] if row else None


def check(label, actual, expected):
    ok = actual == expected
    print(f"{'PASS' if ok else 'FAIL'}  {label}: got {actual!r}, expected {expected!r}")
    if not ok:
        failures.append(label)


print("== Patient 1: normal, duplicate, blurry-then-clear, wrong patient ==")
send(P1, "DISCHARGE_SUMMARY_1.jpg")
check("discharge summary received", db.get_documents_for_phone(P1).get("DISCHARGE_SUMMARY"), "received")

send(P1, "DISCHARGE_SUMMARY_1.jpg")
check("same file twice is ignored", last_event(P1), "duplicate_ignored")
check("duplicate adds no extra row", rows(P1, "DISCHARGE_SUMMARY"), 1)

send(P1, "HOSPITAL_BILL_1_blur.jpg")
check("blurry bill is marked blurry", db.get_documents_for_phone(P1).get("HOSPITAL_BILL"), "blurry")

send(P1, "HOSPITAL_BILL_1.jpg")
check("clear resend upgrades blurry to received", db.get_documents_for_phone(P1).get("HOSPITAL_BILL"), "received")

send(P1, "PHARMACY_BILL_1.jpg")
check("pharmacy bill received", db.get_documents_for_phone(P1).get("PHARMACY_BILL"), "received")

send(P1, "PHARMACY_BILL_1_blur.jpg")
check("later blurry photo does not downgrade a clear one", db.get_documents_for_phone(P1).get("PHARMACY_BILL"), "received")

send(P1, "INVESTIGATION_REPORT_1_dark.jpg")
check("dark investigation report received", db.get_documents_for_phone(P1).get("INVESTIGATION_REPORT"), "received")

before = dict(db.get_documents_for_phone(P1))
send(P1, "DISCHARGE_SUMMARY_3_othername.jpg")
check("other person's document flagged", last_event(P1), "wrong_patient_suspected")
check("other person's document not added", db.get_documents_for_phone(P1), before)

print("== Patient 2: several documents in one PDF ==")
send(P2, "MULTI_bundle.pdf")
got = db.get_documents_for_phone(P2)
check("bundle gives discharge summary", got.get("DISCHARGE_SUMMARY"), "received")
check("bundle gives hospital bill", got.get("HOSPITAL_BILL"), "received")
check("bundle gives pharmacy bill", got.get("PHARMACY_BILL"), "received")

print("== Patient 3: one document sent as two photos ==")
send(P3, "CONSULTATION_PAPERS_1.jpg")
send(P3, "CONSULTATION_PAPERS_1_rot.jpg")
check("two photos give one received entry", db.get_documents_for_phone(P3), {"CONSULTATION_PAPERS": "received"})
check("both photos are kept as files of it", db.get_page_counts(P3).get("CONSULTATION_PAPERS"), 2)

print()
for phone in (P1, P2, P3):
    got = db.get_documents_for_phone(phone)
    print(phone, {k: v for k, v in sorted(got.items())})

print(f"\n{'ALL PASSED' if not failures else 'FAILED: ' + ', '.join(failures)}")
sys.exit(1 if failures else 0)
