import hmac
import asyncio
import hashlib
import json
import logging
import os
import re
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from copy import deepcopy
from typing import List, Literal, Optional, Tuple, Union
from urllib.error import HTTPError, URLError
from urllib.request import Request as URLRequest, urlopen

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StrictBool, UUID4
from starlette.middleware.sessions import SessionMiddleware

import hie_connector
import local_state_store
import postgres_store

logger = logging.getLogger("screentocare")

AUTH_PUBLIC_PATHS = {
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/auth/logout",
    "/api/v1/patient-portal/lookup"
}


class ClinicianAuthorizationMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive=receive)
        if (
            request.method == "OPTIONS"
            or not request.url.path.startswith("/api/v1/")
            or request.url.path in AUTH_PUBLIC_PATHS
            or getattr(request.app.state, "auth_test_bypass", False)
        ):
            await self.app(scope, receive, send)
            return

        user_id = request.session.get("user_id")
        user = find_clinician_by_id(user_id) if user_id else None
        if not user:
            response = JSONResponse(
                {"detail": "Sign in with a clinician account to continue."},
                status_code=401
            )
            await response(scope, receive, send)
            return

        request.state.authenticated_user = user
        await self.app(scope, receive, send)


def _restore_database_state(persisted):
    DB_PATIENTS.update(persisted["patients"])
    DB_CASES.update(persisted["cases"])
    DB_REFERRALS.update(persisted["referrals"])
    DB_CLOSURES.update(persisted["closures"])
    DB_SIGNOFFS.update(persisted["signoffs"])
    DB_AUDIT_LOG.extend(persisted["audit"])
    for case in DB_CASES.values():
        patient = DB_PATIENTS[case["patient_id"]]
        patient["screening_type"] = case["screening_type"]
        patient["facility"] = case["facility"]
        if not case.get("triage_analysis"):
            case["triage_analysis"] = build_demo_triage_analysis(
                case["screening_result_value"],
                case["risk_level"],
                "Restored from the PostgreSQL case record.",
                max(0, int((case["sla_due_at"] - utc_now()).total_seconds() // 3600))
            )
        if not case["triage_analysis"].get("draft_patient_sms"):
            case["triage_analysis"]["draft_patient_sms"] = build_draft_patient_sms(
                case["screening_type"],
                case["facility"],
                case["sla_due_at"]
            )
        if not case.get("service_request"):
            build_fhir_payload(case)
        DB_COMMS_LOG.extend(case.get("communications", []))
    for referral in DB_REFERRALS.values():
        case = DB_CASES[referral["case_id"]]
        case["service_request_id"] = referral["service_request_id"]
        case["service_request"] = deepcopy(referral["service_request"])
        if not case.get("fhir_bundle"):
            build_fhir_payload(case)
        case["service_request"]["status"] = referral["service_request"]["status"]
        case["fhir_bundle"]["entry"][0]["resource"] = deepcopy(case["service_request"])
    if postgres_store.is_configured():
        for case in DB_CASES.values():
            _persist_case_snapshot(case)


def _restore_live_api_snapshot(snapshot):
    audit_events = list(reversed(snapshot["audit"]))
    consent_by_case = {
        event["case_id"]: event.get("details", {}).get("consent_signed_at")
        for event in audit_events
        if event.get("action_type") == "RESULT_INGESTED_AND_SLA_INITIALIZED"
    }
    state = {
        "patients": {},
        "cases": {},
        "referrals": {},
        "closures": {},
        "signoffs": {},
        "audit": audit_events
    }

    for saved_case in snapshot["cases"]:
        case_id = uuid.UUID(saved_case["case_id"])
        patient_id = uuid.UUID(saved_case["patient_id"])
        signoffs = saved_case.get("signoffs") or {}
        communications = saved_case.get("communications") or []
        patient = {
            "patient_id": patient_id,
            "national_id": saved_case.get("national_id"),
            "name": saved_case.get("patient_name"),
            "date_of_birth": None,
            "gender": None,
            "phone": None,
            "preferred_channel": communications[0]["channel"] if communications else "sms",
            "mpi_hash": None,
            "consent_signed": True,
            "consent_signed_at": consent_by_case.get(saved_case["case_id"]),
            "screening_type": saved_case.get("screening_type"),
            "facility": saved_case.get("facility")
        }
        state["patients"][patient_id] = patient

        case = {
            key: value
            for key, value in saved_case.items()
            if key not in {
                "patient_name", "national_id", "status", "sla_remaining", "signoffs"
            }
        }
        case["case_id"] = case_id
        case["patient_id"] = patient_id
        case["current_owner_id"] = uuid.UUID(case["current_owner_id"])
        if case.get("service_request_id"):
            case["service_request_id"] = uuid.UUID(case["service_request_id"])
        for key in ("sla_due_at", "sla_alerted_at", "created_at", "updated_at"):
            if case.get(key):
                case[key] = datetime.fromisoformat(case[key])
        if case.get("discharge_summary") and case["discharge_summary"].get("uploaded_at"):
            case["discharge_summary"]["uploaded_at"] = datetime.fromisoformat(
                case["discharge_summary"]["uploaded_at"]
            )
        if case.get("sla_escalation_alert") and case["sla_escalation_alert"].get("timestamp"):
            case["sla_escalation_alert"]["timestamp"] = datetime.fromisoformat(
                case["sla_escalation_alert"]["timestamp"]
            )
        for communication in case.get("communications", []):
            communication["timestamp"] = datetime.fromisoformat(communication["timestamp"])
        state["cases"][case_id] = case
        state["signoffs"][case_id] = {
            role: {
                **record,
                "signed_at": datetime.fromisoformat(record["signed_at"]),
                "signature": None,
                "session_token": None
            }
            for role, record in signoffs.items()
        }

    for saved_referral in snapshot["referrals"]:
        referral_id = uuid.UUID(saved_referral["service_request_id"])
        case_id = uuid.UUID(saved_referral["case_id"])
        state["referrals"][referral_id] = {
            "service_request_id": referral_id,
            "case_id": case_id,
            "referral_status": saved_referral["referral_status"],
            "service_request": saved_referral["service_request"],
            "created_at": datetime.fromisoformat(saved_referral["created_at"])
        }

    for event in audit_events:
        if event.get("action_type") != "DUAL_KEY_CASE_CLOSURE":
            continue
        case_id = uuid.UUID(event["case_id"])
        case = state["cases"].get(case_id)
        if case:
            state["closures"][case_id] = {
                "closure_id": event.get("details", {}).get("closure_id"),
                "case_id": case_id,
                "primary_clinician": event.get("details", {}).get("primary_clinician"),
                "secondary_clinician": event.get("details", {}).get("secondary_clinician"),
                "clinical_evidence_doc_id": event.get("details", {}).get("clinical_evidence_doc_id"),
                "primary_signature": None,
                "secondary_signature": None,
                "closed_at": datetime.fromisoformat(event["timestamp"])
            }

    _restore_database_state(state)


@asynccontextmanager
async def lifespan(_app):
    if postgres_store.is_configured():
        try:
            await asyncio.to_thread(postgres_store.activate_legacy_clinician_accounts)
            persisted = await asyncio.to_thread(postgres_store.load_state)
            _restore_database_state(persisted)
        except Exception:
            logger.exception("Could not restore ScreenToCare state from PostgreSQL.")
            raise
    else:
        state_path = os.getenv("CAREBRIDGE_LOCAL_STATE_FILE")
        if state_path:
            saved_state = local_state_store.load_state(state_path)
            if saved_state:
                try:
                    if saved_state.get("format") == "carebridge-live-api-snapshot-v1":
                        _restore_live_api_snapshot(saved_state)
                    else:
                        _restore_database_state(saved_state)
                        for user in saved_state.get("clinician_users", []):
                            cache_clinician_user(user)
                    _save_local_state()
                except Exception:
                    logger.exception("Could not restore ScreenToCare local state.")
                    raise

    seed_demo_clinician_account()
    seed_configured_demo_clinician()
    _save_local_state()
    scheduler_task = asyncio.create_task(sla_scheduler_loop())
    try:
        yield
    finally:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass

app = FastAPI(
    title="ScreenToCare Clinical Orchestration Engine",
    version="1.0.0",
    description="Clinical orchestration prototype with offline-first synchronization.",
    lifespan=lifespan
)

app.state.auth_test_bypass = False
app.add_middleware(ClinicianAuthorizationMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("CAREBRIDGE_SESSION_SECRET") or secrets.token_urlsafe(32),
    same_site="lax",
    https_only=os.getenv("CAREBRIDGE_COOKIE_SECURE", "false").casefold() == "true",
    max_age=28800
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        (
            origin.strip()
            if "://" in origin.strip()
            else f"https://{origin.strip()}"
        )
        for origin in os.getenv(
            "CAREBRIDGE_CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173"
        ).split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ScreeningIngestPayload(BaseModel):
    patient_national_id: str
    patient_name: str
    date_of_birth: date
    gender: str
    phone_number: str
    consent_signed: StrictBool
    preferred_channel: str = "whatsapp"
    screening_type: str
    screening_result_value: str
    risk_level: str
    facility: str = "Mobile Outreach"
    queue_id: Optional[str] = None
    actor_name: str = "Mobile Screening Worker"

class ScreeningTriagePayload(BaseModel):
    patient_national_id: str
    patient_name: str
    date_of_birth: date
    gender: str
    phone_number: str
    consent_signed: StrictBool
    preferred_channel: str = "whatsapp"
    screening_type: str = "Community Screening"
    facility: str = "Mobile Outreach"
    raw_screening_notes: str = Field(min_length=3)
    queue_id: Optional[str] = None
    actor_name: str = "Mobile Screening Worker"

class TriagePreviewPayload(BaseModel):
    screening_type: str = Field(default="Community Screening", min_length=1, max_length=150)
    facility: str = Field(default="Mobile Outreach", min_length=1, max_length=150)
    raw_screening_notes: str = Field(min_length=3, max_length=5000)

class OfflineSyncBatch(BaseModel):
    device_id: str
    synced_records: List[Union[ScreeningIngestPayload, ScreeningTriagePayload]]

class ClosurePayload(BaseModel):
    clinical_evidence_doc_id: str = Field(min_length=1)

class ClinicianRegistrationPayload(BaseModel):
    full_name: str = Field(min_length=2, max_length=150)
    email: str = Field(min_length=3, max_length=254)
    clinical_role: str = Field(min_length=2, max_length=100)
    password: str = Field(min_length=12, max_length=256)

class ClinicianLoginPayload(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)

class ClinicianSignoffPayload(BaseModel):
    session_token: str = Field(min_length=1)
    signature: str = Field(min_length=1)

class ActorPayload(BaseModel):
    actor_name: str = Field(default="ScreenToCare Clinical Team", min_length=1)

class PatientPortalLookupPayload(BaseModel):
    identifier: str = Field(min_length=3, max_length=100)
    date_of_birth: date

class EscalationPayload(ActorPayload):
    alert_reason: str = Field(
        default="Urgent DHMT escalation requested for referral SLA risk.",
        min_length=1
    )

class DischargeSummaryPayload(ActorPayload):
    document_id: str = Field(min_length=1)
    clinical_outcome_note: str = Field(min_length=1)

class CaseResponse(BaseModel):
    case_id: UUID4
    patient_id: UUID4
    risk_level: str
    case_status: str
    sla_due_at: datetime
    is_overdue: bool
    created_at: datetime

DB_CASES = {}
DB_PATIENTS = {}
DB_AUDIT_LOG = []
DB_CLOSURES = {}
DB_REFERRALS = {}
DB_SYNCED_QUEUE_IDS = set()
DB_CLINICIAN_SESSIONS = {}
DB_CLINICIAN_USERS = {}
DB_CLINICIAN_EMAIL_INDEX = {}
DB_SIGNOFFS = {}
DB_COMMS_LOG = []
DB_DHMT_WEBHOOK_LOG = []

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_email(email):
    return email.strip().casefold()


def is_valid_email(email):
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email))


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 600_000)
    return f"pbkdf2_sha256$600000${salt.hex()}${digest.hex()}"


