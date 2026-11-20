# ScreenToCare: Clinical Orchestration Prototype

## Overview
ScreenToCare is a Challenge 05 prototype for demonstrating screening-to-care orchestration and national integration patterns.

## Quick Start (Local Development)

1. **Setup Backend Environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   uvicorn main:app --reload --port 8000
   ```
   For a local demo that keeps workflow state across API restarts, configure the state file and optional demo clinician in PowerShell:
   ```powershell
   $env:CAREBRIDGE_LOCAL_STATE_FILE = "$env:LOCALAPPDATA\ScreenToCare\carebridge-state.json"
   $env:CAREBRIDGE_DEMO_CLINICIAN_NAME = "Dr. Kabelo"
   $env:CAREBRIDGE_DEMO_CLINICIAN_EMAIL = "dr.kabelo@health.gov.bw"
   $env:CAREBRIDGE_DEMO_CLINICIAN_PASSWORD = "set-a-private-demo-password"
   $env:CAREBRIDGE_SESSION_SECRET = "replace-with-a-long-random-secret"
   ```
   The local state file can contain patient and clinical data. Protect it accordingly and use synthetic data only. Keep passwords private; for a persistent deployment, use a secrets manager rather than shell history. This local JSON mode is a demo persistence option, not a substitute for PostgreSQL.
   The `CAREBRIDGE_*` environment-variable names and existing data/FHIR identifiers are retained for compatibility with existing local setup and records.

2. **Run the existing React Frontend:**
   ```bash
   cd carebridge-ui
   npm install
   npm run dev
   ```
   For a separately hosted API, set the frontend build variable `VITE_API_BASE_URL` to the backend origin (for example `https://api.example.org`); otherwise the UI uses the current host on port `8000`.

## Create a deployment link with Render

This repository includes a Render Blueprint in `render.yaml`. To deploy it, push the project to a GitHub repository, sign in to Render, choose **New → Blueprint**, and connect that repository. Render will create the API service, static frontend, and PostgreSQL database. The API initializes `schema.sql` automatically when its database is empty.

The Blueprint uses Render's free plans for a demo. Free web services can sleep when idle, and free PostgreSQL databases expire after 30 days; check Render's current plan limits before relying on the link. The frontend's default Render hostname is configured as the API's allowed CORS origin. If Render assigns a different hostname, update `CAREBRIDGE_CORS_ORIGINS` on the API service to the exact frontend URL and redeploy.

After both services deploy, submit the static frontend's `onrender.com` URL as the deployment link. Use only synthetic data in the public demo. Never commit `.env` files, passwords, database dumps, or patient data.

## Separate patient and clinician views

The welcome screen offers separate **Patient portal** and **Hospital / clinician** choices. Hospital users can sign in or register with a name, work email, clinical role, and password. Registration is immediately available for sign-in; there is no administrator approval step. The preloaded demo clinician accounts are Dr. Tlhagiso and Dr. Kabelo; both use the demo PIN `2026`, which the login form fills in. These shared demo credentials are for synthetic local testing only. In-memory mode keeps accounts only for the current process; persistent deployments must apply `schema.sql` and set `DATABASE_URL`.

The API uses PBKDF2-SHA256 password hashes and signed, HTTP-only session cookies; protected workflow APIs require a clinician session. The active account is the audit actor for case access and workflow changes, and sign-off is bound to the authenticated session. Distinct accounts are required for dual-key sign-off. Set a stable, private `CAREBRIDGE_SESSION_SECRET` in deployments and set `CAREBRIDGE_COOKIE_SECURE=true` when serving over HTTPS. This local account system is a prototype, not a substitute for organizational identity management, MFA, rate limiting, or a security review. Do not expose it publicly or enter real patient information.

## Challenge 05 workflow

Without `DATABASE_URL` or `CAREBRIDGE_LOCAL_STATE_FILE`, the app runs in memory and workflow records reset at API restart. Set `CAREBRIDGE_LOCAL_STATE_FILE` to persist workflow state in a local JSON file between restarts. To use the PostgreSQL-backed deployment path, apply `schema.sql` to PostgreSQL and set `DATABASE_URL` before startup; workflow snapshots and audit events are restored from PostgreSQL, and the SLA worker claims due cases from PostgreSQL timestamps.

