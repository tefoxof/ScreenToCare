"""ScreenToCare API and workflow tests."""

import asyncio
import hashlib
import json
from datetime import date, timedelta
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
import hie_connector
import main
from main import app, classify_demo_triage, patient_mpi_hash

client = TestClient(app)
app.state.auth_test_bypass = True

def assert_audit_event_hash_valid(event):
    hash_payload = {
        key: event[key]
        for key in (
            "event_id",
            "case_id",
            "action_type",
            "new_state",
            "actor_name",
            "fhir_resource_reference",
            "details",
            "timestamp",
            "previous_hash"
        )
    }
    encoded = json.dumps(hash_payload, sort_keys=True, separators=(",", ":"), default=str)
    assert hashlib.sha256(encoded.encode("utf-8")).hexdigest() == event["verification_hash"]

def test_demo_clinician_sessions_are_accessible_and_distinct():
    assert client.get("/api/v1/cases").status_code == 200
    primary = client.post(
        "/api/v1/clinicians/session",
        json={"clinician_id": "triage_lead"}
    )
    secondary = client.post(
        "/api/v1/clinicians/session",
        json={"clinician_id": "oncology_specialist"}
    )

    assert primary.status_code == 200
    assert secondary.status_code == 200
    assert primary.json()["clinician"] == "Dr. T. Tlhagiso"
    assert secondary.json()["clinician"] == "Dr. K. Moyo"
    assert primary.json()["session_token"] != secondary.json()["session_token"]
    assert client.get("/api/v1/auth/config").status_code == 404

def test_preloaded_demo_clinicians_share_the_demo_pin(monkeypatch):
    original_users = main.DB_CLINICIAN_USERS.copy()
    original_email_index = main.DB_CLINICIAN_EMAIL_INDEX.copy()
    monkeypatch.setattr(main.postgres_store, "is_configured", lambda: False)
    monkeypatch.setattr(main, "_save_local_state", lambda: None)
    try:
        main.DB_CLINICIAN_USERS.clear()
        main.DB_CLINICIAN_EMAIL_INDEX.clear()
        main.seed_demo_clinician_account()

        for email in ("dr.tlhagiso@health.gov.bw", "dr.kabelo@health.gov.bw"):
            user = main.find_clinician_by_email(email)
            assert user is not None
            assert main.verify_password("2026", user["password_hash"])
    finally:
        main.DB_CLINICIAN_USERS.clear()
        main.DB_CLINICIAN_USERS.update(original_users)
        main.DB_CLINICIAN_EMAIL_INDEX.clear()
        main.DB_CLINICIAN_EMAIL_INDEX.update(original_email_index)

def test_postgres_schema_initialization_only_runs_on_an_empty_database(monkeypatch):
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (None,)
    monkeypatch.setattr(main.postgres_store, "_connect", lambda: connection)

    assert main.postgres_store.initialize_schema() is True
    assert "CREATE TABLE IF NOT EXISTS clinician_users" in cursor.execute.call_args_list[1].args[0]

    cursor.execute.reset_mock()
    cursor.fetchone.return_value = ("clinician_users",)
    assert main.postgres_store.initialize_schema() is False
    assert cursor.execute.call_count == 1

