import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from uuid import UUID


def is_configured():
    return bool(os.getenv("DATABASE_URL"))


def _connect():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for PostgreSQL persistence.")
    if database_url.startswith("postgresql+psycopg://"):
        database_url = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    elif database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    import psycopg

    return psycopg.connect(database_url, connect_timeout=5)


def initialize_schema():
    schema_file = Path(__file__).with_name("schema.sql")
    schema_sql = schema_file.read_text(encoding="utf-8")
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('public.clinician_users')")
            if cursor.fetchone()[0]:
                return False
            cursor.execute(schema_sql)
    return True


def _jsonable(value):
    if isinstance(value, (UUID, datetime)):
        return value.isoformat() if isinstance(value, datetime) else str(value)
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _clinician_user_from_row(row):
    if not row:
        return None
    return {
        "user_id": str(row[0]),
        "full_name": row[1],
        "email": row[2],
        "clinical_role": row[3],
        "password_hash": row[4],
        "created_at": row[5]
    }


_CLINICIAN_USER_COLUMNS = """
    user_id, full_name, email, clinical_role, password_hash, created_at
"""


def create_clinician_user(user):
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO clinician_users (
                    user_id, full_name, email, clinical_role, password_hash,
                    account_status, is_admin, created_at
                )
                VALUES (%s, %s, %s, %s, %s, 'APPROVED', FALSE, %s)
                ON CONFLICT (email) DO NOTHING
                RETURNING {_CLINICIAN_USER_COLUMNS}
                """,
                (
                    user["user_id"],
                    user["full_name"],
                    user["email"],
                    user["clinical_role"],
                    user["password_hash"],
                    user["created_at"]
                )
            )
            return _clinician_user_from_row(cursor.fetchone())


def upsert_demo_clinician_user(user):
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO clinician_users (
                    user_id, full_name, email, clinical_role, password_hash,
                    account_status, is_admin, created_at
                )
                VALUES (%s, %s, %s, %s, %s, 'APPROVED', FALSE, %s)
                ON CONFLICT (email) DO UPDATE SET
                    full_name = EXCLUDED.full_name,
                    clinical_role = EXCLUDED.clinical_role,
                    password_hash = EXCLUDED.password_hash,
                    account_status = 'APPROVED'
                RETURNING {_CLINICIAN_USER_COLUMNS}
                """,
                (
                    user["user_id"],
                    user["full_name"],
                    user["email"],
                    user["clinical_role"],
                    user["password_hash"],
                    user["created_at"]
                )
            )
            return _clinician_user_from_row(cursor.fetchone())


def activate_legacy_clinician_accounts():
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE clinician_users SET account_status = 'APPROVED' "
                "WHERE account_status = 'PENDING'"
            )


def get_clinician_user_by_email(email):
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {_CLINICIAN_USER_COLUMNS} FROM clinician_users WHERE email = %s",
                (email,)
            )
            return _clinician_user_from_row(cursor.fetchone())


def get_clinician_user_by_id(user_id):
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {_CLINICIAN_USER_COLUMNS} FROM clinician_users WHERE user_id = %s",
                (user_id,)
            )
            return _clinician_user_from_row(cursor.fetchone())