1. Select **Ingest Field Screening**, enter synthetic patient details, and confirm the signed POPIA / Data Protection Act consent checkbox. Consent is required by both online intake endpoints and the offline queue.
2. The Master Patient Index computes a SHA-256 digest over normalized Omang ID, date of birth, and phone number; matching screenings reuse the same patient ID across facilities. Triage applies transparent keyword rules, emits demo ICD-10/SNOMED-coded tags and a FHIR R4 ServiceRequest/Bundle, assigns an SLA, and places the case in `RESULT_INGESTED`. Use **View FHIR R4 Payload** to inspect the payload and rationale.
3. In **Screening Queue**, select **Generate FHIR ServiceRequest & Dispatch**. In **Referral Handoffs**, inspect simulated English/Setswana notices, simulate arrival, or trigger a DHMT escalation.
4. In **Dual-Key Closures**, attach the receiving-hospital discharge document and clinical outcome, then obtain two distinct clinician sign-offs. Sign out and sign in with a different clinician account for the second signature.
5. Review the append-only **Audit Ledger**. Every workflow event includes timestamp, actor, FHIR reference, previous-event hash, and SHA-256 verification hash.
6. To test offline mode, queue a consented record and reconnect. Records are AES-256-GCM encrypted in IndexedDB; IV and ciphertext are Base64-encoded. The AES key is a non-extractable device-local `CryptoKey` stored in IndexedDB. Legacy plaintext `cb_offline_queue` data is encrypted and removed after successful migration.
7. From the welcome screen, choose **Patient portal** to look up a screening using an Omang ID or case tracking code plus date of birth. The patient view returns only status, urgency, clinic/follow-up information, and plain-language next steps. Use **Exit patient portal** to return to the role selection screen.

The **Impact & Performance Metrics** panel refreshes with the command center data. Turnaround time averages completed case duration, active SLA breach rate excludes closed and offline-only records, referral completion is completed referrals divided by dispatched referrals, and closed-loop conversion is closed cases divided by registered backend cases. **Analyze screening notes** runs a non-persisting triage preview with a draft SMS; **Ingest Field Screening** separately creates the patient case. The AI Assist panel also shows the latest case triage. No preview SMS is sent.

## Deployment integrations

The SLA worker checks for open cases with less than two hours remaining every `SLA_SCHEDULER_INTERVAL_SECONDS` (default 60, minimum 5). It claims PostgreSQL cases with row locks when the database is configured, logs each attempt, and sends a generic webhook to `DHMT_WEBHOOK_URL` when supplied. Live gateway delivery also requires `DHMT_ESCALATION_DESTINATION`; set `DHMT_ESCALATION_CHANNEL` to `sms` or `whatsapp`. Without a URL, attempts are recorded as simulated.

`POST /api/v1/integrations/hie/cases/{case_id}` sends a FHIR Bundle to `{HIE_FHIR_BASE_URL}/Bundle`, using `HIE_BEARER_TOKEN` when configured. `POST /api/v1/integrations/dhis2/monthly?year=YYYY&month=MM` sends monthly screening and closure counts to the configured DHIS2 `dataValueSets` endpoint. Set `DHIS2_BASE_URL`, `DHIS2_ORG_UNIT`, `DHIS2_DATA_SET`, `DHIS2_SCREENINGS_DATA_ELEMENT`, and `DHIS2_CLOSURES_DATA_ELEMENT` for live delivery; without a base URL, the aggregate is written to the local simulated DHIS2 outbox. `/api/v1/sla-alerts` exposes gateway attempt records.

The demo triage rules/codes are not a clinical decision-support model, validated diagnosis, or authoritative coding. The patient portal uses date of birth as a demo verification check, not strong authentication; add rate limiting and an approved identity-verification flow before exposing it publicly. Account sign-in and distinct-account sign-off provide demo attribution, not proof of professional credentials or non-repudiation. The offline key protects persisted queue contents from casual storage inspection but does not protect against XSS, a compromised browser profile, or a device owner with access to the running origin. Before handling real patient data, add organizational identity management/MFA, use HTTPS, manage encryption keys, and review security, retention, and consent processes. HIE, DHIS2, and gateway endpoints are not configured in this workspace; live connectivity has not been verified. Setswana wording also needs fluent-speaker review.

API endpoints used by the dashboard:

- `GET /api/v1/cases`, `GET /api/v1/referrals`, and `GET /api/v1/audit`
- `GET /api/v1/cases/{case_id}` (records the authenticated case-open event)
- `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `GET /api/v1/auth/me`, and `POST /api/v1/auth/logout`
- `GET /api/v1/metrics/impact`
- `POST /api/v1/patient-portal/lookup` (Omang ID or tracking code with date-of-birth verification)
- `GET /api/v1/sla-alerts`
- `POST /api/v1/screening/triage` and `POST /api/v1/screening/ingest`
- `POST /api/v1/screening/triage-preview` (analyzes non-identifying notes without creating a case)
- `POST /api/v1/cases/{case_id}/dispatch`
- `POST /api/v1/cases/{case_id}/arrival` and `POST /api/v1/cases/{case_id}/escalate`
- `POST /api/v1/cases/{case_id}/discharge-summary`
- `POST /api/v1/cases/{case_id}/signoff`
- `POST /api/v1/cases/{case_id}/close`
- `POST /api/v1/sync/queue`
- `POST /api/v1/integrations/hie/cases/{case_id}`
- `POST /api/v1/integrations/dhis2/monthly`