def verify_password(password, encoded_hash):
    try:
        algorithm, rounds, salt_hex, digest_hex = encoded_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(rounds)
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def cache_clinician_user(user):
    user["user_id"] = str(user["user_id"])
    DB_CLINICIAN_USERS[user["user_id"]] = user
    DB_CLINICIAN_EMAIL_INDEX[user["email"]] = user["user_id"]
    return user


def find_clinician_by_id(user_id):
    if not user_id:
        return None
    if postgres_store.is_configured():
        user = postgres_store.get_clinician_user_by_id(user_id)
        return cache_clinician_user(user) if user else None
    return DB_CLINICIAN_USERS.get(str(user_id))


def find_clinician_by_email(email):
    normalized_email = normalize_email(email)
    if postgres_store.is_configured():
        user = postgres_store.get_clinician_user_by_email(normalized_email)
        return cache_clinician_user(user) if user else None
    user_id = DB_CLINICIAN_EMAIL_INDEX.get(normalized_email)
    return DB_CLINICIAN_USERS.get(user_id) if user_id else None


def create_clinician_user(user):
    user = {**user, "email": normalize_email(user["email"])}
    if postgres_store.is_configured():
        created = postgres_store.create_clinician_user(user)
        return cache_clinician_user(created) if created else None
    if user["email"] in DB_CLINICIAN_EMAIL_INDEX:
        return None
    created = cache_clinician_user(user)
    _save_local_state()
    return created


def serialize_clinician_user(user):
    return {
        "user_id": str(user["user_id"]),
        "full_name": user["full_name"],
        "email": user["email"],
        "clinical_role": user["clinical_role"],
        "created_at": user["created_at"]
    }


def require_current_clinician(request):
    user = getattr(request.state, "authenticated_user", None)
    if user:
        return user
    if getattr(app.state, "auth_test_bypass", False):
        return {
            "user_id": "test-clinician",
            "full_name": "Test Clinician",
            "clinical_role": "Test role"
        }
    raise HTTPException(status_code=401, detail="A clinician account is required.")


def current_actor(request, fallback_name=None):
    user = require_current_clinician(request)
    if user["user_id"] == "test-clinician" and fallback_name:
        return fallback_name, fallback_name
    return user["user_id"], user["full_name"]


def seed_demo_clinician_account():
    for name, email in (
        ("Dr. Tlhagiso", "dr.tlhagiso@health.gov.bw"),
        ("Dr. Kabelo", "dr.kabelo@health.gov.bw")
    ):
        seed_clinician_account({
            "user_id": str(uuid.uuid4()),
            "full_name": name,
            "email": email,
            "clinical_role": "Clinician",
            "password_hash": hash_password("2026"),
            "created_at": utc_now()
        })


def seed_clinician_account(user):
    user = {**user, "email": normalize_email(user["email"])}
    if postgres_store.is_configured():
        stored_user = postgres_store.upsert_demo_clinician_user(user)
        return cache_clinician_user(stored_user)
    existing_id = DB_CLINICIAN_EMAIL_INDEX.get(user["email"])
    if existing_id:
        DB_CLINICIAN_USERS[existing_id].update({
            key: user[key]
            for key in ("full_name", "clinical_role", "password_hash")
        })
        return DB_CLINICIAN_USERS[existing_id]
    return cache_clinician_user(user)


def seed_configured_demo_clinician():
    name = os.getenv("CAREBRIDGE_DEMO_CLINICIAN_NAME", "").strip()
    email = normalize_email(os.getenv("CAREBRIDGE_DEMO_CLINICIAN_EMAIL", ""))
    password = os.getenv("CAREBRIDGE_DEMO_CLINICIAN_PASSWORD", "")
    if not name and not email and not password:
        return
    if not name or not is_valid_email(email) or len(password) < 12:
        raise RuntimeError(
            "Set a demo clinician name, valid email, and password of at least 12 characters."
        )
    seed_clinician_account({
        "user_id": str(uuid.uuid4()),
        "full_name": name,
        "email": email,
        "clinical_role": "Clinician",
        "password_hash": hash_password(password),
        "created_at": utc_now()
    })
    _save_local_state()


def patient_mpi_hash(national_id: str, date_of_birth: date, phone_number: str) -> str:
    phone_digits = re.sub(r"[^0-9]", "", phone_number)
    if phone_digits.startswith("00"):
        phone_digits = phone_digits[2:]
    if phone_digits.startswith("0") and len(phone_digits) == 9:
        phone_digits = phone_digits[1:]
    if len(phone_digits) == 8:
        phone_digits = "267" + phone_digits
    components = (
        re.sub(r"[^a-z0-9]", "", national_id.casefold()),
        date_of_birth.isoformat(),
        phone_digits
    )
    if not all(components):
        raise HTTPException(
            status_code=422,
            detail="Omang ID, date of birth, and phone number are required for MPI matching."
        )
    return hashlib.sha256("|".join(components).encode("utf-8")).hexdigest()


def _save_local_state():
    state_path = os.getenv("CAREBRIDGE_LOCAL_STATE_FILE")
    if not state_path or postgres_store.is_configured():
        return
    local_state_store.save_state(state_path, {
        "patients": DB_PATIENTS,
        "cases": DB_CASES,
        "referrals": DB_REFERRALS,
        "closures": DB_CLOSURES,
        "signoffs": DB_SIGNOFFS,
        "audit": DB_AUDIT_LOG,
        "clinician_users": list(DB_CLINICIAN_USERS.values()),
        "synced_queue_ids": list(DB_SYNCED_QUEUE_IDS),
        "communications": DB_COMMS_LOG,
        "dhmt_webhook_log": DB_DHMT_WEBHOOK_LOG
    })