def upsert_patient(patient):
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT patient_id, date_of_birth
                FROM patients
                WHERE national_id = %s
                FOR UPDATE
                """,
                (patient["national_id"],)
            )
            existing = cursor.fetchone()
            if existing:
                if existing[1].isoformat() != patient["date_of_birth"]:
                    raise ValueError("The supplied Omang ID is already associated with a different date of birth.")
                cursor.execute(
                    """
                    UPDATE patients
                    SET mpi_hash = %s, full_name = %s, gender = %s, phone_number = %s,
                        preferred_channel = %s, consent_signed = %s, consent_signed_at = %s
                    WHERE patient_id = %s
                    RETURNING patient_id
                    """,
                    (
                        patient["mpi_hash"],
                        patient["name"],
                        patient["gender"],
                        patient["phone"],
                        patient["preferred_channel"],
                        patient["consent_signed"],
                        patient["consent_signed_at"],
                        existing[0]
                    )
                )
                return cursor.fetchone()[0]

            cursor.execute(
                """
                INSERT INTO patients (
                    patient_id, national_id, mpi_hash, full_name, date_of_birth,
                    gender, phone_number, preferred_channel, consent_signed, consent_signed_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (mpi_hash) DO UPDATE SET
                    full_name = EXCLUDED.full_name,
                    gender = EXCLUDED.gender,
                    phone_number = EXCLUDED.phone_number,
                    preferred_channel = EXCLUDED.preferred_channel,
                    consent_signed = EXCLUDED.consent_signed,
                    consent_signed_at = EXCLUDED.consent_signed_at
                RETURNING patient_id
                """,
                (
                    patient["patient_id"],
                    patient["national_id"],
                    patient["mpi_hash"],
                    patient["name"],
                    patient["date_of_birth"],
                    patient["gender"],
                    patient["phone"],
                    patient["preferred_channel"],
                    patient["consent_signed"],
                    patient["consent_signed_at"]
                )
            )
            return cursor.fetchone()[0]


def save_case(case, signoffs=None):
    from psycopg.types.json import Jsonb

    payload = _jsonable(case)
    payload["screening_type"] = case["screening_type"]
    payload["facility"] = case["facility"]
    payload["signoffs"] = {
        role: {
            key: value
            for key, value in signoff.items()
            if key != "session_token"
        }
        for role, signoff in (signoffs or {}).items()
    }
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO screening_cases (
                    case_id, patient_id, current_owner_id, risk_level, case_status,
                    sla_due_at, is_overdue, screening_type, screening_result_value,
                    facility, sla_escalation_alert, case_payload, sla_alerted_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (case_id) DO UPDATE SET
                    risk_level = EXCLUDED.risk_level,
                    case_status = EXCLUDED.case_status,
                    sla_due_at = EXCLUDED.sla_due_at,
                    is_overdue = EXCLUDED.is_overdue,
                    screening_type = EXCLUDED.screening_type,
                    screening_result_value = EXCLUDED.screening_result_value,
                    facility = EXCLUDED.facility,
                    sla_escalation_alert = EXCLUDED.sla_escalation_alert,
                    case_payload = EXCLUDED.case_payload,
                    sla_alerted_at = EXCLUDED.sla_alerted_at,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    case["case_id"],
                    case["patient_id"],
                    case["current_owner_id"],
                    case["risk_level"],
                    case["case_status"],
                    case["sla_due_at"],
                    case.get("is_overdue", False),
                    case["screening_type"],
                    case["screening_result_value"],
                    case["facility"],
                    Jsonb(_jsonable(case["sla_escalation_alert"]))
                    if case.get("sla_escalation_alert") else None,
                    Jsonb(payload),
                    case.get("sla_alerted_at"),
                    case.get("updated_at", case["created_at"])
                )
            )


def save_referral(referral, case):
    from psycopg.types.json import Jsonb

    payload = _jsonable(referral)
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO referrals (
                    referral_id, case_id, service_request_id, sending_facility,
                    receiving_facility, referral_status, fhir_service_request,
                    referral_payload, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (service_request_id) DO UPDATE SET
                    referral_status = EXCLUDED.referral_status,
                    fhir_service_request = EXCLUDED.fhir_service_request,
                    referral_payload = EXCLUDED.referral_payload
                """,
                (
                    referral["service_request_id"],
                    case["case_id"],
                    referral["service_request_id"],
                    case["facility"],
                    case["facility"],
                    referral["referral_status"],
                    Jsonb(_jsonable(referral["service_request"])),
                    Jsonb(payload),
                    referral["created_at"]
                )
            )


def save_closure(closure):
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO case_closures (
                    closure_id, case_id, primary_clinician, secondary_clinician,
                    clinical_evidence_doc_id, primary_signature, secondary_signature, closed_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (case_id) DO UPDATE SET
                    primary_clinician = EXCLUDED.primary_clinician,
                    secondary_clinician = EXCLUDED.secondary_clinician,
                    clinical_evidence_doc_id = EXCLUDED.clinical_evidence_doc_id,
                    primary_signature = EXCLUDED.primary_signature,
                    secondary_signature = EXCLUDED.secondary_signature,
                    closed_at = EXCLUDED.closed_at
                """,
                (
                    closure["closure_id"],
                    closure["case_id"],
                    closure["primary_clinician"],
                    closure["secondary_clinician"],
                    closure["clinical_evidence_doc_id"],
                    closure["primary_signature"],
                    closure["secondary_signature"],
                    closure["closed_at"]
                )
            )


def insert_audit_event(event):
    from psycopg.types.json import Jsonb

    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(724811, 51005)")
            cursor.execute(
                "SELECT verification_hash FROM audit_timeline ORDER BY audit_sequence DESC LIMIT 1"
            )
            previous_row = cursor.fetchone()
            previous_hash = previous_row[0].strip() if previous_row else None
            hash_payload = {
                "event_id": str(event["event_id"]),
                "case_id": str(event["case_id"]),
                "action_type": event["action_type"],
                "new_state": event["new_state"],
                "actor_name": event["actor_name"],
                "fhir_resource_reference": event["fhir_resource_reference"],
                "details": _jsonable(event["details"]),
                "timestamp": event["timestamp"].isoformat(),
                "previous_hash": previous_hash
            }
            verification_hash = hashlib.sha256(
                json.dumps(hash_payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
            ).hexdigest()
            cursor.execute(
                """
                INSERT INTO audit_timeline (
                    event_id, case_id, action_type, new_state, actor_id, actor_name,
                    fhir_resource_reference, details, timestamp, previous_hash, verification_hash
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    event["event_id"],
                    event["case_id"],
                    event["action_type"],
                    event["new_state"],
                    event["actor_id"],
                    event["actor_name"],
                    event["fhir_resource_reference"],
                    Jsonb(_jsonable(event["details"])),
                    event["timestamp"],
                    previous_hash,
                    verification_hash
                )
            )
            return previous_hash, verification_hash


