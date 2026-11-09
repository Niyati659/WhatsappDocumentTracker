import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from app import db, main

POSTGRES = "--postgres" in sys.argv
SCHEMA = "smoketest"


def with_hostaddr(url):
    addr = os.environ.get("NEON_HOSTADDR")
    return url + ("&" if "?" in url else "?") + f"hostaddr={addr}" if addr else url


def drop_schema():
    import psycopg
    from dotenv import dotenv_values

    base = with_hostaddr(dotenv_values(Path(__file__).parent / ".env")["DATABASE_URL_UNPOOLED"])
    with psycopg.connect(base, autocommit=True) as c:
        c.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
    return base


if POSTGRES:
    base = drop_schema()
    import psycopg

    with psycopg.connect(base, autocommit=True) as c:
        c.execute(f"CREATE SCHEMA {SCHEMA}")
    db.DATABASE_URL = base + ("&" if "?" in base else "?") + f"options=-csearch_path%3D{SCHEMA}"
else:
    db.DATABASE_URL = None
    db.DB_PATH = str(Path(__file__).parent / "logic_test.db")
    Path(db.DB_PATH).unlink(missing_ok=True)
db.init_db()

failures = []


def check(label, actual, expected):
    ok = actual == expected
    print(f"{'PASS' if ok else 'FAIL'}  {label}: got {actual!r}, expected {expected!r}")
    if not ok:
        failures.append(label)


def doc(phone, doc_type, name=None, blurry=False, data=b"x"):
    main.handle_classified_document(
        phone, data, {"type": doc_type, "blurry": blurry, "patient_name_on_document": name}
    )


def status(phone):
    return db.get_documents_for_phone(phone)


print("== Name matching ==")
cases = [
    ("Ramesh Kumar", "Ramesh Kumar", True),
    ("Ramesh Kumar", "KUMAR RAMESH", True),
    ("Ramesh Kumar", "R. Kumar", True),
    ("Ramesh Kumar", "Ramesh Kumr", True),
    ("Ramesh Kumar", "Ramesh Kumar Sharma", True),
    ("Gohel Yogita Dineshkumar", "Yogita Gohel", True),
    ("Ramesh Kumar", "Sunita Kumar", False),
    ("Ramesh Kumar", "Suresh Patel", False),
    ("Ramesh Kumar", "Jane Doe", False),
    ("Ramesh Kumar", "रमेश कुमार", True),
]
for a, b, expected in cases:
    check(f"{a!r} vs {b!r}", main.names_roughly_match(a, b), expected)

print("== Flow: first name, mismatch goes to review, agent approves ==")
P = "whatsapp:+910000000001"
doc(P, "KYC", "Ramesh Kumar", data=b"kyc")
check("first document sets the name", db.get_expected_name(P), "Ramesh Kumar")
doc(P, "HOSPITAL_BILL", "Sunita Verma", data=b"bill")
check("mismatch is held for review", status(P).get("HOSPITAL_BILL"), "review")
check("review does not count as received", [t for t, s in status(P).items() if s == "received"], ["KYC"])
check("approve changes one record", db.approve_documents(P, "HOSPITAL_BILL"), 1)
check("approved becomes received", status(P).get("HOSPITAL_BILL"), "received")

print("== Flow: name reset lets the next document set a new name ==")
Q = "whatsapp:+910000000002"
doc(Q, "KYC", "Wrong Person", data=b"a")
doc(Q, "PHARMACY_BILL", "Ramesh Kumar", data=b"b")
check("real patient's document is held", status(Q).get("PHARMACY_BILL"), "review")
db.clear_expected_name(Q)
check("name cleared", db.get_expected_name(Q), None)
doc(Q, "DISCHARGE_SUMMARY", "Ramesh Kumar", data=b"c")
check("next document sets the new name", db.get_expected_name(Q), "Ramesh Kumar")
check("and is received", status(Q).get("DISCHARGE_SUMMARY"), "received")

print("== Flow: no name on the document is accepted ==")
R = "whatsapp:+910000000003"
doc(R, "KYC", "Ramesh Kumar", data=b"k")
doc(R, "CANCELLED_CHEQUE", None, data=b"c")
check("nameless document accepted", status(R).get("CANCELLED_CHEQUE"), "received")

print("== Flow: status precedence ==")
S = "whatsapp:+910000000004"
doc(S, "PHARMACY_BILL", "A B", blurry=True, data=b"1")
check("blurry alone", status(S).get("PHARMACY_BILL"), "blurry")
doc(S, "PHARMACY_BILL", "A B", data=b"2")
check("clear photo wins", status(S).get("PHARMACY_BILL"), "received")
doc(S, "PHARMACY_BILL", "A B", blurry=True, data=b"3")
check("later blurry does not downgrade", status(S).get("PHARMACY_BILL"), "received")
doc(S, "PHARMACY_BILL", "A B", data=b"2")
check("same file again adds no record", db.get_page_counts(S).get("PHARMACY_BILL"), 3)
check("known file detected before classification", db.has_file(S, __import__("hashlib").sha256(b"2").hexdigest()), True)

print("== Clearing ==")
db.clear_patient(S)
check("clear patient removes their records", (status(S), db.get_expected_name(S)), ({}, None))
check("clear patient keeps others", status(P).get("KYC"), "received")
check("clear patient removes their events", [e for e in db.get_recent_events() if e["phone"] == S], [])
db.clear_all()
check("clear all empties patients", db.get_all_phones(), [])
check("clear all empties events", db.get_recent_events(), [])
if not POSTGRES:
    backups = list(Path(db.DB_PATH).parent.glob(Path(db.DB_PATH).name + ".backup-*"))
    check("clear all saved a backup copy", len(backups) >= 1, True)
    for b in backups:
        b.unlink()

print(f"\n{'ALL PASSED' if not failures else 'FAILED: ' + ', '.join(failures)}")
if POSTGRES:
    drop_schema()
else:
    Path(db.DB_PATH).unlink(missing_ok=True)
sys.exit(1 if failures else 0)
