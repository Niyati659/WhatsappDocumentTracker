import mimetypes
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from app.classify import DOC_TYPES, classify_document

SAMPLES = Path(__file__).parent / "samples"
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}


def expected_from_name(path):
    prefix = path.stem.split("_")[0].upper()
    if prefix == "MULTI":
        return "MULTI"
    for t in DOC_TYPES:
        if path.stem.upper().startswith(t):
            return t
    return None


def main():
    SAMPLES.mkdir(exist_ok=True)
    files = sorted(p for p in SAMPLES.iterdir() if p.suffix.lower() in EXTENSIONS)
    if not files:
        print(f"No images in {SAMPLES}")
        print("Name files like KYC_1.jpg, HOSPITAL_BILL_2.png, MULTI_bundle.pdf")
        return 1

    scored = correct = 0
    for path in files:
        mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        expected = expected_from_name(path)
        try:
            results = classify_document(path.read_bytes(), mime)
        except Exception as exc:
            print(f"{path.name:40} ERROR {type(exc).__name__}: {exc}")
            continue

        found = [r.get("type", "UNKNOWN") for r in results]
        blurry = any(r.get("blurry") for r in results)
        names = {r.get("patient_name_on_document") for r in results if r.get("patient_name_on_document")}

        verdict = ""
        if expected and expected != "MULTI":
            scored += 1
            ok = found == [expected]
            correct += ok
            verdict = "OK  " if ok else "FAIL"
        print(f"{verdict} {path.name:36} expected={expected or '-':20} got={found} blurry={blurry} names={sorted(names)}")

    if scored:
        print(f"\nAccuracy: {correct}/{scored}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