def claim_due_sla_cases(limit=100):
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                WITH candidates AS (
                    SELECT case_id
                    FROM screening_cases
                    WHERE case_status <> 'CLOSED'
                      AND sla_due_at <= CURRENT_TIMESTAMP + INTERVAL '2 hours'
                      AND sla_alerted_at IS NULL
                      AND sla_alert_attempts < 5
                      AND (
                        sla_alert_claimed_at IS NULL OR
                        sla_alert_claimed_at < CURRENT_TIMESTAMP - INTERVAL '5 minutes'
                      )
                    ORDER BY sla_due_at
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE screening_cases AS cases
                SET sla_alert_claimed_at = CURRENT_TIMESTAMP,
                    sla_alert_attempts = cases.sla_alert_attempts + 1
                FROM candidates
                WHERE cases.case_id = candidates.case_id
                RETURNING cases.case_id, cases.case_status, cases.sla_due_at,
                          cases.case_payload
                """,
                (limit,)
            )
            claimed = cursor.fetchall()
            results = []
            for row in claimed:
                cursor.execute(
                    """
                    SELECT screening_cases.facility
                    FROM screening_cases
                    JOIN patients USING (patient_id)
                    WHERE screening_cases.case_id = %s
                    """,
                    (row[0],)
                )
                facility = cursor.fetchone()[0]
                results.append({
                    "case_id": row[0],
                    "case_status": row[1],
                    "sla_due_at": row[2],
                    "case_payload": row[3] or {},
                    "facility": facility
                })
            return results


def finish_sla_alert(case_id, alert, succeeded, error=None):
    from psycopg.types.json import Jsonb

    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE screening_cases
                SET sla_alerted_at = CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE NULL END,
                    sla_alert_claimed_at = NULL,
                    sla_alert_error = %s,
                    sla_escalation_alert = %s,
                    case_payload = jsonb_set(
                        case_payload,
                        '{sla_escalation_alert}',
                        %s::jsonb,
                        true
                    )
                WHERE case_id = %s
                """,
                (
                    succeeded,
                    error,
                    Jsonb(_jsonable(alert)),
                    json.dumps(_jsonable(alert)),
                    case_id
                )
            )


def save_webhook_attempt(case_id, channel, destination, payload, status, response=None):
    from psycopg.types.json import Jsonb

    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO webhook_alerts (
                    case_id, channel, destination, payload, delivery_status, response_summary
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    case_id,
                    channel,
                    destination,
                    Jsonb(_jsonable(payload)),
                    status,
                    response
                )
            )


def list_webhook_attempts(limit=100):
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT case_id, channel, destination, payload, delivery_status,
                       response_summary, created_at
                FROM webhook_alerts
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,)
            )
            return [{
                "case_id": str(row[0]),
                "channel": row[1],
                "destination": row[2],
                "payload": row[3],
                "status": row[4],
                "response_summary": row[5],
                "timestamp": row[6]
            } for row in cursor.fetchall()]