def test_registration_allows_immediate_login_and_case_audit_attribution():
    app.state.auth_test_bypass = False
    client.cookies.clear()
    main.DB_CLINICIAN_USERS.clear()
    main.DB_CLINICIAN_EMAIL_INDEX.clear()
    try:
        registration = client.post("/api/v1/auth/register", json={
            "full_name": "Dr. Test Clinician",
            "email": "clinician@example.org",
            "clinical_role": "Clinical Officer",
            "password": "clinician-password-123"
        })
        assert registration.status_code == 201
        assert registration.json()["status"] == "REGISTERED"
        assert "approval" not in registration.json()["message"].casefold()

        clinician_login = client.post("/api/v1/auth/login", json={
            "email": "clinician@example.org",
            "password": "clinician-password-123"
        })
        assert clinician_login.status_code == 200
        assert "is_admin" not in clinician_login.json()
        assert "account_status" not in clinician_login.json()
        assert client.get("/api/v1/auth/registrations/pending").status_code == 404
        assert client.post(
            "/api/v1/auth/registrations/00000000-0000-0000-0000-000000000001/approve"
        ).status_code == 404
        assert client.get("/api/v1/cases").status_code == 200

        intake = client.post("/api/v1/screening/ingest", json={
            "patient_national_id": "AUTH-ATTRIBUTION-001",
            "patient_name": "Attribution Test Patient",
            "date_of_birth": "1987-01-02",
            "gender": "Female",
            "phone_number": "+26770000009",
            "consent_signed": True,
            "screening_type": "General Screen",
            "screening_result_value": "Routine screening",
            "risk_level": "MODERATE",
            "actor_name": "Forged Client Actor"
        })
        assert intake.status_code == 201
        case_id = intake.json()["case_id"]
        opened = client.get(f"/api/v1/cases/{case_id}")
        assert opened.status_code == 200
        case_events = [
            event for event in client.get("/api/v1/audit").json()
            if event["case_id"] == case_id
        ]
        assert [event["actor_name"] for event in case_events][:2] == [
            "Dr. Test Clinician",
            "Dr. Test Clinician"
        ]
        assert [event["action_type"] for event in case_events][0] == "CASE_RECORD_OPENED"
        client.post("/api/v1/auth/logout")
        assert client.get(f"/api/v1/cases/{case_id}").status_code == 401
    finally:
        client.cookies.clear()
        app.state.auth_test_bypass = True

def test_dual_signoff_requires_two_authenticated_clinician_accounts():
    app.state.auth_test_bypass = False
    main.DB_CLINICIAN_USERS.clear()
    main.DB_CLINICIAN_EMAIL_INDEX.clear()
    users = [
        {
            "user_id": "00000000-0000-0000-0000-000000000011",
            "full_name": "Primary Clinician",
            "email": "primary@example.org",
            "password": "primary-password-123"
        },
        {
            "user_id": "00000000-0000-0000-0000-000000000012",
            "full_name": "Secondary Clinician",
            "email": "secondary@example.org",
            "password": "secondary-password-123"
        }
    ]
    for user in users:
        main.cache_clinician_user({
            "user_id": user["user_id"],
            "full_name": user["full_name"],
            "email": user["email"],
            "clinical_role": "Clinical Officer",
            "password_hash": main.hash_password(user["password"]),
            "account_status": "APPROVED",
            "is_admin": False,
            "created_at": main.utc_now(),
            "approved_at": main.utc_now(),
            "approved_by": None
        })

    try:
        with TestClient(app) as primary_client, TestClient(app) as secondary_client:
            primary_login = primary_client.post("/api/v1/auth/login", json={
                "email": users[0]["email"],
                "password": users[0]["password"]
            })
            secondary_login = secondary_client.post("/api/v1/auth/login", json={
                "email": users[1]["email"],
                "password": users[1]["password"]
            })
            assert primary_login.status_code == secondary_login.status_code == 200
            intake = primary_client.post("/api/v1/screening/triage", json={
                "patient_national_id": "DUAL-AUTH-TEST-001",
                "patient_name": "Dual Auth Test Patient",
                "date_of_birth": "1986-03-04",
                "gender": "Other",
                "phone_number": "+26770000010",
                "consent_signed": True,
                "screening_type": "General Screen",
                "raw_screening_notes": "Routine screening"
            })
            assert intake.status_code == 201
            case_id = intake.json()["case"]["case_id"]
            assert primary_client.post(f"/api/v1/cases/{case_id}/dispatch").status_code == 200
            assert primary_client.post(f"/api/v1/cases/{case_id}/arrival").status_code == 200
            assert primary_client.post(
                f"/api/v1/cases/{case_id}/discharge-summary",
                json={
                    "document_id": "DISCHARGE-AUTH-001",
                    "clinical_outcome_note": "Treatment completed."
                }
            ).status_code == 200

            signoff_url = f"/api/v1/cases/{case_id}/signoff"
            primary_payload = {
                "session_token": primary_login.json()["session_token"],
                "signature": "Primary approval"
            }
            assert primary_client.post(signoff_url, json=primary_payload).status_code == 200
            assert primary_client.post(signoff_url, json=primary_payload).status_code == 409
            assert secondary_client.post(signoff_url, json={
                "session_token": secondary_login.json()["session_token"],
                "signature": "Secondary approval"
            }).status_code == 200
            assert primary_client.post(signoff_url, json={
                "session_token": secondary_login.json()["session_token"],
                "signature": "Spoofed secondary approval"
            }).status_code == 403
            assert primary_client.post(
                f"/api/v1/cases/{case_id}/close",
                json={"clinical_evidence_doc_id": "EVIDENCE-AUTH-001"}
            ).status_code == 200

            signoff_events = [
                event for event in primary_client.get("/api/v1/audit").json()
                if event["case_id"] == case_id and "CLINICIAN_SIGNOFF_RECORDED" in event["action_type"]
            ]
            assert {event["actor_name"] for event in signoff_events} == {
                "Primary Clinician",
                "Secondary Clinician"
            }
    finally:
        app.state.auth_test_bypass = True

