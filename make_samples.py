import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

SAMPLES = Path(__file__).parent / "samples"
VARIANT_MARKS = ("_blur", "_dark", "_rot", "_othername")
BASE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
PATIENT = "Ramesh Kumar"
OTHER_PATIENT = "Sunita Verma"


def font(size, bold=False):
    name = "arialbd.ttf" if bold else "arial.ttf"
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        return ImageFont.load_default(size)


def page(title, subtitle, rows, footer=None, patient=PATIENT):
    img = Image.new("RGB", (1000, 1400), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 1000, 130], fill="#1f4e79")
    d.text((40, 30), title, fill="white", font=font(42, True))
    d.text((40, 85), subtitle, fill="#dbe8f5", font=font(24))
    y = 180
    d.text((40, y), f"Patient Name: {patient}", fill="black", font=font(30, True))
    y += 70
    for line in rows:
        d.text((40, y), line, fill="#222", font=font(26))
        y += 52
    if footer:
        d.text((40, 1300), footer, fill="#555", font=font(22))
    return img


def cheque():
    img = Image.new("RGB", (1200, 520), "#fdf6e3")
    d = ImageDraw.Draw(img)
    d.rectangle([10, 10, 1190, 510], outline="#335", width=3)
    d.text((40, 30), "STATE BANK OF INDIA", fill="#123", font=font(40, True))
    d.text((40, 85), "Andheri West Branch, Mumbai   IFSC: SBIN0001234", fill="#333", font=font(24))
    d.text((900, 40), "Date: __ / __ / ____", fill="#333", font=font(24))
    d.text((40, 170), "Pay  ______________________________________________  or bearer", fill="#333", font=font(26))
    d.text((40, 240), "Rupees  ____________________________________________", fill="#333", font=font(26))
    d.rectangle([860, 230, 1160, 290], outline="#333", width=2)
    d.text((40, 340), f"A/c No. 00112233445566   A/c Holder: {PATIENT}", fill="#222", font=font(26))
    d.text((40, 440), "000123   110002003   004567   31", fill="#111", font=font(30))
    d.line([(60, 480), (1140, 130)], fill="#222", width=5)
    d.line([(60, 130), (1140, 480)], fill="#222", width=5)
    d.text((420, 270), "CANCELLED", fill="#8b0000", font=font(60, True))
    return img