def load_state():
    state = {
        "patients": {},
        "cases": {},
        "referrals": {},
        "closures": {},
        "signoffs": {},
        "audit": []
    }
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT patient_id, national_id, full_name, date_of_birth, gender,
                       phone_number, preferred_channel, mpi_hash, consent_signed,
                       consent_signed_at
                FROM patients
                """
            )
            for row in cursor.fetchall():
                patient = {
                    "patient_id": row[0],
                    "national_id": row[1],
                    "name": row[2],
                    "date_of_birth": row[3].isoformat(),
                    "gender": row[4],
                    "phone": row[5],
                    "preferred_channel": row[6],
                    "mpi_hash": row[7].strip(),
                    "consent_signed": row[8],
                    "consent_signed_at": row[9],
                    "screening_type": None,
                    "facility": None
                }
                state["patients"][row[0]] = patient

            cursor.execute(
                """
                SELECT case_id, patient_id, current_owner_id, risk_level, case_status,
                       sla_due_at, is_overdue, screening_type, screening_result_value,
                       facility, created_at, updated_at, case_payload
                FROM screening_cases ORDER BY created_at DESC
                """
            )
            for (
                case_id, patient_id, owner_id, risk_level, case_status, sla_due_at,
                is_overdue, screening_type, screening_result_value, facility,
                created_at, updated_at, payload
            ) in cursor.fetchall():
                case = payload or {}
                patient = state["patients"].get(patient_id)
                if patient and patient["screening_type"] is None:
                    patient["screening_type"] = case.get("screening_type", screening_type)
                    patient["facility"] = case.get("facility", facility)
                case["case_id"] = case_id
                case["patient_id"] = patient_id
                case["current_owner_id"] = UUID(str(case.get("current_owner_id", owner_id)))
                case["risk_level"] = case.get("risk_level", risk_level)
                case["case_status"] = case.get("case_status", case_status)
                case["screening_type"] = case.get("screening_type", screening_type)
                case["facility"] = case.get("facility", facility)
                case["sla_due_at"] = _as_datetime(case.get("sla_due_at", sla_due_at))
                case["is_overdue"] = case.get("is_overdue", is_overdue)
                case["screening_result_value"] = case.get("screening_result_value", screening_result_value)
                case["created_at"] = _as_datetime(case.get("created_at", created_at))
                case["updated_at"] = _as_datetime(case.get("updated_at", updated_at or created_at))
                case.setdefault("actor_name", "Restored from PostgreSQL")
                case.setdefault("service_request", None)
                case.setdefault("fhir_bundle", None)
                case.setdefault("communications", [])
                case.setdefault("discharge_summary", None)
                case.setdefault("sla_escalation_alert", None)
                case.setdefault("sla_alert_attempts", 0)
                case.setdefault("sla_alert_error", None)
                case["sla_alerted_at"] = _as_datetime(case.get("sla_alerted_at"))
                if case.get("service_request_id"):
                    case["service_request_id"] = UUID(str(case["service_request_id"]))
                if case.get("discharge_summary"):
                    case["discharge_summary"]["uploaded_at"] = _as_datetime(
                        case["discharge_summary"]["uploaded_at"]
                    )
                if case.get("sla_escalation_alert"):
                    case["sla_escalation_alert"]["timestamp"] = _as_datetime(
                        case["sla_escalation_alert"]["timestamp"]
                    )
                for communication in case.get("communications", []):
                    communication["timestamp"] = _as_datetime(communication["timestamp"])
                case_signoffs = case.pop("signoffs", {})
                for signoff in case_signoffs.values():
                    signoff["signed_at"] = _as_datetime(signoff["signed_at"])
                    signoff["session_token"] = None
                state["signoffs"][case_id] = case_signoffs
                state["cases"][case_id] = case

            cursor.execute(
                """
                SELECT service_request_id, case_id, referral_status,
                       fhir_service_request, created_at, referral_payload
                FROM referrals
                """
            )
            for referral_id, case_id, referral_status, service_request, created_at, payload in cursor.fetchall():
                referral = payload or {}
                referral.setdefault("case_id", str(case_id))
                referral.setdefault("referral_status", referral_status)
                referral.setdefault("service_request", service_request)
                referral.setdefault("created_at", created_at.isoformat())
                referral["service_request_id"] = referral_id
                referral["case_id"] = UUID(str(referral["case_id"]))
                referral["created_at"] = _as_datetime(referral["created_at"])
                state["referrals"][referral_id] = referral

            cursor.execute(
                """
                SELECT closure_id, case_id, primary_clinician, secondary_clinician,
                       clinical_evidence_doc_id, primary_signature, secondary_signature, closed_at
                FROM case_closures
                """
            )
            for row in cursor.fetchall():
                state["closures"][row[1]] = {
                    "closure_id": row[0],
                    "case_id": row[1],
                    "primary_clinician": row[2],
                    "secondary_clinician": row[3],
                    "clinical_evidence_doc_id": row[4],
                    "primary_signature": row[5],
                    "secondary_signature": row[6],
                    "closed_at": row[7]
                }

            cursor.execute(
                """
                SELECT event_id, case_id, action_type, new_state, actor_id, actor_name,
                       fhir_resource_reference, details, timestamp, previous_hash, verification_hash
                FROM audit_timeline ORDER BY audit_sequence
                """
            )
            for row in cursor.fetchall():
                state["audit"].append({
                    "event_id": row[0],
                    "case_id": row[1],
                    "action_type": row[2],
                    "new_state": row[3],
                    "actor_id": row[4],
                    "actor_name": row[5],
                    "fhir_resource_reference": row[6],
                    "details": row[7],
                    "timestamp": row[8],
                    "previous_hash": row[9].strip() if row[9] else None,
                    "verification_hash": row[10].strip()
                })
    return state


def _as_datetime(value):
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)