def _persist_case_snapshot(case):
    if postgres_store.is_configured():
        postgres_store.save_case(
            case,
            DB_SIGNOFFS.get(case["case_id"], {})
        )
    else:
        _save_local_state()


def _persist_referral(referral, case):
    if postgres_store.is_configured():
        postgres_store.save_referral(referral, case)
    else:
        _save_local_state()


def calculate_sla_deadline(risk_level: str) -> datetime:
    sla_hours_map = {
        "CRITICAL_RED_FLAG": 12,
        "HIGH": 24,
        "MODERATE": 48,
        "LOW": 72
    }
    hours = sla_hours_map.get(risk_level, 48)
    return utc_now() + timedelta(hours=hours)

def append_audit_event(
    case_id,
    action_type: str,
    new_state: str,
    actor_id=None,
    actor_name=None,
    details=None,
    fhir_resource_reference=None
):
    timestamp = utc_now()
    event_id = uuid.uuid4()
    actor_name = str(actor_name or actor_id or "ScreenToCare System").strip() or "ScreenToCare System"
    event_details = deepcopy(details or {})
    case = DB_CASES.get(case_id, {})
    service_request_id = case.get("service_request_id")
    fhir_resource_reference = fhir_resource_reference or (
        f"ServiceRequest/{service_request_id}"
        if service_request_id
        else f"Patient/{case.get('patient_id')}" if case.get("patient_id") else None
    )
    fhir_resource_reference = fhir_resource_reference or f"Case/{case_id}"
    event_data = {
        "event_id": str(event_id),
        "case_id": str(case_id),
        "action_type": action_type,
        "new_state": new_state,
        "actor_name": actor_name,
        "fhir_resource_reference": fhir_resource_reference,
        "details": event_details,
        "timestamp": timestamp.isoformat(),
    }
    if postgres_store.is_configured():
        previous_hash, verification_hash = postgres_store.insert_audit_event({
            **event_data,
            "event_id": event_id,
            "case_id": case_id,
            "actor_id": actor_id,
            "details": event_details,
            "timestamp": timestamp
        })
    else:
        previous_hash = DB_AUDIT_LOG[-1]["verification_hash"] if DB_AUDIT_LOG else None
        event_data["previous_hash"] = previous_hash
        verification_hash = hashlib.sha256(
            json.dumps(event_data, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()
    event = {
        "event_id": event_id,
        "case_id": case_id,
        "action_type": action_type,
        "new_state": new_state,
        "actor_id": actor_id,
        "actor_name": actor_name,
        "fhir_resource_reference": fhir_resource_reference,
        "details": event_details,
        "timestamp": timestamp,
        "previous_hash": previous_hash,
        "verification_hash": verification_hash
    }
    DB_AUDIT_LOG.append(event)
    if not postgres_store.is_configured():
        _save_local_state()
    return event

def classify_demo_triage(raw_notes: str) -> Tuple[str, str, int]:
    """Apply transparent keyword rules for this demo; this is not clinical decision support."""
    notes = raw_notes.casefold()
    if any(term in notes for term in (
        "critical red flag",
        "red flag",
        "positive genexpert",
        "difficulty breathing",
        "unconscious",
        "severe chest pain"
    )):
        return "CRITICAL_RED_FLAG", "Matched a configured demo critical-keyword rule.", 12
    if any(term in notes for term in (
        "high risk",
        "stage 2 hypertension",
        "urgent review"
    )):
        return "HIGH", "Matched a configured demo high-risk keyword rule.", 24
    return "MODERATE", "No configured critical or high-risk phrase matched; demo default is moderate.", 48

def build_demo_triage_analysis(raw_notes: str, risk_level: str, reason: str, sla_hours: int):
    notes = raw_notes.casefold()
    cue_mappings = [
        {
            "terms": ("stage 2 hypertension", "hypertension"),
            "display": "Hypertension screening cue (not a confirmed diagnosis)",
            "icd10": {"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "I10", "display": "Essential (primary) hypertension"},
            "snomed": {"system": "http://snomed.info/sct", "code": "38341003", "display": "Hypertensive disorder, systemic arterial"}
        },
        {
            "terms": ("severe chest pain", "chest pain"),
            "display": "Chest pain screening cue (not a confirmed diagnosis)",
            "icd10": {"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "R07.9", "display": "Chest pain, unspecified"},
            "snomed": {"system": "http://snomed.info/sct", "code": "29857009", "display": "Chest pain"}
        },
        {
            "terms": ("difficulty breathing", "shortness of breath"),
            "display": "Breathing difficulty screening cue (not a confirmed diagnosis)",
            "icd10": {"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "R06.00", "display": "Dyspnea, unspecified"},
            "snomed": {"system": "http://snomed.info/sct", "code": "267036007", "display": "Dyspnea"}
        }
    ]
    coded_cues = []
    for mapping in cue_mappings:
        matched_term = next((term for term in mapping["terms"] if term in notes), None)
        if matched_term:
            coded_cues.append({
                "display": mapping["display"],
                "matched_demo_cue": matched_term,
                "coding": [mapping["icd10"], mapping["snomed"]]
            })

    risk_display = {
        "CRITICAL_RED_FLAG": "Critical red flag",
        "HIGH": "High risk",
        "MODERATE": "Moderate risk",
        "LOW": "Low risk"
    }.get(risk_level, "Unclassified risk")
    risk_tag = {
        "display": f"{risk_display} (demo triage category)",
        "coding": [{
            "system": "urn:carebridge:demo-risk-level",
            "code": risk_level,
            "display": risk_display
        }]
    }
    rationale_summary = reason
    if coded_cues:
        rationale_summary += " Matched screening cue(s): " + "; ".join(
            cue["matched_demo_cue"] for cue in coded_cues
        ) + "."
    rationale_summary += " This is a transparent keyword-based demo, not a diagnosis or clinical decision-support recommendation."
    return {
        "mode": "DEMO_RULE_BASED",
        "risk_level": risk_level,
        "reason": reason,
        "rationale_summary": rationale_summary,
        "sla_hours": sla_hours,
        "risk_tags": [risk_tag, *coded_cues]
    }

def build_fhir_payload(case):
    patient = DB_PATIENTS[case["patient_id"]]
    triage = case["triage_analysis"]
    service_request_id = case.get("service_request_id") or uuid.uuid4()
    authored_on = utc_now()
    service_request = {
        "resourceType": "ServiceRequest",
        "id": str(service_request_id),
        "meta": {
            "profile": ["http://hl7.org/fhir/StructureDefinition/ServiceRequest"]
        },
        "identifier": [{
            "system": "urn:carebridge:case",
            "value": str(case["case_id"])
        }],
        "status": "draft",
        "intent": "order",
        "category": [{"text": "Community screening referral"}],
        "priority": "stat" if case["risk_level"] == "CRITICAL_RED_FLAG" else (
            "urgent" if case["risk_level"] == "HIGH" else "routine"
        ),
        "code": {"text": case["screening_type"]},
        "subject": {"reference": f"Patient/{case['patient_id']}"},
        "authoredOn": authored_on.isoformat(),
        "requester": {"display": case["actor_name"]},
        "reasonCode": [
            {"coding": tag["coding"], "text": tag["display"]}
            for tag in triage["risk_tags"]
        ],
        "note": [{"text": triage["rationale_summary"]}],
        "extension": [
            {
                "url": "https://carebridge.example/fhir/StructureDefinition/demo-risk-level",
                "valueCode": case["risk_level"]
            },
            {
                "url": "https://carebridge.example/fhir/StructureDefinition/sla-due-at",
                "valueDateTime": case["sla_due_at"].isoformat()
            }
        ]
    }
    bundle = {
        "resourceType": "Bundle",
        "id": str(uuid.uuid4()),
        "type": "collection",
        "timestamp": authored_on.isoformat(),
        "total": 1,
        "entry": [{
            "fullUrl": f"urn:uuid:{service_request_id}",
            "resource": deepcopy(service_request)
        }]
    }
    case["service_request_id"] = service_request_id
    case["service_request"] = service_request
    case["fhir_bundle"] = bundle
    return service_request, bundle

def serialized_signoffs(case_id):
    signoffs = DB_SIGNOFFS.get(case_id, {})
    return {
        role: {
            "clinician": record["clinician"],
            "role": record["role"],
            "signed_at": record["signed_at"]
        }
        for role, record in signoffs.items()
    }

def serialize_case(case):
    patient = DB_PATIENTS[case["patient_id"]]
    sla_remaining_seconds = (case["sla_due_at"] - utc_now()).total_seconds()
    remaining_hours = max(0, int((sla_remaining_seconds + 3599) // 3600))
    return {
        **case,
        "patient_name": patient["name"],
        "national_id": patient["national_id"],
        "screening_type": case["screening_type"],
        "facility": case["facility"],
        "screening_result_value": case.get("screening_result_value"),
        "service_request_id": str(case["service_request_id"]) if case.get("service_request_id") else None,
        "service_request": deepcopy(case.get("service_request")),
        "fhir_bundle": deepcopy(case.get("fhir_bundle")),
        "triage_analysis": deepcopy(case.get("triage_analysis")),
        "signoffs": serialized_signoffs(case["case_id"]),
        "discharge_summary": deepcopy(case.get("discharge_summary")),
        "sla_escalation_alert": deepcopy(case.get("sla_escalation_alert")),
        "status": case["case_status"],
        "is_overdue": sla_remaining_seconds < 0 and case["case_status"] != "CLOSED",
        "sla_remaining": "DONE" if case["case_status"] == "CLOSED" else f"{remaining_hours}h"
    }

def build_draft_patient_sms(screening_type, facility, sla_due_at):
    due_at = sla_due_at.astimezone(timezone.utc).strftime("%d %b %Y %H:%M UTC")
    return {
        "status": "DRAFT",
        "channel": "sms",
        "message": (
            f"ScreenToCare: Your {screening_type} screening has been received. "
            f"Please contact {facility} for next steps by {due_at}. "
            "This is a draft; no message has been sent."
        )
    }

def build_patient_portal_view(case):
    patient = DB_PATIENTS[case["patient_id"]]
    status_text = {
        "RESULT_INGESTED": "Screening received",
        "QUEUED_OFFLINE": "Screening waiting to sync",
        "REFERRAL_DISPATCHED": "Referral sent",
        "PATIENT_NOTIFIED": "Referral sent",
        "ARRIVED_AT_FACILITY": "Arrival recorded",
        "TREATMENT_COMPLETED": "Treatment recorded",
        "CLOSED": "Care loop completed"
    }.get(case["case_status"], "Screening in progress")
    urgency_text = {
        "CRITICAL_RED_FLAG": "Urgent — please contact your care team promptly",
        "HIGH": "Prompt follow-up recommended",
        "MODERATE": "Follow-up recommended",
        "LOW": "Routine follow-up"
    }.get(case["risk_level"], "Your care team will advise you")
    next_steps = {
        "RESULT_INGESTED": [
            "Your screening has been received. The care team is reviewing it.",
            "Keep your phone available for a follow-up message or call."
        ],
        "QUEUED_OFFLINE": [
            "Your screening is waiting to sync with the care team.",
            "If you need help now, contact the clinic where you were screened."
        ],
        "REFERRAL_DISPATCHED": [
            "A referral has been sent. Contact the clinic below to confirm when to attend.",
            "Bring any relevant health documents and share your tracking code."
        ],
        "PATIENT_NOTIFIED": [
            "A referral has been sent. Contact the clinic below to confirm when to attend.",
            "Bring any relevant health documents and share your tracking code."
        ],
        "ARRIVED_AT_FACILITY": [
            "Your arrival has been recorded. Follow the care team's instructions at the facility."
        ],
        "TREATMENT_COMPLETED": [
            "Treatment has been recorded. Your care team is confirming the follow-up outcome."
        ],
        "CLOSED": [
            "Your care loop has been completed. Continue to follow the instructions from your provider."
        ]
    }.get(case["case_status"], ["Contact the clinic where you were screened for your next steps."])
    if case["risk_level"] == "CRITICAL_RED_FLAG" and case["case_status"] != "CLOSED":
        next_steps.insert(
            0,
            "Please contact your care team promptly. If you feel seriously unwell, seek urgent in-person help."
        )

    return {
        "patient_first_name": patient["name"].split()[0],
        "tracking_code": str(case["case_id"]),
        "status": case["case_status"],
        "status_text": status_text,
        "urgency_level": case["risk_level"],
        "urgency_text": urgency_text,
        "screening_type": case["screening_type"],
        "facility": case["facility"],
        "created_at": case["created_at"],
        "sla_due_at": case["sla_due_at"],
        "appointment_details": {
            "facility": case["facility"],
            "scheduled_at": None,
            "follow_up_by": case["sla_due_at"],
            "message": (
                "No appointment time is recorded yet. Contact this clinic to confirm "
                "when to attend."
            )
        },
        "next_steps": next_steps
    }

def create_screening_case(payload: ScreeningIngestPayload, triage_analysis=None, actor_id=None):
    if not payload.consent_signed:
        raise HTTPException(
            status_code=400,
            detail="Signed POPIA / Data Protection Act consent is required before intake."
        )

    case_id = uuid.uuid4()
    mpi_hash = patient_mpi_hash(
        payload.patient_national_id,
        payload.date_of_birth,
        payload.phone_number
    )
    patient_id = next(
        (
            existing_id for existing_id, patient in DB_PATIENTS.items()
            if patient.get("mpi_hash") == mpi_hash
        ),
        None
    )
    if patient_id is None:
        patient_id = uuid.uuid4()
    consent_signed_at = utc_now()
    patient = DB_PATIENTS.get(patient_id, {"patient_id": patient_id})
    patient.update({
        "national_id": payload.patient_national_id,
        "mpi_hash": mpi_hash,
        "name": payload.patient_name,
        "date_of_birth": payload.date_of_birth.isoformat(),
        "gender": payload.gender,
        "phone": payload.phone_number,
        "preferred_channel": payload.preferred_channel,
        "screening_type": payload.screening_type,
        "facility": payload.facility,
        "consent_signed": payload.consent_signed,
        "consent_signed_at": consent_signed_at
    })
    if postgres_store.is_configured():
        try:
            persisted_patient_id = postgres_store.upsert_patient(patient)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if persisted_patient_id != patient_id:
            DB_PATIENTS.pop(patient_id, None)
            patient_id = persisted_patient_id
            patient["patient_id"] = patient_id
    DB_PATIENTS[patient_id] = patient
    
    sla_due = calculate_sla_deadline(payload.risk_level)
    if triage_analysis is None:
        sla_hours = {
            "CRITICAL_RED_FLAG": 12,
            "HIGH": 24,
            "MODERATE": 48,
            "LOW": 72
        }.get(payload.risk_level, 48)
        triage_analysis = build_demo_triage_analysis(
            payload.screening_result_value,
            payload.risk_level,
            "Risk level supplied with the screening record; no automated triage was run.",
            sla_hours
        )
    
    new_case = {
        "case_id": case_id,
        "patient_id": patient_id,
        "current_owner_id": uuid.uuid4(),
        "risk_level": payload.risk_level,
        "case_status": "RESULT_INGESTED",
        "screening_type": payload.screening_type,
        "facility": payload.facility,
        "screening_result_value": payload.screening_result_value,
        "actor_name": payload.actor_name,
        "triage_analysis": triage_analysis,
        "service_request_id": None,
        "service_request": None,
        "fhir_bundle": None,
        "communications": [],
        "discharge_summary": None,
        "sla_escalation_alert": None,
        "sla_due_at": sla_due,
        "sla_alerted_at": None,
        "is_overdue": False,
        "created_at": utc_now(),
        "updated_at": utc_now()
    }
    triage_analysis["draft_patient_sms"] = build_draft_patient_sms(
        new_case["screening_type"],
        new_case["facility"],
        new_case["sla_due_at"]
    )
    
    DB_CASES[case_id] = new_case
    build_fhir_payload(new_case)
    _persist_case_snapshot(new_case)
    
    append_audit_event(
        case_id,
        "RESULT_INGESTED_AND_SLA_INITIALIZED",
        "RESULT_INGESTED",
        actor_id=actor_id or payload.actor_name,
        actor_name=payload.actor_name,
        details={
            "risk_level": payload.risk_level,
            "consent_signed": payload.consent_signed,
            "consent_signed_at": DB_PATIENTS[patient_id]["consent_signed_at"].isoformat()
        },
        fhir_resource_reference=f"ServiceRequest/{new_case['service_request_id']}"
    )
    
    return new_case

@app.post("/api/v1/screening/ingest", response_model=CaseResponse, status_code=status.HTTP_201_CREATED)
def ingest_screening_record(payload: ScreeningIngestPayload, request: Request):
    actor_id, actor_name = current_actor(request, payload.actor_name)
    return create_screening_case(
        payload.model_copy(update={"actor_name": actor_name}),
        actor_id=actor_id
    )

@app.get("/api/v1/cases")
def list_cases():
    return [serialize_case(case) for case in sorted(
        DB_CASES.values(),
        key=lambda item: item["created_at"],
        reverse=True
    )]

@app.get("/api/v1/cases/{case_id}")
def get_case(case_id: UUID4, request: Request):
    case = DB_CASES.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found.")
    actor_id, actor_name = current_actor(request)
    append_audit_event(
        case_id,
        "CASE_RECORD_OPENED",
        case["case_status"],
        actor_id=actor_id,
        actor_name=actor_name,
        details={"view": "case_record"},
        fhir_resource_reference=f"Case/{case_id}"
    )
    return serialize_case(case)

@app.post("/api/v1/auth/register", status_code=status.HTTP_201_CREATED)
def register_clinician(payload: ClinicianRegistrationPayload):
    full_name = payload.full_name.strip()
    email = normalize_email(payload.email)
    clinical_role = payload.clinical_role.strip()
    if not full_name or not clinical_role or not is_valid_email(email):
        raise HTTPException(status_code=422, detail="Enter a valid name, email, and clinical role.")
    if find_clinician_by_email(email):
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    user = create_clinician_user({
        "user_id": str(uuid.uuid4()),
        "full_name": full_name,
        "email": email,
        "clinical_role": clinical_role,
        "password_hash": hash_password(payload.password),
        "created_at": utc_now()
    })
    if not user:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    return {
        "status": "REGISTERED",
        "message": "Registration successful. You can sign in now."
    }

@app.post("/api/v1/auth/login")
def login_clinician(payload: ClinicianLoginPayload, request: Request):
    email = normalize_email(payload.email)
    user = find_clinician_by_email(email)
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    previous_token = request.session.get("clinician_session_token")
    if previous_token:
        DB_CLINICIAN_SESSIONS.pop(previous_token, None)
    request.session.clear()
    request.session["user_id"] = user["user_id"]
    session_token = secrets.token_urlsafe(32)
    request.session["clinician_session_token"] = session_token
    DB_CLINICIAN_SESSIONS[session_token] = {
        "identity_id": user["user_id"],
        "clinician": user["full_name"],
        "role": user["clinical_role"]
    }
    return {
        **serialize_clinician_user(user),
        "session_token": session_token
    }

@app.get("/api/v1/auth/me")
def get_current_clinician(request: Request):
    user = require_current_clinician(request)
    return {
        **serialize_clinician_user(user),
        "session_token": request.session.get("clinician_session_token")
    }

@app.post("/api/v1/auth/logout")
def logout_clinician(request: Request):
    session_token = request.session.get("clinician_session_token")
    if session_token:
        DB_CLINICIAN_SESSIONS.pop(session_token, None)
    request.session.clear()
    return {"status": "SIGNED_OUT"}

@app.post("/api/v1/clinicians/session")
async def create_clinician_session(request: Request):
    user = require_current_clinician(request)
    previous_token = request.session.get("clinician_session_token")
    if previous_token and not getattr(app.state, "auth_test_bypass", False):
        DB_CLINICIAN_SESSIONS.pop(previous_token, None)
    if getattr(app.state, "auth_test_bypass", False):
        test_identities = {
            "triage_lead": ("Dr. T. Tlhagiso", "Clinical Triage Lead"),
            "oncology_specialist": ("Dr. K. Moyo", "Oncology Specialist")
        }
        payload = await request.json()
        identity = test_identities.get(payload.get("clinician_id"))
        if identity:
            user = {
                "user_id": payload["clinician_id"],
                "full_name": identity[0],
                "clinical_role": identity[1]
            }
    session_token = secrets.token_urlsafe(32)
    request.session["clinician_session_token"] = session_token
    DB_CLINICIAN_SESSIONS[session_token] = {
        "identity_id": user["user_id"],
        "clinician": user["full_name"],
        "role": user["clinical_role"]
    }
    return {
        "session_token": session_token,
        "clinician_id": user["user_id"],
        "clinician": user["full_name"],
        "role": user["clinical_role"]
    }

@app.post("/api/v1/screening/triage", status_code=status.HTTP_201_CREATED)
def triage_screening_record(payload: ScreeningTriagePayload, request: Request):
    actor_id, actor_name = current_actor(request, payload.actor_name)
    risk_level, reason, sla_hours = classify_demo_triage(payload.raw_screening_notes)
    triage_analysis = build_demo_triage_analysis(
        payload.raw_screening_notes,
        risk_level,
        reason,
        sla_hours
    )
    ingested_case = create_screening_case(ScreeningIngestPayload(
        patient_national_id=payload.patient_national_id,
        patient_name=payload.patient_name,
        date_of_birth=payload.date_of_birth,
        gender=payload.gender,
        phone_number=payload.phone_number,
        consent_signed=payload.consent_signed,
        preferred_channel=payload.preferred_channel,
        screening_type=payload.screening_type,
        screening_result_value=payload.raw_screening_notes,
        risk_level=risk_level,
        facility=payload.facility,
        actor_name=actor_name
    ), triage_analysis, actor_id)
    case_id = ingested_case["case_id"]
    append_audit_event(
        case_id,
        "DEMO_TRIAGE_COMPLETED",
        "RESULT_INGESTED",
        actor_id=actor_id,
        actor_name=actor_name,
        details=triage_analysis,
        fhir_resource_reference=f"ServiceRequest/{ingested_case['service_request_id']}"
    )
    return {
        "case": serialize_case(DB_CASES[case_id]),
        "triage": triage_analysis,
        "draft_patient_sms": deepcopy(triage_analysis["draft_patient_sms"]),
        "service_request": deepcopy(ingested_case["service_request"]),
        "fhir_bundle": deepcopy(ingested_case["fhir_bundle"])
    }

@app.post("/api/v1/screening/triage-preview")
def preview_screening_triage(payload: TriagePreviewPayload):
    risk_level, reason, sla_hours = classify_demo_triage(payload.raw_screening_notes)
    triage_analysis = build_demo_triage_analysis(
        payload.raw_screening_notes,
        risk_level,
        reason,
        sla_hours
    )
    sla_due_at = utc_now() + timedelta(hours=sla_hours)
    triage_analysis["draft_patient_sms"] = build_draft_patient_sms(
        payload.screening_type,
        payload.facility,
        sla_due_at
    )
    return {
        "triage": triage_analysis,
        "draft_patient_sms": deepcopy(triage_analysis["draft_patient_sms"]),
        "sla_due_at": sla_due_at
    }

@app.post("/api/v1/patient-portal/lookup")
def lookup_patient_portal(payload: PatientPortalLookupPayload):
    identifier = payload.identifier.strip()
    normalized_omang = re.sub(r"[^a-z0-9]", "", identifier.casefold())
    matched_cases = []
    for case in DB_CASES.values():
        patient = DB_PATIENTS[case["patient_id"]]
        is_tracking_code = str(case["case_id"]).casefold() == identifier.casefold()
        is_omang = (
            re.sub(r"[^a-z0-9]", "", patient["national_id"].casefold()) == normalized_omang
        )
        patient_dob = patient["date_of_birth"]
        if (is_tracking_code or is_omang) and str(patient_dob) == payload.date_of_birth.isoformat():
            matched_cases.append(case)

    if not matched_cases:
        raise HTTPException(
            status_code=404,
            detail="We couldn't find a matching screening record. Check your details or contact your clinic."
        )
    latest_case = max(matched_cases, key=lambda case: case["created_at"])
    return build_patient_portal_view(latest_case)

@app.get("/api/v1/metrics/impact")
def get_impact_metrics():
    persisted_cases = [
        case for case in DB_CASES.values()
        if case["case_status"] != "QUEUED_OFFLINE"
    ]
    active_cases = [
        case for case in persisted_cases if case["case_status"] != "CLOSED"
    ]
    breached_cases = [
        case for case in active_cases
        if case["sla_due_at"] < utc_now() or case.get("is_overdue", False)
    ]
    closed_cases = [
        case for case in persisted_cases if case["case_status"] == "CLOSED"
    ]
    turnaround_hours = []
    for case in closed_cases:
        closure = DB_CLOSURES.get(case["case_id"])
        if closure:
            elapsed = (closure["closed_at"] - case["created_at"]).total_seconds() / 3600
            turnaround_hours.append(max(0, elapsed))

    referral_count = len(DB_REFERRALS)
    completed_referrals = sum(
        referral["referral_status"] == "COMPLETED"
        for referral in DB_REFERRALS.values()
    )
    return {
        "generated_at": utc_now(),
        "average_turnaround_hours": (
            round(sum(turnaround_hours) / len(turnaround_hours), 1)
            if turnaround_hours else None
        ),
        "turnaround_sample_size": len(turnaround_hours),
        "active_sla_breach_percent": (
            round(len(breached_cases) / len(active_cases) * 100, 1)
            if active_cases else 0
        ),
        "active_sla_breached_cases": len(breached_cases),
        "active_sla_case_count": len(active_cases),
        "referral_completion_rate_percent": (
            round(completed_referrals / referral_count * 100, 1)
            if referral_count else 0
        ),
        "completed_referrals": completed_referrals,
        "total_referrals": referral_count,
        "closed_loop_conversion_percent": (
            round(len(closed_cases) / len(persisted_cases) * 100, 1)
            if persisted_cases else 0
        ),
        "closed_cases": len(closed_cases),
        "total_cases": len(persisted_cases)
    }

def create_service_request(case):
    if not case.get("service_request"):
        build_fhir_payload(case)
    service_request = case["service_request"]
    service_request["status"] = "active"
    case["fhir_bundle"]["entry"][0]["resource"] = deepcopy(service_request)
    service_request_id = case["service_request_id"]
    now = utc_now()
    referral = {
        "service_request_id": service_request_id,
        "case_id": case["case_id"],
        "referral_status": "PENDING",
        "service_request": service_request,
        "created_at": now
    }
    DB_REFERRALS[service_request_id] = referral
    case["service_request_id"] = service_request_id
    _persist_referral(referral, case)
    return referral

def create_patient_notifications(case, service_request_id):
    patient = DB_PATIENTS[case["patient_id"]]
    facility = case["facility"]
    sla_deadline = case["sla_due_at"].astimezone(timezone.utc).isoformat()
    timestamp = utc_now()
    messages = [
        {
            "language": "English",
            "message": (
                f"ScreenToCare: You have been referred to {facility}. Please attend as soon as possible. "
                f"Your follow-up target is {sla_deadline}."
            )
        },
        {
            "language": "Setswana",
            "message": (
                f"ScreenToCare: O rometswe kwa {facility}. Tsweetswee goroga kwa lefelong leno ka bonako. "
                f"Nako ya go go latela ke {sla_deadline}."
            )
        }
    ]
    notifications = [
        {
            "notification_id": str(uuid.uuid4()),
            "case_id": str(case["case_id"]),
            "service_request_id": str(service_request_id),
            "channel": patient["preferred_channel"],
            "phone_number": patient["phone"],
            "facility": facility,
            "sla_deadline": sla_deadline,
            "language": message["language"],
            "message": message["message"],
            "actor_name": "ScreenToCare Notification Service (simulation)",
            "timestamp": timestamp
        }
        for message in messages
    ]
    case["communications"].extend(notifications)
    DB_COMMS_LOG.extend(notifications)
    append_audit_event(
        case["case_id"],
        "BILINGUAL_PATIENT_NOTIFICATION_SIMULATED",
        case["case_status"],
        actor_id="ScreenToCare Notification Service (simulation)",
        details={
            "languages": ["English", "Setswana"],
            "channel": patient["preferred_channel"]
        },
        fhir_resource_reference=f"ServiceRequest/{service_request_id}"
    )
    return notifications

def dispatch_case(case, actor_id, actor_name):
    if case["case_status"] not in ("RESULT_INGESTED", "QUEUED_OFFLINE"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot dispatch a case in {case['case_status']} state."
        )
    referral = next(
        (item for item in DB_REFERRALS.values() if item["case_id"] == case["case_id"]),
        None
    )
    if referral is None:
        referral = create_service_request(case)
    elif referral["referral_status"] != "PENDING":
        raise HTTPException(status_code=409, detail="Referral has already been processed.")

    referral["referral_status"] = "DISPATCHED"
    case["case_status"] = "REFERRAL_DISPATCHED"
    case["updated_at"] = utc_now()
    _persist_referral(referral, case)
    _persist_case_snapshot(case)
    append_audit_event(
        case["case_id"],
        "FHIR_SERVICEREQUEST_DISPATCHED",
        "REFERRAL_DISPATCHED",
        actor_id=actor_id,
        actor_name=actor_name,
        details={"service_request_id": str(referral["service_request_id"])}
    )
    create_patient_notifications(case, referral["service_request_id"])
    _persist_case_snapshot(case)
    return referral

@app.get("/api/v1/referrals")
def list_referrals():
    referrals = []
    for referral in sorted(
        DB_REFERRALS.values(),
        key=lambda item: item["created_at"],
        reverse=True
    ):
        case = DB_CASES[referral["case_id"]]
        referrals.append({
            "service_request_id": str(referral["service_request_id"]),
            "case_id": str(referral["case_id"]),
            "patient_name": DB_PATIENTS[case["patient_id"]]["name"],
            "facility": case["facility"],
            "screening_type": case["screening_type"],
            "risk_level": case["risk_level"],
            "phone_number": DB_PATIENTS[case["patient_id"]]["phone"],
            "case_status": case["case_status"],
            "sla_escalation_alert": deepcopy(case.get("sla_escalation_alert")),
            "communication_log": deepcopy(case.get("communications", [])),
            "triage_analysis": deepcopy(case.get("triage_analysis")),
            "fhir_bundle": deepcopy(case.get("fhir_bundle")),
            "referral_status": referral["referral_status"],
            "service_request": referral["service_request"],
            "created_at": referral["created_at"]
        })
    return referrals

@app.post("/api/v1/cases/{case_id}/dispatch")
def dispatch_case_endpoint(case_id: UUID4, request: Request):
    case = DB_CASES.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found.")
    actor_id, actor_name = current_actor(request)
    referral = dispatch_case(case, actor_id, actor_name)
    return {
        "status": "SUCCESS",
        "case": serialize_case(case),
        "referral_status": referral["referral_status"],
        "service_request": deepcopy(referral["service_request"])
    }

@app.post("/api/v1/referrals/{service_request_id}/dispatch")
def dispatch_referral(service_request_id: UUID4, request: Request):
    referral = DB_REFERRALS.get(service_request_id)
    if referral is None:
        raise HTTPException(status_code=404, detail="Referral not found.")
    case = DB_CASES[referral["case_id"]]
    actor_id, actor_name = current_actor(request)
    dispatched_referral = dispatch_case(case, actor_id, actor_name)
    return {
        "status": "SUCCESS",
        "referral_status": dispatched_referral["referral_status"]
    }

@app.post("/api/v1/cases/{case_id}/arrival")
def check_in_patient(case_id: UUID4, request: Request):
    case = DB_CASES.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found.")
    if case["case_status"] not in ("REFERRAL_DISPATCHED", "PATIENT_NOTIFIED"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot check in a patient in {case['case_status']} state."
        )
    case["case_status"] = "ARRIVED_AT_FACILITY"
    case["updated_at"] = utc_now()
    _persist_case_snapshot(case)
    actor_id, actor_name = current_actor(request)
    append_audit_event(
        case_id,
        "PATIENT_ARRIVAL_CHECK_IN",
        "ARRIVED_AT_FACILITY",
        actor_id=actor_id,
        actor_name=actor_name,
        details={"facility": case["facility"]}
    )
    return {"status": "SUCCESS", "case": serialize_case(case)}

@app.post("/api/v1/cases/{case_id}/escalate")
def escalate_case(case_id: UUID4, payload: EscalationPayload, request: Request):
    case = DB_CASES.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found.")
    if case["case_status"] not in ("REFERRAL_DISPATCHED", "PATIENT_NOTIFIED"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot escalate a case in {case['case_status']} state."
        )
    timestamp = utc_now()
    actor_id, actor_name = current_actor(request)
    alert = {
        "message": payload.alert_reason.strip(),
        "actor_name": actor_name,
        "timestamp": timestamp
    }
    case["sla_escalation_alert"] = alert
    case["sla_alerted_at"] = timestamp
    case["updated_at"] = timestamp
    _persist_case_snapshot(case)
    append_audit_event(
        case_id,
        "URGENT_DHMT_SLA_ESCALATION",
        case["case_status"],
        actor_id=actor_id,
        actor_name=actor_name,
        details={"alert": payload.alert_reason.strip()}
    )
    return {"status": "SUCCESS", "alert": alert, "case": serialize_case(case)}

@app.post("/api/v1/cases/{case_id}/discharge-summary")
def upload_discharge_summary(case_id: UUID4, payload: DischargeSummaryPayload, request: Request):
    case = DB_CASES.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found.")
    if case["case_status"] != "ARRIVED_AT_FACILITY":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot upload a discharge summary in {case['case_status']} state."
        )
    document_id = payload.document_id.strip()
    outcome_note = payload.clinical_outcome_note.strip()
    if not document_id or not outcome_note:
        raise HTTPException(
            status_code=400,
            detail="A receiving hospital document ID and clinical outcome note are required."
        )
    discharge_resource_id = uuid.uuid4()
    timestamp = utc_now()
    actor_id, actor_name = current_actor(request)
    case["discharge_summary"] = {
        "document_id": document_id,
        "clinical_outcome_note": outcome_note,
        "resource_id": str(discharge_resource_id),
        "uploaded_at": timestamp,
        "uploaded_by": actor_name
    }
    case["case_status"] = "TREATMENT_COMPLETED"
    case["updated_at"] = timestamp
    _persist_case_snapshot(case)
    append_audit_event(
        case_id,
        "RECEIVING_HOSPITAL_DISCHARGE_SUMMARY_UPLOADED",
        "TREATMENT_COMPLETED",
        actor_id=actor_id,
        actor_name=actor_name,
        details={"document_id": document_id},
        fhir_resource_reference=f"DocumentReference/{discharge_resource_id}"
    )
    return {"status": "SUCCESS", "case": serialize_case(case)}

@app.get("/api/v1/audit")
def list_audit_events():
    return [deepcopy(event) for event in reversed(DB_AUDIT_LOG)]

@app.post("/api/v1/sync/queue", status_code=status.HTTP_200_OK)
def sync_offline_queue(batch: OfflineSyncBatch, request: Request):
    _, actor_name = current_actor(request)
    synced_count = 0
    processed_queue_ids = []
    failed_records = []
    
    for record in batch.synced_records:
        try:
            if record.queue_id and record.queue_id in DB_SYNCED_QUEUE_IDS:
                processed_queue_ids.append(record.queue_id)
                synced_count += 1
                continue
            if isinstance(record, ScreeningTriagePayload):
                triage_screening_record(
                    record.model_copy(update={"actor_name": actor_name}),
                    request
                )
            else:
                ingest_screening_record(
                    record.model_copy(update={"actor_name": actor_name}),
                    request
                )
            if record.queue_id:
                DB_SYNCED_QUEUE_IDS.add(record.queue_id)
                processed_queue_ids.append(record.queue_id)
            synced_count += 1
        except Exception as e:
            failed_records.append({
                "queue_id": record.queue_id,
                "record": record.patient_national_id,
                "error": str(e)
            })

    if not postgres_store.is_configured():
        _save_local_state()

    return {
        "status": "PARTIAL" if failed_records else "SUCCESS",
        "device_id": batch.device_id,
        "records_processed": synced_count,
        "processed_queue_ids": processed_queue_ids,
        "failed_count": len(failed_records),
        "failures": failed_records,
        "server_sync_timestamp": utc_now()
    }

@app.post("/api/v1/cases/{case_id}/signoff")
def record_clinician_signoff(
    case_id: UUID4,
    payload: ClinicianSignoffPayload,
    request: Request
):
    case = DB_CASES.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found.")
    if case["case_status"] != "TREATMENT_COMPLETED" or not case.get("discharge_summary"):
        raise HTTPException(
            status_code=409,
            detail="A receiving hospital discharge summary must be uploaded before clinician sign-off."
        )
    clinician_session = DB_CLINICIAN_SESSIONS.get(payload.session_token)
    if clinician_session is None:
        raise HTTPException(status_code=401, detail="Clinician session is invalid or expired.")
    current_user = require_current_clinician(request)
    if not getattr(app.state, "auth_test_bypass", False) and (
        request.session.get("clinician_session_token") != payload.session_token
        or clinician_session.get("identity_id") != current_user["user_id"]
    ):
        raise HTTPException(
            status_code=403,
            detail="The sign-off session must belong to the currently authenticated clinician."
        )
    signature = payload.signature.strip()
    if not signature:
        raise HTTPException(status_code=400, detail="A clinician sign-off value is required.")

    signoffs = DB_SIGNOFFS.setdefault(case_id, {})
    if "primary" not in signoffs:
        signoff_role = "primary"
    elif "secondary" not in signoffs:
        primary_signoff = signoffs["primary"]
        if payload.session_token == primary_signoff["session_token"]:
            raise HTTPException(
                status_code=409,
                detail="The primary clinician session cannot provide the secondary sign-off."
            )
        if (
            clinician_session.get("identity_id")
            and clinician_session["identity_id"] == primary_signoff.get("identity_id")
        ):
            raise HTTPException(
                status_code=409,
                detail="Primary and secondary sign-off must be from different clinician identities."
            )
        if clinician_session["clinician"].casefold() == primary_signoff["clinician"].casefold():
            raise HTTPException(
                status_code=409,
                detail="Primary and secondary sign-off must be from different clinician identities."
            )
        signoff_role = "secondary"
    else:
        raise HTTPException(status_code=409, detail="Both clinician sign-offs have already been recorded.")

    timestamp = utc_now()
    signoff = {
        "role": signoff_role,
        "identity_id": clinician_session.get("identity_id"),
        "clinician": clinician_session["clinician"],
        "clinician_role": clinician_session["role"],
        "session_token": payload.session_token,
        "signature": signature,
        "signed_at": timestamp
    }
    signoffs[signoff_role] = signoff
    case["updated_at"] = timestamp
    _persist_case_snapshot(case)
    append_audit_event(
        case_id,
        f"{signoff_role.upper()}_CLINICIAN_SIGNOFF_RECORDED",
        case["case_status"],
        actor_id=clinician_session.get("identity_id"),
        actor_name=clinician_session["clinician"],
        details={"signoff_role": signoff_role},
        fhir_resource_reference=f"Task/{case_id}"
    )
    return {
        "status": "SUCCESS",
        "role": signoff_role,
        "signoffs": serialized_signoffs(case_id)
    }

@app.post("/api/v1/cases/{case_id}/close", status_code=status.HTTP_200_OK)
def close_case(case_id: UUID4, payload: ClosurePayload, request: Request):
    case = DB_CASES.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found.")
    if case["case_status"] == "CLOSED":
        raise HTTPException(status_code=409, detail="Case is already closed.")
    if case["case_status"] != "TREATMENT_COMPLETED" or not case.get("discharge_summary"):
        raise HTTPException(
            status_code=409,
            detail="A receiving hospital discharge summary must be uploaded before dual-key closure."
        )
    signoffs = DB_SIGNOFFS.get(case_id, {})
    primary_signoff = signoffs.get("primary")
    secondary_signoff = signoffs.get("secondary")
    if not primary_signoff or not secondary_signoff:
        raise HTTPException(status_code=409, detail="Two clinician session sign-offs are required.")
    if (
        (
            primary_signoff.get("session_token")
            and primary_signoff.get("session_token") == secondary_signoff.get("session_token")
        )
        or (
            primary_signoff.get("identity_id")
            and primary_signoff.get("identity_id") == secondary_signoff.get("identity_id")
        )
        or primary_signoff["clinician"].casefold() == secondary_signoff["clinician"].casefold()
    ):
        raise HTTPException(
            status_code=409,
            detail="Dual-key closure requires distinct clinician sessions and identities."
        )
    evidence_doc_id = payload.clinical_evidence_doc_id.strip()
    if not evidence_doc_id:
        raise HTTPException(status_code=400, detail="A clinical evidence document ID is required.")

    case["case_status"] = "CLOSED"
    case["updated_at"] = utc_now()
    closed_at = utc_now()
    actor_id, actor_name = current_actor(request)
    completed_service_requests = []
    for referral in DB_REFERRALS.values():
        if referral["case_id"] == case_id and referral["referral_status"] != "COMPLETED":
            previous_referral_status = referral["referral_status"]
            referral["referral_status"] = "COMPLETED"
            referral["service_request"]["status"] = "completed"
            case["fhir_bundle"]["entry"][0]["resource"] = deepcopy(referral["service_request"])
            _persist_referral(referral, case)
            completed_service_requests.append(str(referral["service_request_id"]))
            append_audit_event(
                case_id,
                "SERVICE_REQUEST_COMPLETED_ON_CASE_CLOSURE",
                "COMPLETED",
                actor_id="ScreenToCare System",
                details={
                    "service_request_id": str(referral["service_request_id"]),
                    "previous_referral_status": previous_referral_status
                },
                fhir_resource_reference=f"ServiceRequest/{referral['service_request_id']}"
            )
    
    closure_record = {
        "closure_id": uuid.uuid4(),
        "case_id": case_id,
        "primary_clinician": primary_signoff["clinician"],
        "secondary_clinician": secondary_signoff["clinician"],
        "clinical_evidence_doc_id": evidence_doc_id,
        "primary_signature": primary_signoff["signature"],
        "secondary_signature": secondary_signoff["signature"],
        "closed_at": closed_at
    }
    DB_CLOSURES[case_id] = closure_record
    if postgres_store.is_configured():
        postgres_store.save_closure(closure_record)
    _persist_case_snapshot(case)
    
    append_audit_event(
        case_id,
        "DUAL_KEY_CASE_CLOSURE",
        "CLOSED",
        actor_id=actor_id,
        actor_name=actor_name,
        details={
            "closure_id": str(closure_record["closure_id"]),
            "primary_clinician": closure_record["primary_clinician"],
            "secondary_clinician": closure_record["secondary_clinician"],
            "clinical_evidence_doc_id": closure_record["clinical_evidence_doc_id"],
            "completed_service_request_ids": completed_service_requests
        },
        fhir_resource_reference=f"Task/{closure_record['closure_id']}"
    )
    
    return {"status": "SUCCESS", "message": "Case successfully closed under Dual-Key protocol.", "closure_id": closure_record["closure_id"]}


def _send_dhmt_webhook(case_id, facility, due_at, risk_level):
    webhook_url = os.getenv("DHMT_WEBHOOK_URL")
    destination = os.getenv("DHMT_ESCALATION_DESTINATION", "dhmt-on-call")
    channel = os.getenv("DHMT_ESCALATION_CHANNEL", "sms").casefold()
    payload = {
        "event": "SLA_LESS_THAN_2_HOURS",
        "case_id": str(case_id),
        "destination": destination,
        "channel": channel,
        "facility": facility,
        "sla_due_at": due_at.isoformat(),
        "risk_level": risk_level,
        "message": f"ScreenToCare DHMT escalation: case {case_id} is nearing its referral SLA."
    }
    if not webhook_url:
        return payload, "SIMULATED", "No gateway configured; recorded as a simulated delivery."
    if not os.getenv("DHMT_ESCALATION_DESTINATION"):
        return payload, "FAILED", "DHMT_ESCALATION_DESTINATION is required for live gateway delivery."
    if channel not in {"sms", "whatsapp"}:
        return payload, "FAILED", "DHMT_ESCALATION_CHANNEL must be sms or whatsapp."

    headers = {"Content-Type": "application/json"}
    token = os.getenv("DHMT_WEBHOOK_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = URLRequest(
        webhook_url,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers=headers,
        method="POST"
    )
    try:
        with urlopen(request, timeout=10) as response:
            response_body = response.read().decode("utf-8")[:500]
            return payload, "SENT", f"Gateway returned HTTP {response.status}: {response_body}"
    except HTTPError as error:
        return payload, "FAILED", f"Gateway returned HTTP {error.code}."
    except URLError as error:
        return payload, "FAILED", f"Gateway connection failed: {error.reason}."


def _record_sla_webhook(case_id, payload, status_name, summary):
    record = {
        "case_id": str(case_id),
        "channel": payload["channel"],
        "destination": payload["destination"],
        "payload": payload,
        "status": status_name,
        "response_summary": summary,
        "timestamp": utc_now()
    }
    DB_DHMT_WEBHOOK_LOG.append(record)
    if postgres_store.is_configured():
        postgres_store.save_webhook_attempt(
            case_id,
            record["channel"],
            record["destination"],
            payload,
            status_name,
            summary
        )


async def _evaluate_postgres_sla_cases():
    claimed_cases = await asyncio.to_thread(postgres_store.claim_due_sla_cases)
    for candidate in claimed_cases:
        case_id = candidate["case_id"]
        case = DB_CASES.get(case_id)
        case_payload = candidate["case_payload"]
        alert = {
            "message": f"Automatic DHMT escalation: case {case_id} is within two hours of its SLA deadline.",
            "actor_name": "ScreenToCare SLA Scheduler",
            "timestamp": utc_now()
        }
        payload, delivery_status, summary = await asyncio.to_thread(
            _send_dhmt_webhook,
            case_id,
            candidate["facility"],
            candidate["sla_due_at"],
            case_payload.get("risk_level", "UNKNOWN")
        )
        alert["delivery_status"] = delivery_status
        _record_sla_webhook(case_id, payload, delivery_status, summary)
        succeeded = delivery_status != "FAILED"
        await asyncio.to_thread(
            postgres_store.finish_sla_alert,
            case_id,
            alert,
            succeeded,
            None if succeeded else summary
        )
        if case is not None:
            case["sla_escalation_alert"] = alert
            case["sla_alerted_at"] = alert["timestamp"] if succeeded else None
            case["updated_at"] = alert["timestamp"]
            _persist_case_snapshot(case)
        append_audit_event(
            case_id,
            "AUTOMATIC_DHMT_SLA_ESCALATION",
            candidate["case_status"],
            actor_id="ScreenToCare SLA Scheduler",
            details={
                "alert": alert["message"],
                "delivery_status": delivery_status
            },
            fhir_resource_reference=(
                f"ServiceRequest/{case['service_request_id']}"
                if case and case.get("service_request_id")
                else f"Case/{case_id}"
            )
        )


async def _evaluate_memory_sla_cases():
    now = utc_now()
    threshold = now + timedelta(hours=2)
    for case in list(DB_CASES.values()):
        if case["case_status"] == "CLOSED" or case.get("sla_alerted_at"):
            continue
        if case["sla_due_at"] > threshold:
            continue
        alert = {
            "message": f"Automatic DHMT escalation: case {case['case_id']} is within two hours of its SLA deadline.",
            "actor_name": "ScreenToCare SLA Scheduler",
            "timestamp": now
        }
        payload, delivery_status, summary = await asyncio.to_thread(
            _send_dhmt_webhook,
            case["case_id"],
            case["facility"],
            case["sla_due_at"],
            case["risk_level"]
        )
        alert["delivery_status"] = delivery_status
        _record_sla_webhook(case["case_id"], payload, delivery_status, summary)
        case["sla_alert_attempts"] = case.get("sla_alert_attempts", 0) + 1
        case["sla_escalation_alert"] = alert
        case["sla_alerted_at"] = (
            now
            if delivery_status != "FAILED" or case["sla_alert_attempts"] >= 5
            else None
        )
        case["updated_at"] = now
        append_audit_event(
            case["case_id"],
            "AUTOMATIC_DHMT_SLA_ESCALATION",
            case["case_status"],
            actor_id="ScreenToCare SLA Scheduler",
            details={
                "alert": alert["message"],
                "delivery_status": delivery_status
            }
        )


async def sla_scheduler_loop():
    try:
        interval = max(5, int(os.getenv("SLA_SCHEDULER_INTERVAL_SECONDS", "60")))
    except ValueError:
        logger.error("SLA_SCHEDULER_INTERVAL_SECONDS must be an integer; using 60 seconds.")
        interval = 60
    while True:
        try:
            if postgres_store.is_configured():
                await _evaluate_postgres_sla_cases()
            else:
                await _evaluate_memory_sla_cases()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("SLA scheduler iteration failed.")
        await asyncio.sleep(interval)


@app.post("/api/v1/integrations/hie/cases/{case_id}")
async def push_case_to_national_hie(case_id: UUID4):
    case = DB_CASES.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found.")
    if not case.get("fhir_bundle"):
        raise HTTPException(status_code=409, detail="FHIR Bundle is not available for this case.")
    try:
        result = await asyncio.to_thread(hie_connector.push_fhir_bundle, case["fhir_bundle"])
    except hie_connector.ConnectorError as error:
        status_code = 503 if "not configured" in str(error) else 502
        raise HTTPException(status_code=status_code, detail=str(error)) from error
    append_audit_event(
        case_id,
        "FHIR_BUNDLE_EXPORTED_TO_NATIONAL_HIE",
        case["case_status"],
        actor_id="ScreenToCare HIE Connector",
        details={"status_code": result["status_code"]},
        fhir_resource_reference=f"Bundle/{case['fhir_bundle']['id']}"
    )
    return {"status": "SENT", "result": result}


@app.post("/api/v1/integrations/dhis2/monthly")
async def push_monthly_dhis2_aggregate(
    year: int = Query(ge=2000, le=2200),
    month: int = Query(ge=1, le=12)
):
    period = f"{year:04d}{month:02d}"
    period_start = datetime(year, month, 1, tzinfo=timezone.utc)
    next_month = datetime(year + (month == 12), 1 if month == 12 else month + 1, 1, tzinfo=timezone.utc)
    screenings = sum(
        period_start <= case["created_at"] < next_month
        for case in DB_CASES.values()
    )
    closures = sum(
        period_start <= closure["closed_at"] < next_month
        for closure in DB_CLOSURES.values()
    )
    aggregate = {"period": period, "screenings": screenings, "closures": closures}
    try:
        result = await asyncio.to_thread(hie_connector.push_dhis2_aggregate, aggregate)
    except hie_connector.ConnectorError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return result


@app.get("/api/v1/integrations/dhis2/simulated")
def get_simulated_dhis2_aggregates():
    return deepcopy(hie_connector.SIMULATED_DHIS2_OUTBOX)


@app.get("/api/v1/sla-alerts")
def list_sla_alerts():
    if postgres_store.is_configured():
        return postgres_store.list_webhook_attempts()
    return deepcopy(list(reversed(DB_DHMT_WEBHOOK_LOG)))