def test_demo_triage_rules_return_expected_sla_windows():
    critical_risk, _, critical_sla = classify_demo_triage("Positive GeneXpert")
    high_risk, _, high_sla = classify_demo_triage("Stage 2 hypertension")
    moderate_risk, _, moderate_sla = classify_demo_triage("Routine screening")
    assert (critical_risk, critical_sla) == ("CRITICAL_RED_FLAG", 12)
    assert (high_risk, high_sla) == ("HIGH", 24)
    assert (moderate_risk, moderate_sla) == ("MODERATE", 48)

def test_ingest_screening_record():
    payload = {
        "patient_national_id": "TEST-OMANG-001",
        "patient_name": "Kabelo Test",
        "date_of_birth": "1988-04-20",
        "gender": "Male",
        "phone_number": "+26772000000",
        "consent_signed": True,
        "preferred_channel": "whatsapp",
        "screening_type": "Cardiovascular Risk",
        "screening_result_value": "Stage 2 Hypertension",
        "risk_level": "HIGH"
    }
    response = client.post("/api/v1/screening/ingest", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["risk_level"] == "HIGH"
    assert data["case_status"] == "RESULT_INGESTED"
    assert "case_id" in data

def test_offline_sync_queue():
    batch_payload = {
        "device_id": "test_mobile_van_01",
        "synced_records": [
            {
                "patient_national_id": "OFFLINE-ID-01",
                "patient_name": "Offline Patient",
                "date_of_birth": "1995-10-10",
                "gender": "Female",
                "phone_number": "+26771111111",
                "consent_signed": True,
                "preferred_channel": "sms",
                "screening_type": "Tuberculosis",
                "screening_result_value": "Positive Screen",
                "risk_level": "CRITICAL_RED_FLAG"
            }
        ]
    }
    response = client.post("/api/v1/sync/queue", json=batch_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "SUCCESS"
    assert data["records_processed"] == 1

def test_triage_generates_coded_fhir_payload_and_dispatch_logs_bilingual_notifications():
    response = client.post("/api/v1/screening/triage", json={
        "patient_national_id": "TRIAGE-TEST-001",
        "patient_name": "Triage Test Patient",
        "date_of_birth": "1980-01-01",
        "gender": "Female",
        "phone_number": "+26770000001",
        "consent_signed": True,
        "screening_type": "Tuberculosis Screen",
        "facility": "Gaborone Clinic",
        "raw_screening_notes": "Positive GeneXpert result with severe chest pain"
    })

    assert response.status_code == 201
    data = response.json()
    assert data["triage"]["mode"] == "DEMO_RULE_BASED"
    assert data["triage"]["risk_level"] == "CRITICAL_RED_FLAG"
    assert data["triage"]["sla_hours"] == 12
    assert "keyword-based demo" in data["triage"]["rationale_summary"]
    assert data["draft_patient_sms"]["status"] == "DRAFT"
    assert data["draft_patient_sms"]["channel"] == "sms"
    assert "no message has been sent" in data["draft_patient_sms"]["message"]
    assert any(
        coding["code"] == "29857009"
        for tag in data["triage"]["risk_tags"]
        for coding in tag["coding"]
    )
    assert any(
        coding["system"] == "http://hl7.org/fhir/sid/icd-10-cm"
        for tag in data["triage"]["risk_tags"]
        for coding in tag["coding"]
    )
    service_request = data["service_request"]
    assert service_request["resourceType"] == "ServiceRequest"
    assert service_request["status"] == "draft"
    assert service_request["intent"] == "order"
    assert service_request["code"]["text"] == "Tuberculosis Screen"
    assert service_request["subject"]["reference"].startswith("Patient/")
    assert data["fhir_bundle"]["resourceType"] == "Bundle"
    assert data["fhir_bundle"]["entry"][0]["resource"] == service_request

    referrals = client.get("/api/v1/referrals").json()
    assert all(item["case_id"] != data["case"]["case_id"] for item in referrals)

    dispatch_response = client.post(
        f"/api/v1/cases/{data['case']['case_id']}/dispatch",
        json={"actor_name": "Queue Clinician"}
    )
    assert dispatch_response.status_code == 200
    dispatched = dispatch_response.json()
    assert dispatched["service_request"]["resourceType"] == "ServiceRequest"
    assert dispatched["service_request"]["status"] == "active"
    assert dispatched["service_request"]["subject"]["reference"].startswith("Patient/")

    referrals = client.get("/api/v1/referrals").json()
    referral = next(item for item in referrals if item["case_id"] == data["case"]["case_id"])
    assert referral["referral_status"] == "DISPATCHED"
    assert referral["case_status"] == "REFERRAL_DISPATCHED"
    notifications = referral["communication_log"]
    assert {item["language"] for item in notifications} == {"English", "Setswana"}
    assert all(item["phone_number"] == "+26770000001" for item in notifications)
    assert all(item["facility"] == "Gaborone Clinic" for item in notifications)
    assert all(item["sla_deadline"] for item in notifications)
    assert all(item["channel"] == "whatsapp" for item in notifications)

    case = next(
        item for item in client.get("/api/v1/cases").json()
        if item["case_id"] == data["case"]["case_id"]
    )
    assert case["status"] == "REFERRAL_DISPATCHED"

    case_events = [
        event for event in client.get("/api/v1/audit").json()
        if event["case_id"] == data["case"]["case_id"]
    ]
    assert {event["action_type"] for event in case_events} >= {
        "RESULT_INGESTED_AND_SLA_INITIALIZED",
        "DEMO_TRIAGE_COMPLETED",
        "FHIR_SERVICEREQUEST_DISPATCHED",
        "BILINGUAL_PATIENT_NOTIFICATION_SIMULATED"
    }
    for event in case_events:
        assert event["actor_name"]
        assert event["fhir_resource_reference"]
        assert_audit_event_hash_valid(event)

def test_dual_signoff_closure_updates_case_and_preserves_audit_history():
    triage_response = client.post("/api/v1/screening/triage", json={
        "patient_national_id": "CLOSE-TEST-001",
        "patient_name": "Closure Test Patient",
        "date_of_birth": "1985-02-02",
        "gender": "Male",
        "phone_number": "+26770000002",
        "consent_signed": True,
        "screening_type": "Cardiovascular Risk",
        "raw_screening_notes": "Stage 2 hypertension"
    })
    assert triage_response.status_code == 201
    case_id = triage_response.json()["case"]["case_id"]

    payload = {"clinical_evidence_doc_id": "EVIDENCE-TEST-001"}

    premature_close = client.post(f"/api/v1/cases/{case_id}/close", json=payload)
    assert premature_close.status_code == 409
    assert client.post(f"/api/v1/cases/{case_id}/arrival").status_code == 409

    dispatch_response = client.post(
        f"/api/v1/cases/{case_id}/dispatch",
        json={"actor_name": "Queue Clinician"}
    )
    assert dispatch_response.status_code == 200
    escalation_response = client.post(
        f"/api/v1/cases/{case_id}/escalate",
        json={
            "actor_name": "DHMT Escalation Desk",
            "alert_reason": "Urgent SLA escalation."
        }
    )
    assert escalation_response.status_code == 200
    assert escalation_response.json()["alert"]["message"] == "Urgent SLA escalation."
    arrival_response = client.post(
        f"/api/v1/cases/{case_id}/arrival",
        json={"actor_name": "Receiving Facility"}
    )
    assert arrival_response.status_code == 200
    assert arrival_response.json()["case"]["status"] == "ARRIVED_AT_FACILITY"

    summary_response = client.post(
        f"/api/v1/cases/{case_id}/discharge-summary",
        json={
            "document_id": "DISCHARGE-TEST-001",
            "clinical_outcome_note": "Patient received treatment and is stable.",
            "actor_name": "Receiving Hospital"
        }
    )
    assert summary_response.status_code == 200
    assert summary_response.json()["case"]["status"] == "TREATMENT_COMPLETED"

    audit_before = client.get("/api/v1/audit").json()
    triage_event = next(
        event for event in audit_before
        if event["case_id"] == case_id
        and event["action_type"] == "DEMO_TRIAGE_COMPLETED"
    )
    assert triage_event["timestamp"].endswith("+00:00")

    primary_session = client.post(
        "/api/v1/clinicians/session",
        json={"clinician_id": "triage_lead"}
    ).json()
    same_clinician_session = client.post(
        "/api/v1/clinicians/session",
        json={"clinician_id": "triage_lead"}
    ).json()
    secondary_session = client.post(
        "/api/v1/clinicians/session",
        json={"clinician_id": "oncology_specialist"}
    ).json()
    signoff_url = f"/api/v1/cases/{case_id}/signoff"
    primary_signoff = client.post(signoff_url, json={
        "session_token": primary_session["session_token"],
        "signature": "primary-signature-demo"
    })
    assert primary_signoff.status_code == 200
    assert primary_signoff.json()["role"] == "primary"
    case_after_primary_signoff = next(
        item for item in client.get("/api/v1/cases").json()
        if item["case_id"] == case_id
    )
    primary_signoff_metadata = case_after_primary_signoff["signoffs"]["primary"]
    assert primary_signoff_metadata["clinician"] == "Dr. T. Tlhagiso"
    assert "session_token" not in primary_signoff_metadata
    assert "signature" not in primary_signoff_metadata
    assert client.post(signoff_url, json={
        "session_token": primary_session["session_token"],
        "signature": "same-session-secondary-attempt"
    }).status_code == 409
    assert client.post(signoff_url, json={
        "session_token": same_clinician_session["session_token"],
        "signature": "same-clinician-secondary-attempt"
    }).status_code == 409
    secondary_signoff = client.post(signoff_url, json={
        "session_token": secondary_session["session_token"],
        "signature": "secondary-signature-demo"
    })
    assert secondary_signoff.status_code == 200
    assert secondary_signoff.json()["role"] == "secondary"

    response = client.post(f"/api/v1/cases/{case_id}/close", json=payload)
    assert response.status_code == 200
    assert client.post(f"/api/v1/cases/{case_id}/close", json=payload).status_code == 409

    case = next(
        item for item in client.get("/api/v1/cases").json()
        if item["case_id"] == case_id
    )
    assert case["status"] == "CLOSED"
    assert case["sla_remaining"] == "DONE"
    closure_referral = next(
        item for item in client.get("/api/v1/referrals").json()
        if item["case_id"] == case_id
    )
    assert closure_referral["referral_status"] == "COMPLETED"
    assert closure_referral["service_request"]["status"] == "completed"
    assert closure_referral["fhir_bundle"]["entry"][0]["resource"]["status"] == "completed"

    audit_after = client.get("/api/v1/audit").json()
    unchanged_triage_event = next(
        event for event in audit_after if event["event_id"] == triage_event["event_id"]
    )
    assert unchanged_triage_event == triage_event
    assert any(
        event["case_id"] == case_id
        and event["action_type"] == "DUAL_KEY_CASE_CLOSURE"
        for event in audit_after
    )
    assert {
        event["action_type"]
        for event in audit_after
        if event["case_id"] == case_id
    } >= {
        "FHIR_SERVICEREQUEST_DISPATCHED",
        "URGENT_DHMT_SLA_ESCALATION",
        "PATIENT_ARRIVAL_CHECK_IN",
        "RECEIVING_HOSPITAL_DISCHARGE_SUMMARY_UPLOADED",
        "PRIMARY_CLINICIAN_SIGNOFF_RECORDED",
        "SECONDARY_CLINICIAN_SIGNOFF_RECORDED",
        "DUAL_KEY_CASE_CLOSURE"
    }
    assert any(
        event["case_id"] == case_id
        and event["action_type"] == "SERVICE_REQUEST_COMPLETED_ON_CASE_CLOSURE"
        for event in audit_after
    )
    chronological_events = list(reversed(audit_after))
    for index, event in enumerate(chronological_events):
        assert_audit_event_hash_valid(event)
        expected_previous_hash = (
            chronological_events[index - 1]["verification_hash"] if index else None
        )
        assert event["previous_hash"] == expected_previous_hash

def test_offline_sync_triages_queued_raw_notes_once():
    batch = {
        "device_id": "triage-sync-test-device",
        "synced_records": [{
            "queue_id": "triage-sync-test-queue-id",
            "record_type": "triage",
            "patient_national_id": "TRIAGE-SYNC-TEST-001",
            "patient_name": "Offline Triage Patient",
            "date_of_birth": "1990-03-03",
            "gender": "Female",
            "phone_number": "+26770000003",
            "consent_signed": True,
            "screening_type": "Tuberculosis Screen",
            "facility": "Mobile Unit",
            "raw_screening_notes": "Positive GeneXpert"
        }]
    }

    before_count = len(client.get("/api/v1/cases").json())
    before_referral_count = len(client.get("/api/v1/referrals").json())
    first_response = client.post("/api/v1/sync/queue", json=batch)
    second_response = client.post("/api/v1/sync/queue", json=batch)
    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json()["records_processed"] == 1
    assert second_response.json()["records_processed"] == 1
    assert len(client.get("/api/v1/cases").json()) == before_count + 1
    assert len(client.get("/api/v1/referrals").json()) == before_referral_count

def test_repeated_screening_uses_existing_patient_record():
    payload = {
        "patient_national_id": "REPEAT-TEST-001",
        "patient_name": "Repeat Test Patient",
        "date_of_birth": "1982-04-04",
        "gender": "Other",
        "phone_number": "+26770000004",
        "consent_signed": True,
        "screening_type": "General Screen",
        "screening_result_value": "Routine follow-up",
        "risk_level": "MODERATE"
    }

    first = client.post("/api/v1/screening/ingest", json=payload)
    second = client.post(
        "/api/v1/screening/ingest",
        json={**payload, "facility": "Gaborone Clinic"}
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["patient_id"] == second.json()["patient_id"]
    cases_by_id = {
        case["case_id"]: case
        for case in client.get("/api/v1/cases").json()
    }
    assert cases_by_id[first.json()["case_id"]]["facility"] == "Mobile Outreach"
    assert cases_by_id[second.json()["case_id"]]["facility"] == "Gaborone Clinic"


def test_consent_is_required_and_mpi_hash_normalizes_identifiers():
    response = client.post("/api/v1/screening/triage", json={
        "patient_national_id": "CONSENT-TEST-001",
        "patient_name": "Consent Test Patient",
        "date_of_birth": "1987-07-07",
        "gender": "Female",
        "phone_number": "+267 71-234-567",
        "consent_signed": False,
        "raw_screening_notes": "Routine screening"
    })
    assert response.status_code == 400
    assert "consent" in response.json()["detail"].lower()

    original_hash = patient_mpi_hash(
        "OMANG-1234",
        date.fromisoformat("1987-07-07"),
        "+267 71-234-567"
    )
    normalized_hash = patient_mpi_hash(
        "omang1234",
        date.fromisoformat("1987-07-07"),
        "26771234567"
    )
    local_phone_hash = patient_mpi_hash(
        "OMANG1234",
        date.fromisoformat("1987-07-07"),
        "071234567"
    )
    assert original_hash == normalized_hash
    assert original_hash == local_phone_hash


def test_sla_worker_logs_simulated_dhmt_webhook_once(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DHMT_WEBHOOK_URL", raising=False)
    response = client.post("/api/v1/screening/triage", json={
        "patient_national_id": "SLA-TEST-001",
        "patient_name": "SLA Test Patient",
        "date_of_birth": "1986-08-08",
        "gender": "Other",
        "phone_number": "+26770000005",
        "consent_signed": True,
        "screening_type": "General Screen",
        "facility": "Test Clinic",
        "raw_screening_notes": "Routine screening"
    })
    assert response.status_code == 201
    case_id = response.json()["case"]["case_id"]
    case = next(item for item in main.DB_CASES.values() if str(item["case_id"]) == case_id)
    case["sla_due_at"] = main.utc_now() + timedelta(minutes=90)

    before_attempts = len(main.DB_DHMT_WEBHOOK_LOG)
    asyncio.run(main._evaluate_memory_sla_cases())
    assert case["sla_escalation_alert"]["actor_name"] == "ScreenToCare SLA Scheduler"
    attempts = [
        item for item in main.DB_DHMT_WEBHOOK_LOG
        if item["case_id"] == case_id
    ]
    assert len(attempts) == 1
    assert attempts[0]["status"] == "SIMULATED"
    assert attempts[0]["destination"] == "dhmt-on-call"
    assert attempts[0]["channel"] == "sms"
    assert len(main.DB_DHMT_WEBHOOK_LOG) == before_attempts + 1
    asyncio.run(main._evaluate_memory_sla_cases())
    assert len([
        item for item in main.DB_DHMT_WEBHOOK_LOG
        if item["case_id"] == case_id
    ]) == 1


def test_hie_requires_configuration_and_dhis2_has_simulated_sink(monkeypatch):
    monkeypatch.delenv("HIE_FHIR_BASE_URL", raising=False)
    monkeypatch.delenv("DHIS2_BASE_URL", raising=False)
    triage = client.post("/api/v1/screening/triage", json={
        "patient_national_id": "HIE-TEST-001",
        "patient_name": "HIE Test Patient",
        "date_of_birth": "1989-09-09",
        "gender": "Female",
        "phone_number": "+26770000006",
        "consent_signed": True,
        "raw_screening_notes": "Routine screening"
    })
    case_id = triage.json()["case"]["case_id"]
    hie_response = client.post(f"/api/v1/integrations/hie/cases/{case_id}")
    assert hie_response.status_code == 503
    assert "HIE_FHIR_BASE_URL" in hie_response.json()["detail"]

    dhis2_response = client.post(
        "/api/v1/integrations/dhis2/monthly?year=2020&month=1"
    )
    assert dhis2_response.status_code == 200
    assert dhis2_response.json()["status"] == "SIMULATED"
    assert dhis2_response.json()["aggregate"]["period"] == "202001"
    assert client.get("/api/v1/integrations/dhis2/simulated").json()[-1] == dhis2_response.json()


def test_configured_hie_and_dhis2_connectors_send_expected_payloads(monkeypatch):
    class FakeResponse:
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"ok":true}'

    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse()

    monkeypatch.setattr(hie_connector, "urlopen", fake_urlopen)
    monkeypatch.setenv("HIE_FHIR_BASE_URL", "https://hie.example/fhir")
    monkeypatch.setenv("HIE_BEARER_TOKEN", "test-token")
    bundle = {"resourceType": "Bundle", "type": "collection", "entry": []}
    hie_result = hie_connector.push_fhir_bundle(bundle)
    assert hie_result["status_code"] == 201
    assert requests[0][0].full_url == "https://hie.example/fhir/Bundle"
    assert requests[0][0].get_header("Authorization") == "Bearer test-token"
    assert json.loads(requests[0][0].data) == bundle

    monkeypatch.setenv("DHIS2_BASE_URL", "https://dhis2.example")
    monkeypatch.setenv("DHIS2_ORG_UNIT", "ORG-001")
    monkeypatch.setenv("DHIS2_DATA_SET", "DATA-001")
    monkeypatch.setenv("DHIS2_SCREENINGS_DATA_ELEMENT", "SCREEN-001")
    monkeypatch.setenv("DHIS2_CLOSURES_DATA_ELEMENT", "CLOSE-001")
    dhis2_result = hie_connector.push_dhis2_aggregate({
        "period": "202611",
        "screenings": 20,
        "closures": 8
    })
    assert dhis2_result["status"] == "SENT"
    assert requests[1][0].full_url == "https://dhis2.example/api/dataValueSets"
    dhis2_payload = json.loads(requests[1][0].data)
    assert dhis2_payload["period"] == "202611"
    assert [item["value"] for item in dhis2_payload["dataValues"]] == ["20", "8"]


def test_patient_portal_lookup_supports_tracking_code_and_omang_with_dob_verification():
    triage = client.post("/api/v1/screening/triage", json={
        "patient_national_id": "PORTAL-TEST-001",
        "patient_name": "Portal Test Patient",
        "date_of_birth": "1987-07-07",
        "gender": "Female",
        "phone_number": "+26770000007",
        "consent_signed": True,
        "screening_type": "General Screen",
        "facility": "Gaborone Clinic",
        "raw_screening_notes": "Routine screening"
    })
    assert triage.status_code == 201
    case_id = triage.json()["case"]["case_id"]
    assert triage.json()["draft_patient_sms"]["status"] == "DRAFT"

    by_tracking_code = client.post("/api/v1/patient-portal/lookup", json={
        "identifier": case_id,
        "date_of_birth": "1987-07-07"
    })
    assert by_tracking_code.status_code == 200
    portal_record = by_tracking_code.json()
    assert portal_record["tracking_code"] == case_id
    assert portal_record["patient_first_name"] == "Portal"
    assert portal_record["status_text"] == "Screening received"
    assert portal_record["appointment_details"]["scheduled_at"] is None
    assert portal_record["next_steps"]
    assert "national_id" not in portal_record
    assert "phone_number" not in portal_record
    assert "screening_result_value" not in portal_record

    by_omang = client.post("/api/v1/patient-portal/lookup", json={
        "identifier": "portal test-001",
        "date_of_birth": "1987-07-07"
    })
    assert by_omang.status_code == 200
    assert by_omang.json()["tracking_code"] == case_id

    wrong_dob = client.post("/api/v1/patient-portal/lookup", json={
        "identifier": case_id,
        "date_of_birth": "1987-07-08"
    })
    assert wrong_dob.status_code == 404


def test_triage_preview_analyzes_notes_without_creating_a_case():
    cases_before = len(main.DB_CASES)
    audit_before = len(main.DB_AUDIT_LOG)
    examples = [
        ("Positive GeneXpert", "CRITICAL_RED_FLAG", 12),
        ("Stage 2 hypertension", "HIGH", 24),
        ("Routine screening", "MODERATE", 48)
    ]

    for notes, expected_risk, expected_sla in examples:
        response = client.post("/api/v1/screening/triage-preview", json={
            "screening_type": "Test Screening",
            "facility": "Test Clinic",
            "raw_screening_notes": notes
        })
        assert response.status_code == 200
        result = response.json()
        assert result["triage"]["risk_level"] == expected_risk
        assert result["triage"]["sla_hours"] == expected_sla
        assert result["draft_patient_sms"]["status"] == "DRAFT"
        assert "no message has been sent" in result["draft_patient_sms"]["message"]
        assert "case" not in result

    assert len(main.DB_CASES) == cases_before
    assert len(main.DB_AUDIT_LOG) == audit_before


def test_impact_metrics_calculate_turnaround_sla_referral_and_closure_rates():
    response = client.get("/api/v1/metrics/impact")
    assert response.status_code == 200
    metrics = response.json()

    persisted_cases = [
        case for case in main.DB_CASES.values()
        if case["case_status"] != "QUEUED_OFFLINE"
    ]
    active_cases = [case for case in persisted_cases if case["case_status"] != "CLOSED"]
    breached_cases = [
        case for case in active_cases
        if case["sla_due_at"] < main.utc_now() or case.get("is_overdue", False)
    ]
    closed_cases = [case for case in persisted_cases if case["case_status"] == "CLOSED"]
    turnaround_hours = [
        max(0, (main.DB_CLOSURES[case["case_id"]]["closed_at"] - case["created_at"]).total_seconds() / 3600)
        for case in closed_cases
        if case["case_id"] in main.DB_CLOSURES
    ]
    completed_referrals = sum(
        referral["referral_status"] == "COMPLETED"
        for referral in main.DB_REFERRALS.values()
    )

    assert metrics["total_cases"] == len(persisted_cases)
    assert metrics["closed_cases"] == len(closed_cases)
    assert metrics["active_sla_case_count"] == len(active_cases)
    assert metrics["active_sla_breached_cases"] == len(breached_cases)
    assert metrics["active_sla_breach_percent"] == (
        round(len(breached_cases) / len(active_cases) * 100, 1)
        if active_cases else 0
    )
    assert metrics["turnaround_sample_size"] == len(turnaround_hours)
    assert metrics["average_turnaround_hours"] == (
        round(sum(turnaround_hours) / len(turnaround_hours), 1)
        if turnaround_hours else None
    )
    assert metrics["total_referrals"] == len(main.DB_REFERRALS)
    assert metrics["completed_referrals"] == completed_referrals
    assert metrics["referral_completion_rate_percent"] == (
        round(completed_referrals / len(main.DB_REFERRALS) * 100, 1)
        if main.DB_REFERRALS else 0
    )
    assert metrics["closed_loop_conversion_percent"] == (
        round(len(closed_cases) / len(persisted_cases) * 100, 1)
        if persisted_cases else 0
    )
