# Claimly

**WhatsApp Document Tracker** — automatically classifies insurance claim documents patients send over WhatsApp and keeps a live, per-patient checklist, so agents never have to dig through a chat thread to see what's missing.

## What it does

- Receives WhatsApp messages via a Twilio webhook the moment a patient sends something
- Classifies each image/PDF against the 8 required document types using Gemini vision (with a local Ollama fallback for offline development)
- Keeps a live, per-patient checklist of received / blurry / missing documents
- Handles messy real-world input: multiple documents bundled in one PDF, a single document sent as several photos, duplicate sends, blurry scans, and documents that appear to belong to a different patient
- Serves a password-protected portal showing every patient's status and a recent-activity log, refreshing in real time
- Optionally auto-replies to the patient on WhatsApp with a summary of what's still missing

## Required documents tracked

KYC (Aadhaar/PAN) · Policy copy / health card · Discharge summary · Final hospital bill · Investigation reports · Consultation papers · Pharmacy bills · Cancelled cheque

## Tech stack

- **Backend:** FastAPI (Python)
- **Messaging:** Twilio WhatsApp (Sandbox or production number)
- **Classification:** Google Gemini (vision), with an Ollama local-model fallback for development
- **Database:** SQLite for local dev, Postgres (Neon) in production
- **Deployment:** Vercel

## Project structure

```
app/
  main.py        FastAPI app — webhook, portal API, authentication
  classify.py    Document classification (Gemini / Ollama)
  db.py          Data layer (SQLite locally, Postgres in production)
  whatsapp.py    Twilio send/receive helpers
  templates/
    index.html   Live portal UI
```

## Local setup

1. Create and activate a virtual environment, then install dependencies:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. Copy `.env.example` to `.env` and fill in:
   - `GEMINI_API_KEY`, `GEMINI_MODEL`
   - `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_NUMBER`
   - `PORTAL_USER`, `PORTAL_PASSWORD` — basic-auth login for the portal
   - `PUBLIC_BASE_URL` — the public HTTPS URL used to validate Twilio webhook signatures (e.g. your ngrok URL)
3. Run the server:
   ```
   uvicorn app.main:app --reload --port 8000
   ```
4. Expose it publicly (e.g. `ngrok http 8000`) and point the Twilio WhatsApp Sandbox's **"WHEN A MESSAGE COMES IN"** webhook at `<public-url>/webhook/whatsapp`.

## Deployment

Configured for Vercel (`vercel.json`) with a Postgres database on Neon (`DATABASE_URL`).

## Assignment context

Built for the "WhatsApp Document Tracker" problem statement: track documents patients send over WhatsApp for an insurance claim and keep an up-to-date per-patient checklist, correctly handling bundled PDFs, multi-photo documents, duplicate sends, blurry scans, and documents belonging to a different patient.