def synthetic():
    docs = {
        "DISCHARGE_SUMMARY_1": page(
            "CITY CARE HOSPITAL", "Discharge Summary",
            ["UHID: CCH-448120      IP No: 77391", "Date of Admission: 02-Nov-2026", "Date of Discharge: 06-Nov-2026",
             "Diagnosis: Acute Appendicitis", "Procedure: Laparoscopic Appendectomy",
             "Condition at discharge: Stable, afebrile", "Course in hospital: Admitted with right iliac fossa",
             "pain and fever. Underwent surgery on 03-Nov under GA.", "Uneventful recovery.",
             "Advice: Tab Paracetamol 650mg SOS, wound care,", "review after 7 days with Dr. A. Mehta."],
            "Consultant: Dr. A. Mehta, MS (Surgery)"),
        "HOSPITAL_BILL_1": page(
            "CITY CARE HOSPITAL", "Final In-Patient Bill",
            ["Bill No: FB-99120    IP No: 77391", "Room Charges (4 days)             Rs. 24,000",
             "Operation Theatre Charges         Rs. 38,000", "Surgeon Fees                      Rs. 30,000",
             "Anaesthesia Charges               Rs. 12,000", "Nursing & Consumables              Rs. 9,500",
             "Investigations                    Rs. 7,200", "-------------------------------------------",
             "Gross Total                       Rs. 1,20,700", "Advance Paid                      Rs. 50,000",
             "Net Payable                       Rs. 70,700"],
            "Authorised Signatory"),
        "PHARMACY_BILL_1": page(
            "MEDICARE PHARMACY", "Tax Invoice - GSTIN 27ABCDE1234F1Z5",
            ["Invoice No: PH-55821      Date: 06-Nov-2026", "Item            Batch    Exp     Qty   Amt",
             "Paracetamol 650  B2241   09/28   10    32.00", "Amoxicillin 500  A9921   03/28   15    210.00",
             "Pantoprazole 40  P1182   11/27   10    118.50", "ORS Sachet       S771    06/27   5     60.00",
             "-------------------------------------------", "Total (incl. GST)                  Rs. 420.50"],
            "Drugs once sold will not be taken back"),
        "INVESTIGATION_REPORT_1": page(
            "SURE DIAGNOSTICS LAB", "Laboratory Report - Complete Blood Count",
            ["Sample ID: LB-20917     Collected: 02-Nov-2026", "Test               Result    Reference",
             "Haemoglobin        13.2      13.0 - 17.0 g/dL", "WBC Count          14,800    4,000 - 11,000 /cumm",
             "Neutrophils        82        40 - 70 %", "Platelets          2.4       1.5 - 4.1 lakh/cumm",
             "CRP                48        < 6 mg/L", "Impression: Neutrophilic leucocytosis.", ""],
            "Pathologist: Dr. S. Rao, MD"),
        "CONSULTATION_PAPERS_1": page(
            "Dr. A. MEHTA, MS (Surgery)", "OPD Consultation - City Care Hospital",
            ["Date: 02-Nov-2026      OPD No: 20931", "Complaints: Pain right lower abdomen x 2 days, fever",
             "O/E: Tender RIF, guarding present", "Provisional Dx: Acute appendicitis",
             "Rx:  1. Inj. Ceftriaxone 1g IV", "     2. Tab Paracetamol 650mg SOS", "Advice: USG abdomen, CBC. Admit for surgery.",
             "", ""], "Signature / Reg. No. 54321"),
        "POLICY_COPY_1": page(
            "SECURE LIFE HEALTH INSURANCE", "Policy Schedule / Certificate of Insurance",
            ["Policy No: SLH/2026/00481920", "Plan: Family Floater Health Plus", "Sum Insured: Rs. 5,00,000",
             "Policy Period: 01-Apr-2026 to 31-Mar-2027", "Insured: Ramesh Kumar (Self)", "TPA ID Card No: TPA-7782193",
             "Premium Paid: Rs. 18,450", "Cashless facility available at network hospitals"],
            "Toll free: 1800-000-0000"),
        "CANCELLED_CHEQUE_1": cheque(),
    }
    docs["DISCHARGE_SUMMARY_3_othername"] = page(
        "CITY CARE HOSPITAL", "Discharge Summary",
        ["UHID: CCH-512004      IP No: 80112", "Date of Admission: 10-Oct-2026", "Date of Discharge: 13-Oct-2026",
         "Diagnosis: Dengue fever", "Condition at discharge: Stable"],
        "Consultant: Dr. P. Nair", patient=OTHER_PATIENT)

    for name, img in docs.items():
        out = SAMPLES / f"{name}.jpg"
        if not out.exists():
            img.save(out, quality=92)
            print("created", out.name)

    bundle = SAMPLES / "MULTI_bundle.pdf"
    if not bundle.exists():
        pages = [docs["DISCHARGE_SUMMARY_1"], docs["HOSPITAL_BILL_1"], docs["PHARMACY_BILL_1"]]
        pages[0].save(bundle, save_all=True, append_images=pages[1:])
        print("created", bundle.name)


def variants():
    rng = random.Random(7)
    for src in sorted(SAMPLES.iterdir()):
        if src.suffix.lower() not in BASE_EXT or any(m in src.stem for m in VARIANT_MARKS):
            continue
        img = Image.open(src).convert("RGB")
        made = {
            "_blur": img.filter(ImageFilter.GaussianBlur(9)),
            "_dark": ImageEnhance.Brightness(img).enhance(0.35),
            "_rot": img.rotate(11, expand=True, fillcolor="#444"),
        }
        px = made["_dark"].load()
        for _ in range(img.width * img.height // 40):
            x, y = rng.randrange(img.width), rng.randrange(img.height)
            v = rng.randrange(0, 60)
            px[x, y] = (v, v, v)
        for mark, out_img in made.items():
            out = SAMPLES / f"{src.stem}{mark}.jpg"
            if not out.exists():
                out_img.save(out, quality=70 if mark == "_blur" else 85)
                print("created", out.name)


if __name__ == "__main__":
    SAMPLES.mkdir(exist_ok=True)
    synthetic()
    if "--no-variants" not in sys.argv:
        variants()
    sys.exit(0)
