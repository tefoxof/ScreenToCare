-- ScreenToCare PostgreSQL schema
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS clinician_users (
    user_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    full_name VARCHAR(150) NOT NULL,
    email VARCHAR(254) UNIQUE NOT NULL,
    clinical_role VARCHAR(100) NOT NULL,
    password_hash TEXT NOT NULL,
    account_status VARCHAR(20) NOT NULL DEFAULT 'APPROVED'
        CHECK (account_status IN ('PENDING', 'APPROVED')),
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    approved_at TIMESTAMP WITH TIME ZONE,
    approved_by UUID REFERENCES clinician_users(user_id)
);

ALTER TABLE clinician_users ALTER COLUMN account_status SET DEFAULT 'APPROVED';
UPDATE clinician_users SET account_status = 'APPROVED' WHERE account_status = 'PENDING';

CREATE TABLE patients (
    patient_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    national_id VARCHAR(50) UNIQUE NOT NULL,
    mpi_hash CHAR(64) NOT NULL,
    full_name VARCHAR(150) NOT NULL,
    date_of_birth DATE NOT NULL,
    gender VARCHAR(20) NOT NULL,
    phone_number VARCHAR(30) NOT NULL,
    preferred_channel VARCHAR(30) DEFAULT 'whatsapp',
    consent_signed BOOLEAN NOT NULL,
    consent_signed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE patients ADD COLUMN IF NOT EXISTS mpi_hash CHAR(64);
ALTER TABLE patients ADD COLUMN IF NOT EXISTS consent_signed BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE patients ADD COLUMN IF NOT EXISTS consent_signed_at TIMESTAMP WITH TIME ZONE;
WITH normalized_patients AS (
    SELECT patient_id, regexp_replace(phone_number, '[^0-9]', '', 'g') AS phone_digits
    FROM patients
)
UPDATE patients AS patient
SET mpi_hash = encode(
    digest(
        regexp_replace(lower(trim(patient.national_id)), '[^a-z0-9]', '', 'g') || '|' ||
        to_char(patient.date_of_birth, 'YYYY-MM-DD') || '|' ||
        CASE
            WHEN normalized.phone_digits LIKE '00%' THEN substring(normalized.phone_digits FROM 3)
            WHEN length(normalized.phone_digits) = 9 AND normalized.phone_digits LIKE '0%'
                THEN '267' || substring(normalized.phone_digits FROM 2)
            WHEN length(normalized.phone_digits) = 8 THEN '267' || normalized.phone_digits
            ELSE normalized.phone_digits
        END,
        'sha256'
    ),
    'hex'
)
FROM normalized_patients AS normalized
WHERE patient.patient_id = normalized.patient_id AND patient.mpi_hash IS NULL;
ALTER TABLE patients ALTER COLUMN mpi_hash SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_patients_mpi_hash ON patients(mpi_hash);

CREATE TABLE screening_cases (
    case_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    patient_id UUID NOT NULL REFERENCES patients(patient_id),
    current_owner_id UUID NOT NULL,
    risk_level VARCHAR(30) NOT NULL,
    case_status VARCHAR(50) NOT NULL DEFAULT 'RESULT_INGESTED'
        CHECK (case_status IN (
            'RESULT_INGESTED',
            'QUEUED_OFFLINE',
            'REFERRAL_DISPATCHED',
            'PATIENT_NOTIFIED',
            'ARRIVED_AT_FACILITY',
            'TREATMENT_COMPLETED',
            'CLOSED'
        )),
    sla_due_at TIMESTAMP WITH TIME ZONE NOT NULL,
    is_overdue BOOLEAN DEFAULT FALSE,
    sla_alerted_at TIMESTAMP WITH TIME ZONE,
    sla_alert_claimed_at TIMESTAMP WITH TIME ZONE,
    sla_alert_attempts INTEGER NOT NULL DEFAULT 0,
    sla_alert_error TEXT,
    case_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    screening_type VARCHAR(150) NOT NULL,
    screening_result_value TEXT NOT NULL,
    facility VARCHAR(150) NOT NULL,
    discharge_document_id VARCHAR(150),
    discharge_resource_id UUID,
    clinical_outcome_note TEXT,
    discharge_uploaded_by VARCHAR(150),
    discharge_uploaded_at TIMESTAMP WITH TIME ZONE,
    sla_escalation_alert JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE screening_cases ADD COLUMN IF NOT EXISTS sla_alerted_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE screening_cases ADD COLUMN IF NOT EXISTS sla_alert_claimed_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE screening_cases ADD COLUMN IF NOT EXISTS sla_alert_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE screening_cases ADD COLUMN IF NOT EXISTS sla_alert_error TEXT;
ALTER TABLE screening_cases ADD COLUMN IF NOT EXISTS case_payload JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE referrals (
    referral_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID NOT NULL REFERENCES screening_cases(case_id),
    service_request_id UUID UNIQUE NOT NULL,
    sending_facility VARCHAR(150) NOT NULL,
    receiving_facility VARCHAR(150) NOT NULL,
    referral_status VARCHAR(50) NOT NULL DEFAULT 'PENDING',
    fhir_service_request JSONB NOT NULL,
    referral_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    rejection_reason TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE referrals ADD COLUMN IF NOT EXISTS referral_payload JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE case_closures (
    closure_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID UNIQUE NOT NULL REFERENCES screening_cases(case_id),
    primary_clinician VARCHAR(150) NOT NULL,
    secondary_clinician VARCHAR(150) NOT NULL,
    clinical_evidence_doc_id VARCHAR(100) NOT NULL,
    primary_signature TEXT NOT NULL,
    secondary_signature TEXT NOT NULL,
    closed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CHECK (lower(primary_clinician) <> lower(secondary_clinician))
);

CREATE TABLE webhook_alerts (
    webhook_alert_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID NOT NULL REFERENCES screening_cases(case_id),
    channel VARCHAR(30) NOT NULL,
    destination VARCHAR(50) NOT NULL,
    payload JSONB NOT NULL,
    delivery_status VARCHAR(30) NOT NULL,
    response_summary TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE audit_timeline (
    audit_sequence BIGSERIAL NOT NULL,
    event_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID NOT NULL REFERENCES screening_cases(case_id),
    action_type VARCHAR(100) NOT NULL,
    new_state VARCHAR(50) NOT NULL,
    actor_id VARCHAR(150),
    actor_name VARCHAR(150) NOT NULL,
    fhir_resource_reference VARCHAR(255) NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    previous_hash CHAR(64),
    verification_hash CHAR(64) NOT NULL UNIQUE
);

ALTER TABLE audit_timeline ADD COLUMN IF NOT EXISTS audit_sequence BIGSERIAL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_audit_sequence ON audit_timeline(audit_sequence);

CREATE INDEX idx_cases_sla ON screening_cases(sla_due_at) WHERE case_status != 'CLOSED';
CREATE INDEX idx_cases_status ON screening_cases(case_status);
CREATE INDEX idx_referrals_status ON referrals(referral_status);
CREATE INDEX idx_audit_case_timestamp ON audit_timeline(case_id, timestamp DESC);
CREATE INDEX idx_webhook_case_timestamp ON webhook_alerts(case_id, created_at DESC);

CREATE FUNCTION prevent_audit_timeline_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit_timeline rows are immutable';
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_timeline_immutable
BEFORE UPDATE OR DELETE ON audit_timeline
FOR EACH ROW EXECUTE FUNCTION prevent_audit_timeline_mutation();

CREATE TRIGGER audit_timeline_no_truncate
BEFORE TRUNCATE ON audit_timeline
FOR EACH STATEMENT EXECUTE FUNCTION prevent_audit_timeline_mutation();
