-- =============================================================================
-- TRUSTOS — POSTGRESQL 18 SCHEMA, ROLES, SEQUENCES & ROW-LEVEL SECURITY (RLS)
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 1. Create Non-Superuser Application Role (NOSUPERUSER, NOBYPASSRLS)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'trustos_app') THEN
        CREATE ROLE trustos_app WITH LOGIN PASSWORD 'trustos_app_local_dev_pw' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
END
$$;

-- Helper functions to read transaction-scoped RLS context safely
CREATE OR REPLACE FUNCTION app_current_role() RETURNS text AS $$
    SELECT COALESCE(NULLIF(current_setting('app.current_role', true), ''), 'ANONYMOUS');
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION app_current_user_id() RETURNS uuid AS $$
    SELECT CASE
        WHEN NULLIF(current_setting('app.current_user_id', true), '') IS NULL THEN NULL
        ELSE current_setting('app.current_user_id', true)::uuid
    END;
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION app_current_campus_id() RETURNS uuid AS $$
    SELECT CASE
        WHEN NULLIF(current_setting('app.current_campus_id', true), '') IS NULL THEN NULL
        ELSE current_setting('app.current_campus_id', true)::uuid
    END;
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION app_current_student_id() RETURNS uuid AS $$
    SELECT CASE
        WHEN NULLIF(current_setting('app.current_student_id', true), '') IS NULL THEN NULL
        ELSE current_setting('app.current_student_id', true)::uuid
    END;
$$ LANGUAGE sql STABLE;

-- Sequences for collision-safe readable IDs and USNs
CREATE SEQUENCE IF NOT EXISTS seq_user_mgmt START 1001;
CREATE SEQUENCE IF NOT EXISTS seq_user_admin START 1001;
CREATE SEQUENCE IF NOT EXISTS seq_user_student START 10001;
CREATE SEQUENCE IF NOT EXISTS seq_user_parent START 10001;
CREATE SEQUENCE IF NOT EXISTS seq_user_warden START 1001;
CREATE SEQUENCE IF NOT EXISTS seq_receipt_no START 500001;
CREATE SEQUENCE IF NOT EXISTS seq_usn_c1 START 1;
CREATE SEQUENCE IF NOT EXISTS seq_usn_c2 START 1;
CREATE SEQUENCE IF NOT EXISTS seq_usn_c3 START 1;
CREATE SEQUENCE IF NOT EXISTS seq_usn_c4 START 1;
CREATE SEQUENCE IF NOT EXISTS seq_usn_c5 START 1;
CREATE SEQUENCE IF NOT EXISTS seq_usn_c6 START 1;

-- =============================================================================
-- GROUP 1: INSTITUTIONAL STRUCTURE
-- =============================================================================

CREATE TABLE IF NOT EXISTS trusts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL,
    code VARCHAR(50) UNIQUE NOT NULL,
    headquarters VARCHAR(200) NOT NULL,
    established_year INT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS campus_types (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code VARCHAR(50) UNIQUE NOT NULL, -- ENGINEERING, POLYTECHNIC, SCHOOL
    name VARCHAR(100) NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS campuses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trust_id UUID NOT NULL REFERENCES trusts(id) ON DELETE RESTRICT,
    campus_type_id UUID NOT NULL REFERENCES campus_types(id) ON DELETE RESTRICT,
    campus_number INT UNIQUE NOT NULL CHECK (campus_number BETWEEN 1 AND 6),
    code VARCHAR(30) UNIQUE NOT NULL,
    name VARCHAR(200) NOT NULL,
    city VARCHAR(100) NOT NULL,
    state VARCHAR(100) NOT NULL DEFAULT 'Karnataka',
    usn_prefix VARCHAR(20) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS academic_years (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code VARCHAR(20) UNIQUE NOT NULL, -- e.g. 2026-27
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    is_current BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS courses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campus_id UUID NOT NULL REFERENCES campuses(id) ON DELETE CASCADE,
    code VARCHAR(40) NOT NULL,
    name VARCHAR(150) NOT NULL,
    duration_years INT NOT NULL DEFAULT 4,
    total_semesters INT NOT NULL DEFAULT 8,
    max_intake INT NOT NULL DEFAULT 120,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (campus_id, code)
);

CREATE TABLE IF NOT EXISTS campus_policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campus_id UUID NOT NULL REFERENCES campuses(id) ON DELETE CASCADE,
    academic_year_id UUID NOT NULL REFERENCES academic_years(id) ON DELETE RESTRICT,
    version INT NOT NULL DEFAULT 1,
    attendance_threshold_pct NUMERIC(5,2) NOT NULL DEFAULT 75.00 CHECK (attendance_threshold_pct BETWEEN 0 AND 100),
    warning_threshold_pct NUMERIC(5,2) NOT NULL DEFAULT 80.00 CHECK (warning_threshold_pct BETWEEN 0 AND 100),
    late_fee_per_day NUMERIC(10,2) NOT NULL DEFAULT 50.00 CHECK (late_fee_per_day >= 0),
    grace_period_days INT NOT NULL DEFAULT 10,
    max_concession_pct NUMERIC(5,2) NOT NULL DEFAULT 50.00,
    transfer_min_attendance_pct NUMERIC(5,2) NOT NULL DEFAULT 65.00,
    require_zero_dues_for_transfer BOOLEAN NOT NULL DEFAULT FALSE,
    hostel_max_distance_priority_km INT NOT NULL DEFAULT 25,
    policy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    effective_from DATE NOT NULL DEFAULT CURRENT_DATE,
    effective_to DATE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    updated_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (campus_id, academic_year_id, version)
);

-- =============================================================================
-- GROUP 2: PERMANENT STUDENT IDENTITY & USER ACCOUNTS
-- =============================================================================

CREATE TABLE IF NOT EXISTS students (
    student_id UUID PRIMARY KEY DEFAULT gen_random_uuid(), -- PERMANENT CANONICAL TRUST-WIDE ID
    full_name VARCHAR(200) NOT NULL,
    normalized_name VARCHAR(200) NOT NULL,
    date_of_birth DATE NOT NULL,
    gender VARCHAR(20) NOT NULL,
    is_minor BOOLEAN NOT NULL DEFAULT FALSE,
    blood_group VARCHAR(10),
    email VARCHAR(200),
    phone VARCHAR(30),
    guardian_name VARCHAR(200),
    guardian_phone VARCHAR(30),
    guardian_email VARCHAR(200),
    guardian_relation VARCHAR(50) DEFAULT 'Parent',
    guardian_verified BOOLEAN NOT NULL DEFAULT TRUE,
    category VARCHAR(40) NOT NULL DEFAULT 'GENERAL',
    primary_campus_id UUID NOT NULL REFERENCES campuses(id),
    current_usn VARCHAR(50) UNIQUE NOT NULL,
    data_origin VARCHAR(30) NOT NULL DEFAULT 'SYNTHETIC', -- SYNTHETIC, SOURCE_DERIVED, TRANSFORMED, INFERRED
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_students_primary_campus ON students(primary_campus_id);
CREATE INDEX IF NOT EXISTS idx_students_norm_name_dob ON students(normalized_name, date_of_birth);
CREATE INDEX IF NOT EXISTS idx_students_current_usn ON students(current_usn);

CREATE TABLE IF NOT EXISTS student_identifiers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id UUID NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
    campus_id UUID REFERENCES campuses(id),
    id_type VARCHAR(40) NOT NULL, -- USN, ADMISSION_NO, ROLL_NO, LEGACY_SHEET_ID
    id_value VARCHAR(80) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deactivated_at TIMESTAMPTZ,
    notes TEXT,
    UNIQUE (id_type, id_value)
);
CREATE INDEX IF NOT EXISTS idx_student_identifiers_student ON student_identifiers(student_id);
CREATE INDEX IF NOT EXISTS idx_student_identifiers_value ON student_identifiers(id_value);

CREATE TABLE IF NOT EXISTS student_source_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id UUID REFERENCES students(student_id) ON DELETE SET NULL,
    campus_id UUID REFERENCES campuses(id),
    source_system VARCHAR(100) NOT NULL,
    source_file VARCHAR(200) NOT NULL,
    source_row_hash VARCHAR(64) UNIQUE NOT NULL,
    raw_payload JSONB NOT NULL,
    data_origin VARCHAR(30) NOT NULL DEFAULT 'SOURCE_DERIVED',
    imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    display_user_id VARCHAR(30) UNIQUE NOT NULL, -- M..., A..., S..., P..., W...
    full_name VARCHAR(200) NOT NULL,
    email VARCHAR(200) UNIQUE NOT NULL,
    phone VARCHAR(30),
    password_hash VARCHAR(255) NOT NULL,
    role_code VARCHAR(40) NOT NULL CHECK (role_code IN ('TRUST_MANAGEMENT', 'COLLEGE_ADMIN', 'STUDENT', 'PARENT', 'HOSTEL_WARDEN')),
    status VARCHAR(30) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('PENDING', 'ACTIVE', 'REJECTED', 'SUSPENDED')),
    primary_campus_id UUID REFERENCES campuses(id),
    linked_student_id UUID REFERENCES students(student_id),
    failed_login_attempts INT NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ,
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_code VARCHAR(40) NOT NULL,
    granted_by UUID REFERENCES users(id),
    granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, role_code)
);

CREATE TABLE IF NOT EXISTS user_campus_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    campus_id UUID NOT NULL REFERENCES campuses(id) ON DELETE CASCADE,
    is_primary BOOLEAN NOT NULL DEFAULT TRUE,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, campus_id)
);

CREATE TABLE IF NOT EXISTS parent_student_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    student_id UUID NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
    relationship VARCHAR(40) NOT NULL DEFAULT 'Parent',
    is_verified BOOLEAN NOT NULL DEFAULT TRUE,
    verified_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (parent_user_id, student_id)
);
CREATE INDEX IF NOT EXISTS idx_parent_links_parent ON parent_student_links(parent_user_id);
CREATE INDEX IF NOT EXISTS idx_parent_links_student ON parent_student_links(student_id);

CREATE TABLE IF NOT EXISTS registration_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    requested_role VARCHAR(40) NOT NULL CHECK (requested_role IN ('TRUST_MANAGEMENT', 'COLLEGE_ADMIN', 'STUDENT', 'PARENT', 'HOSTEL_WARDEN')),
    full_name VARCHAR(200) NOT NULL,
    email VARCHAR(200) NOT NULL,
    phone VARCHAR(30),
    campus_id UUID REFERENCES campuses(id),
    verification_usn VARCHAR(50),
    linked_student_id UUID REFERENCES students(student_id),
    password_hash VARCHAR(255) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED', 'SUSPENDED')),
    generated_user_id VARCHAR(30),
    reviewed_by UUID REFERENCES users(id),
    review_notes TEXT,
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- GROUP 3: ADMISSIONS & CAMPUS TRANSFERS
-- =============================================================================

CREATE TABLE IF NOT EXISTS admissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id UUID NOT NULL REFERENCES students(student_id) ON DELETE RESTRICT,
    campus_id UUID NOT NULL REFERENCES campuses(id) ON DELETE RESTRICT,
    course_id UUID NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    academic_year_id UUID NOT NULL REFERENCES academic_years(id) ON DELETE RESTRICT,
    admission_number VARCHAR(60) UNIQUE NOT NULL,
    admission_date DATE NOT NULL DEFAULT CURRENT_DATE,
    quota VARCHAR(40) NOT NULL DEFAULT 'MERIT', -- MERIT, GOVERNMENT, MANAGEMENT, RTE
    status VARCHAR(30) NOT NULL DEFAULT 'CONFIRMED',
    admitted_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS campus_enrollments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id UUID NOT NULL REFERENCES students(student_id) ON DELETE RESTRICT,
    campus_id UUID NOT NULL REFERENCES campuses(id) ON DELETE RESTRICT,
    course_id UUID NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    academic_year_id UUID NOT NULL REFERENCES academic_years(id) ON DELETE RESTRICT,
    usn VARCHAR(50) UNIQUE NOT NULL,
    year_of_study INT NOT NULL DEFAULT 1,
    section VARCHAR(10) NOT NULL DEFAULT 'A',
    status VARCHAR(30) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'TRANSFERRED', 'GRADUATED', 'DROPPED')),
    enrolled_at DATE NOT NULL DEFAULT CURRENT_DATE,
    ended_at DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_enrollments_campus_status ON campus_enrollments(campus_id, status);
CREATE INDEX IF NOT EXISTS idx_enrollments_student ON campus_enrollments(student_id);

CREATE TABLE IF NOT EXISTS transfer_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id UUID NOT NULL REFERENCES students(student_id) ON DELETE RESTRICT,
    source_campus_id UUID NOT NULL REFERENCES campuses(id),
    destination_campus_id UUID NOT NULL REFERENCES campuses(id),
    source_course_id UUID NOT NULL REFERENCES courses(id),
    destination_course_id UUID NOT NULL REFERENCES courses(id),
    source_usn VARCHAR(50) NOT NULL,
    proposed_destination_usn VARCHAR(50) NOT NULL,
    reason TEXT NOT NULL,
    eligibility_check_passed BOOLEAN NOT NULL DEFAULT TRUE,
    eligibility_notes TEXT,
    outstanding_balance_at_request NUMERIC(12,2) NOT NULL DEFAULT 0.00,
    hostel_Action VARCHAR(40) NOT NULL DEFAULT 'RELEASE_ON_TRANSFER',
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED', 'COMPLETED')),
    requested_by UUID REFERENCES users(id),
    approved_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    CHECK (source_campus_id <> destination_campus_id)
);

CREATE TABLE IF NOT EXISTS transfer_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transfer_request_id UUID NOT NULL REFERENCES transfer_requests(id) ON DELETE RESTRICT,
    student_id UUID NOT NULL REFERENCES students(student_id) ON DELETE RESTRICT,
    old_campus_id UUID NOT NULL REFERENCES campuses(id),
    new_campus_id UUID NOT NULL REFERENCES campuses(id),
    old_usn VARCHAR(50) NOT NULL,
    new_usn VARCHAR(50) NOT NULL,
    old_enrollment_id UUID NOT NULL REFERENCES campus_enrollments(id),
    new_enrollment_id UUID NOT NULL REFERENCES campus_enrollments(id),
    financial_treatment VARCHAR(100) NOT NULL DEFAULT 'CARRY_FORWARD_AND_AUDIT',
    hostel_released BOOLEAN NOT NULL DEFAULT FALSE,
    transferred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    authorized_by UUID REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS transfer_approvals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transfer_request_id UUID NOT NULL REFERENCES transfer_requests(id) ON DELETE CASCADE,
    approver_user_id UUID REFERENCES users(id),
    approval_level VARCHAR(40) NOT NULL, -- SOURCE_CAMPUS, DESTINATION_CAMPUS, TRUST_MANAGEMENT
    decision VARCHAR(20) NOT NULL CHECK (decision IN ('APPROVED', 'REJECTED')),
    comments TEXT,
    decided_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- GROUP 4: FEES, TWO-LEVEL VERIFICATION & IMMUTABLE RECEIPTS
-- =============================================================================

CREATE TABLE IF NOT EXISTS fee_heads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code VARCHAR(40) UNIQUE NOT NULL, -- TUITION, LAB, LIBRARY, EXAM, DEVELOPMENT, BUS, UNIFORM
    name VARCHAR(100) NOT NULL,
    is_refundable BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS fee_structures (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campus_id UUID NOT NULL REFERENCES campuses(id) ON DELETE CASCADE,
    course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    academic_year_id UUID NOT NULL REFERENCES academic_years(id) ON DELETE RESTRICT,
    year_of_study INT NOT NULL DEFAULT 1,
    total_amount NUMERIC(12,2) NOT NULL CHECK (total_amount >= 0),
    due_date DATE NOT NULL,
    breakdown_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (campus_id, course_id, academic_year_id, year_of_study)
);

CREATE TABLE IF NOT EXISTS student_fee_assessments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id UUID NOT NULL REFERENCES students(student_id) ON DELETE RESTRICT,
    campus_id UUID NOT NULL REFERENCES campuses(id) ON DELETE RESTRICT,
    enrollment_id UUID REFERENCES campus_enrollments(id),
    academic_year_id UUID NOT NULL REFERENCES academic_years(id),
    fee_structure_id UUID REFERENCES fee_structures(id),
    assessed_amount NUMERIC(12,2) NOT NULL CHECK (assessed_amount >= 0),
    concession_amount NUMERIC(12,2) NOT NULL DEFAULT 0.00 CHECK (concession_amount >= 0),
    scholarship_amount NUMERIC(12,2) NOT NULL DEFAULT 0.00 CHECK (scholarship_amount >= 0),
    adjustments_amount NUMERIC(12,2) NOT NULL DEFAULT 0.00, -- positive = extra charge/late fee, negative = credit adjustment
    net_posted_payments NUMERIC(12,2) NOT NULL DEFAULT 0.00 CHECK (net_posted_payments >= 0),
    refunded_amount NUMERIC(12,2) NOT NULL DEFAULT 0.00 CHECK (refunded_amount >= 0),
    outstanding_balance NUMERIC(12,2) NOT NULL DEFAULT 0.00,
    due_date DATE NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PAID', 'PARTIAL', 'PENDING', 'OVERDUE', 'OVERPAID')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fee_assessments_campus ON student_fee_assessments(campus_id, status);
CREATE INDEX IF NOT EXISTS idx_fee_assessments_student ON student_fee_assessments(student_id);

CREATE TABLE IF NOT EXISTS fee_assessment_lines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    assessment_id UUID NOT NULL REFERENCES student_fee_assessments(id) ON DELETE CASCADE,
    fee_head_id UUID NOT NULL REFERENCES fee_heads(id),
    amount NUMERIC(12,2) NOT NULL CHECK (amount >= 0)
);

CREATE TABLE IF NOT EXISTS concessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    assessment_id UUID NOT NULL REFERENCES student_fee_assessments(id) ON DELETE CASCADE,
    student_id UUID NOT NULL REFERENCES students(student_id),
    campus_id UUID NOT NULL REFERENCES campuses(id),
    concession_type VARCHAR(60) NOT NULL, -- MERIT_WAIVER, SIBLING_DISCOUNT, STAFF_WARD, EWS_CONCESSION
    amount NUMERIC(12,2) NOT NULL CHECK (amount > 0),
    status VARCHAR(20) NOT NULL DEFAULT 'APPROVED' CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
    approved_by UUID REFERENCES users(id),
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS scholarships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    assessment_id UUID NOT NULL REFERENCES student_fee_assessments(id) ON DELETE CASCADE,
    student_id UUID NOT NULL REFERENCES students(student_id),
    campus_id UUID NOT NULL REFERENCES campuses(id),
    scheme_name VARCHAR(120) NOT NULL,
    amount NUMERIC(12,2) NOT NULL CHECK (amount > 0),
    status VARCHAR(20) NOT NULL DEFAULT 'APPROVED' CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    assessment_id UUID NOT NULL REFERENCES student_fee_assessments(id) ON DELETE RESTRICT,
    student_id UUID NOT NULL REFERENCES students(student_id) ON DELETE RESTRICT,
    campus_id UUID NOT NULL REFERENCES campuses(id) ON DELETE RESTRICT,
    transaction_ref VARCHAR(80) UNIQUE NOT NULL,
    receipt_number VARCHAR(50) UNIQUE,
    amount NUMERIC(12,2) NOT NULL CHECK (amount > 0),
    payment_mode VARCHAR(30) NOT NULL DEFAULT 'UPI_SIMULATED', -- UPI_SIMULATED, NEFT_SIMULATED, DD, CARD_SIMULATED
    status VARCHAR(40) NOT NULL DEFAULT 'PENDING_COLLEGE_VERIFICATION'
        CHECK (status IN ('PENDING_COLLEGE_VERIFICATION', 'COLLEGE_VERIFIED', 'POSTED', 'FAILED', 'REVERSED')),
    college_verified_by UUID REFERENCES users(id),
    college_verified_at TIMESTAMPTZ,
    trust_verified_by UUID REFERENCES users(id),
    trust_verified_at TIMESTAMPTZ,
    posted_at TIMESTAMPTZ,
    is_synthetic BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_payments_campus_status ON payments(campus_id, status);
CREATE INDEX IF NOT EXISTS idx_payments_student ON payments(student_id);

CREATE TABLE IF NOT EXISTS payment_allocations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payment_id UUID NOT NULL REFERENCES payments(id) ON DELETE CASCADE,
    assessment_id UUID NOT NULL REFERENCES student_fee_assessments(id) ON DELETE CASCADE,
    allocated_amount NUMERIC(12,2) NOT NULL CHECK (allocated_amount > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS refunds (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payment_id UUID NOT NULL REFERENCES payments(id) ON DELETE RESTRICT,
    assessment_id UUID NOT NULL REFERENCES student_fee_assessments(id) ON DELETE RESTRICT,
    student_id UUID NOT NULL REFERENCES students(student_id),
    campus_id UUID NOT NULL REFERENCES campuses(id),
    refund_ref VARCHAR(80) UNIQUE NOT NULL,
    amount NUMERIC(12,2) NOT NULL CHECK (amount > 0),
    reason TEXT NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'COMPLETED' CHECK (status IN ('PENDING', 'COMPLETED', 'REJECTED')),
    approved_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS financial_adjustments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    assessment_id UUID NOT NULL REFERENCES student_fee_assessments(id) ON DELETE RESTRICT,
    student_id UUID NOT NULL REFERENCES students(student_id),
    campus_id UUID NOT NULL REFERENCES campuses(id),
    linked_payment_id UUID REFERENCES payments(id),
    adjustment_type VARCHAR(40) NOT NULL CHECK (adjustment_type IN ('LATE_FEE', 'REVERSAL_DEBIT', 'FEE_CORRECTION_CREDIT', 'FEE_CORRECTION_DEBIT')),
    amount NUMERIC(12,2) NOT NULL, -- signed or positive with type
    reason TEXT NOT NULL,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS financial_audit_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campus_id UUID REFERENCES campuses(id),
    student_id UUID REFERENCES students(student_id),
    assessment_id UUID REFERENCES student_fee_assessments(id),
    payment_id UUID REFERENCES payments(id),
    event_type VARCHAR(60) NOT NULL,
    amount NUMERIC(12,2),
    previous_balance NUMERIC(12,2),
    new_balance NUMERIC(12,2),
    actor_user_id UUID REFERENCES users(id),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- IMMUTABILITY TRIGGER FOR POSTED PAYMENTS
-- =============================================================================
CREATE OR REPLACE FUNCTION enforce_posted_payment_immutability()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status = 'POSTED' THEN
            RAISE EXCEPTION 'Immutable financial ledger violation: POSTED payments cannot be deleted. Use a linked reversal or refund.';
        END IF;
        RETURN OLD;
    ELSIF TG_OP = 'UPDATE' THEN
        IF OLD.status = 'POSTED' THEN
            -- Only allow status transition from POSTED -> REVERSED; never allow modifying amount, receipt_number, student_id, or transaction_ref
            IF NEW.amount <> OLD.amount OR NEW.transaction_ref <> OLD.transaction_ref OR NEW.student_id <> OLD.student_id OR COALESCE(NEW.receipt_number, '') <> COALESCE(OLD.receipt_number, '') THEN
                RAISE EXCEPTION 'Immutable financial ledger violation: Cannot modify amount, receipt number, student, or reference of a POSTED payment.';
            END IF;
            IF NEW.status <> 'POSTED' AND NEW.status <> 'REVERSED' THEN
                RAISE EXCEPTION 'Immutable financial ledger violation: A POSTED payment can only transition to REVERSED via an audited reversal entry.';
            END IF;
        END IF;
        RETURN NEW;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_posted_payment_immutability ON payments;
CREATE TRIGGER trg_posted_payment_immutability
BEFORE UPDATE OR DELETE ON payments
FOR EACH ROW EXECUTE FUNCTION enforce_posted_payment_immutability();

-- =============================================================================
-- LEDGER BALANCE RECALCULATION FUNCTION
-- Formula:
-- Outstanding = assessed_amount + adjustments_amount - concession_amount - scholarship_amount - (posted_payments - completed_refunds)
-- =============================================================================
CREATE OR REPLACE FUNCTION recalculate_assessment_balance(p_assessment_id UUID)
RETURNS VOID AS $$
DECLARE
    v_assessed NUMERIC(12,2);
    v_concessions NUMERIC(12,2);
    v_scholarships NUMERIC(12,2);
    v_adjustments NUMERIC(12,2);
    v_posted_payments NUMERIC(12,2);
    v_refunds NUMERIC(12,2);
    v_net_paid NUMERIC(12,2);
    v_outstanding NUMERIC(12,2);
    v_due_date DATE;
    v_status VARCHAR(30);
BEGIN
    SELECT assessed_amount, due_date INTO v_assessed, v_due_date
    FROM student_fee_assessments WHERE id = p_assessment_id;

    SELECT COALESCE(SUM(amount), 0.00) INTO v_concessions
    FROM concessions WHERE assessment_id = p_assessment_id AND status = 'APPROVED';

    SELECT COALESCE(SUM(amount), 0.00) INTO v_scholarships
    FROM scholarships WHERE assessment_id = p_assessment_id AND status = 'APPROVED';

    SELECT COALESCE(SUM(
        CASE
            WHEN adjustment_type IN ('LATE_FEE', 'REVERSAL_DEBIT', 'FEE_CORRECTION_DEBIT') THEN ABS(amount)
            WHEN adjustment_type IN ('FEE_CORRECTION_CREDIT') THEN -ABS(amount)
            ELSE amount
        END
    ), 0.00) INTO v_adjustments
    FROM financial_adjustments
    WHERE assessment_id = p_assessment_id AND adjustment_type <> 'REVERSAL_DEBIT';

    -- Posted payments (excluding REVERSED, FAILED, PENDING)
    SELECT COALESCE(SUM(amount), 0.00) INTO v_posted_payments
    FROM payments WHERE assessment_id = p_assessment_id AND status = 'POSTED';

    -- Completed refunds linked to payments of this assessment
    SELECT COALESCE(SUM(amount), 0.00) INTO v_refunds
    FROM refunds WHERE assessment_id = p_assessment_id AND status = 'COMPLETED';

    v_net_paid := GREATEST(v_posted_payments - v_refunds, 0.00);
    v_outstanding := v_assessed + v_adjustments - v_concessions - v_scholarships - v_net_paid;

    IF v_outstanding < 0 THEN
        v_status := 'OVERPAID';
    ELSIF v_outstanding = 0 THEN
        v_status := 'PAID';
    ELSIF v_net_paid > 0 THEN
        v_status := 'PARTIAL';
    ELSIF v_due_date < CURRENT_DATE THEN
        v_status := 'OVERDUE';
    ELSE
        v_status := 'PENDING';
    END IF;

    UPDATE student_fee_assessments
    SET concession_amount = v_concessions,
        scholarship_amount = v_scholarships,
        adjustments_amount = v_adjustments,
        net_posted_payments = v_net_paid,
        refunded_amount = v_refunds,
        outstanding_balance = v_outstanding,
        status = v_status,
        updated_at = NOW()
    WHERE id = p_assessment_id;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- GROUP 5: HOSTEL INVENTORY & BED ALLOCATIONS
-- =============================================================================

CREATE TABLE IF NOT EXISTS hostel_buildings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campus_id UUID NOT NULL REFERENCES campuses(id) ON DELETE CASCADE,
    code VARCHAR(30) NOT NULL,
    name VARCHAR(120) NOT NULL,
    gender_type VARCHAR(20) NOT NULL DEFAULT 'BOYS', -- BOYS, GIRLS
    total_floors INT NOT NULL DEFAULT 3,
    warden_user_id UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (campus_id, code)
);

CREATE TABLE IF NOT EXISTS hostel_rooms (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    building_id UUID NOT NULL REFERENCES hostel_buildings(id) ON DELETE CASCADE,
    campus_id UUID NOT NULL REFERENCES campuses(id) ON DELETE CASCADE,
    room_number VARCHAR(20) NOT NULL,
    floor_number INT NOT NULL DEFAULT 1,
    room_type VARCHAR(30) NOT NULL DEFAULT 'STANDARD_4_SHARE', -- SINGLE, DOUBLE, STANDARD_4_SHARE
    capacity INT NOT NULL DEFAULT 4 CHECK (capacity BETWEEN 1 AND 8),
    annual_fee NUMERIC(10,2) NOT NULL DEFAULT 45000.00,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (building_id, room_number)
);

CREATE TABLE IF NOT EXISTS hostel_beds (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id UUID NOT NULL REFERENCES hostel_rooms(id) ON DELETE CASCADE,
    building_id UUID NOT NULL REFERENCES hostel_buildings(id) ON DELETE CASCADE,
    campus_id UUID NOT NULL REFERENCES campuses(id) ON DELETE CASCADE,
    bed_code VARCHAR(30) NOT NULL, -- e.g. 101-A, 101-B
    status VARCHAR(30) NOT NULL DEFAULT 'AVAILABLE'
        CHECK (status IN ('AVAILABLE', 'OCCUPIED', 'RESERVED', 'OUT_OF_SERVICE')),
    current_student_id UUID UNIQUE REFERENCES students(student_id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (room_id, bed_code)
);
CREATE INDEX IF NOT EXISTS idx_hostel_beds_campus_status ON hostel_beds(campus_id, status);

CREATE TABLE IF NOT EXISTS hostel_allocations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bed_id UUID NOT NULL REFERENCES hostel_beds(id) ON DELETE RESTRICT,
    room_id UUID NOT NULL REFERENCES hostel_rooms(id) ON DELETE RESTRICT,
    building_id UUID NOT NULL REFERENCES hostel_buildings(id) ON DELETE RESTRICT,
    campus_id UUID NOT NULL REFERENCES campuses(id) ON DELETE RESTRICT,
    student_id UUID NOT NULL REFERENCES students(student_id) ON DELETE RESTRICT,
    academic_year_id UUID NOT NULL REFERENCES academic_years(id),
    allocation_status VARCHAR(30) NOT NULL DEFAULT 'ACTIVE'
        CHECK (allocation_status IN ('RESERVED', 'ACTIVE', 'RELEASED', 'CANCELLED')),
    allocated_by UUID REFERENCES users(id),
    allocated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    released_at TIMESTAMPTZ,
    release_reason TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_active_bed_allocation ON hostel_allocations(bed_id) WHERE (allocation_status IN ('ACTIVE', 'RESERVED'));
CREATE UNIQUE INDEX IF NOT EXISTS uq_active_student_hostel ON hostel_allocations(student_id) WHERE (allocation_status IN ('ACTIVE', 'RESERVED'));

CREATE TABLE IF NOT EXISTS hostel_allocation_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    allocation_id UUID REFERENCES hostel_allocations(id),
    bed_id UUID NOT NULL REFERENCES hostel_beds(id),
    student_id UUID NOT NULL REFERENCES students(student_id),
    campus_id UUID NOT NULL REFERENCES campuses(id),
    action VARCHAR(40) NOT NULL, -- ALLOCATED, RESERVED, RELEASED, AUTO_RELEASED_ON_TRANSFER
    actor_user_id UUID REFERENCES users(id),
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- GROUP 6: ATTENDANCE, ELIGIBILITY & EXAMINATION RESULTS
-- =============================================================================

CREATE TABLE IF NOT EXISTS subjects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campus_id UUID NOT NULL REFERENCES campuses(id) ON DELETE CASCADE,
    course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    code VARCHAR(30) NOT NULL,
    name VARCHAR(150) NOT NULL,
    semester INT NOT NULL DEFAULT 1,
    credits INT NOT NULL DEFAULT 4,
    UNIQUE (campus_id, course_id, code)
);

CREATE TABLE IF NOT EXISTS attendance_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campus_id UUID NOT NULL REFERENCES campuses(id) ON DELETE CASCADE,
    course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    subject_id UUID NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    academic_year_id UUID NOT NULL REFERENCES academic_years(id),
    session_date DATE NOT NULL,
    classes_conducted INT NOT NULL DEFAULT 1 CHECK (classes_conducted > 0),
    weight NUMERIC(4,2) NOT NULL DEFAULT 1.00,
    topic VARCHAR(200),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS attendance_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES attendance_sessions(id) ON DELETE CASCADE,
    student_id UUID NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
    campus_id UUID NOT NULL REFERENCES campuses(id) ON DELETE CASCADE,
    subject_id UUID NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    classes_attended INT NOT NULL DEFAULT 1 CHECK (classes_attended >= 0),
    classes_eligible INT NOT NULL DEFAULT 1 CHECK (classes_eligible >= 0),
    status VARCHAR(20) NOT NULL DEFAULT 'PRESENT' CHECK (status IN ('PRESENT', 'ABSENT', 'EXCUSED')),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (session_id, student_id)
);
CREATE INDEX IF NOT EXISTS idx_attendance_records_student ON attendance_records(student_id);
CREATE INDEX IF NOT EXISTS idx_attendance_records_campus ON attendance_records(campus_id);

CREATE TABLE IF NOT EXISTS examination_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id UUID NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
    campus_id UUID NOT NULL REFERENCES campuses(id) ON DELETE CASCADE,
    subject_id UUID NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    academic_year_id UUID NOT NULL REFERENCES academic_years(id),
    exam_term VARCHAR(50) NOT NULL, -- TERM_1, MIDTERM, FINAL_SEM_1, FINAL_SEM_2
    max_marks NUMERIC(6,2) NOT NULL DEFAULT 100.00,
    marks_obtained NUMERIC(6,2) NOT NULL CHECK (marks_obtained >= 0),
    grade VARCHAR(5) NOT NULL,
    passed BOOLEAN NOT NULL DEFAULT TRUE,
    is_synthetic BOOLEAN NOT NULL DEFAULT TRUE,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS academic_progress_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id UUID NOT NULL UNIQUE REFERENCES students(student_id) ON DELETE CASCADE,
    campus_id UUID NOT NULL REFERENCES campuses(id) ON DELETE CASCADE,
    course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    academic_year_id UUID NOT NULL REFERENCES academic_years(id),
    total_classes_held INT NOT NULL DEFAULT 0,
    total_classes_attended INT NOT NULL DEFAULT 0,
    attendance_percentage NUMERIC(5,2), -- NULL if 0 eligible classes or missing attendance
    applicable_threshold_pct NUMERIC(5,2) NOT NULL DEFAULT 75.00,
    eligibility_status VARCHAR(30) NOT NULL DEFAULT 'ELIGIBLE'
        CHECK (eligibility_status IN ('ELIGIBLE', 'AT_RISK', 'INELIGIBLE', 'NO_DATA')),
    cgpa NUMERIC(4,2) DEFAULT 8.00,
    sgpa_term1 NUMERIC(4,2) DEFAULT 7.80,
    sgpa_term2 NUMERIC(4,2) DEFAULT 8.20,
    backlogs INT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_academic_progress_campus_elig ON academic_progress_records(campus_id, eligibility_status);

-- =============================================================================
-- GROUP 7: SCHOLARSHIPS & GOVERNMENT REIMBURSEMENTS
-- =============================================================================

CREATE TABLE IF NOT EXISTS scholarship_schemes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scheme_code VARCHAR(40) UNIQUE NOT NULL, -- SSP_POST_MATRIC, NSP_MERIT, AICTE_PRAGATI, RTE_REIMBURSEMENT
    name VARCHAR(200) NOT NULL,
    sponsoring_agency VARCHAR(150) NOT NULL,
    max_annual_amount NUMERIC(12,2) NOT NULL,
    required_fields_json JSONB NOT NULL DEFAULT '["usn", "category", "income_certificate_no", "bank_ifsc"]'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS scholarship_applications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id UUID NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
    campus_id UUID NOT NULL REFERENCES campuses(id) ON DELETE CASCADE,
    scheme_id UUID NOT NULL REFERENCES scholarship_schemes(id),
    academic_year_id UUID NOT NULL REFERENCES academic_years(id),
    application_no VARCHAR(60) UNIQUE NOT NULL,
    annual_family_income NUMERIC(12,2) NOT NULL DEFAULT 180000.00,
    income_cert_no VARCHAR(60),
    bank_account_masked VARCHAR(40),
    status VARCHAR(30) NOT NULL DEFAULT 'SUBMITTED'
        CHECK (status IN ('DRAFT', 'SUBMITTED', 'VERIFIED', 'SANCTIONED', 'DISBURSED', 'REJECTED')),
    missing_fields_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_synthetic BOOLEAN NOT NULL DEFAULT TRUE,
    submitted_at DATE NOT NULL DEFAULT CURRENT_DATE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS scholarship_awards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id UUID NOT NULL REFERENCES scholarship_applications(id) ON DELETE CASCADE,
    student_id UUID NOT NULL REFERENCES students(student_id),
    campus_id UUID NOT NULL REFERENCES campuses(id),
    sanctioned_amount NUMERIC(12,2) NOT NULL,
    disbursed_amount NUMERIC(12,2) NOT NULL DEFAULT 0.00,
    awarded_at DATE NOT NULL DEFAULT CURRENT_DATE
);

CREATE TABLE IF NOT EXISTS government_reimbursement_claims (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id UUID REFERENCES scholarship_applications(id),
    student_id UUID NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
    campus_id UUID NOT NULL REFERENCES campuses(id) ON DELETE CASCADE,
    scheme_id UUID NOT NULL REFERENCES scholarship_schemes(id),
    academic_year_id UUID NOT NULL REFERENCES academic_years(id),
    claim_reference VARCHAR(60) UNIQUE NOT NULL,
    sanctioned_amount NUMERIC(12,2) NOT NULL DEFAULT 0.00,
    approved_amount NUMERIC(12,2) NOT NULL DEFAULT 0.00,
    claimed_amount NUMERIC(12,2) NOT NULL CHECK (claimed_amount >= 0),
    disbursed_amount NUMERIC(12,2) NOT NULL DEFAULT 0.00 CHECK (disbursed_amount >= 0),
    pending_amount NUMERIC(12,2) NOT NULL DEFAULT 0.00,
    claim_status VARCHAR(40) NOT NULL DEFAULT 'PENDING_STATE_APPROVAL'
        CHECK (claim_status IN ('DRAFT_VALIDATION_ERROR', 'SUBMITTED_TO_PORTAL', 'PENDING_STATE_APPROVAL', 'PARTIALLY_REIMBURSED', 'SETTLED', 'REJECTED')),
    validation_errors_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    submission_date DATE NOT NULL DEFAULT CURRENT_DATE,
    is_synthetic BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_reimbursement_campus_status ON government_reimbursement_claims(campus_id, claim_status);

CREATE TABLE IF NOT EXISTS reimbursement_status_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id UUID NOT NULL REFERENCES government_reimbursement_claims(id) ON DELETE CASCADE,
    previous_status VARCHAR(40),
    new_status VARCHAR(40) NOT NULL,
    notes TEXT,
    changed_by UUID REFERENCES users(id),
    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- GROUP 8: DATA QUALITY, DUPLICATE RECONCILIATION, PRIVACY & AUDIT
-- =============================================================================

CREATE TABLE IF NOT EXISTS dataset_imports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campus_id UUID REFERENCES campuses(id),
    filename VARCHAR(255) NOT NULL,
    file_format VARCHAR(30) NOT NULL, -- CSV, XLSX, JSON, SQL_DUMP
    file_checksum VARCHAR(64) NOT NULL,
    target_module VARCHAR(50) NOT NULL, -- ADMISSIONS, STUDENTS, FEES, ATTENDANCE, HOSTEL, SCHOLARSHIPS, TRANSFERS
    total_rows INT NOT NULL DEFAULT 0,
    accepted_rows INT NOT NULL DEFAULT 0,
    rejected_rows INT NOT NULL DEFAULT 0,
    skipped_duplicate_rows INT NOT NULL DEFAULT 0,
    reconciled_rows INT NOT NULL DEFAULT 0,
    status VARCHAR(30) NOT NULL DEFAULT 'COMPLETED' CHECK (status IN ('PROFILED', 'VALIDATING', 'COMPLETED', 'ROLLED_BACK', 'FAILED')),
    summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_report_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    imported_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dataset_column_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_system_name VARCHAR(120) UNIQUE NOT NULL,
    target_module VARCHAR(50) NOT NULL,
    mapping_json JSONB NOT NULL, -- e.g. {"Student Name": "full_name", "DOB": "date_of_birth"}
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS data_quality_issues (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    import_id UUID REFERENCES dataset_imports(id) ON DELETE CASCADE,
    campus_id UUID REFERENCES campuses(id),
    source_file VARCHAR(200) NOT NULL,
    row_number INT NOT NULL,
    field_name VARCHAR(80) NOT NULL,
    issue_type VARCHAR(60) NOT NULL, -- MISSING_REQUIRED, INVALID_DATE, DUPLICATE_REF, CONFLICTING_VALUE, INFERRED_FIELD
    severity VARCHAR(20) NOT NULL DEFAULT 'WARNING' CHECK (severity IN ('INFO', 'WARNING', 'ERROR')),
    raw_value TEXT,
    resolution_status VARCHAR(30) NOT NULL DEFAULT 'OPEN' CHECK (resolution_status IN ('OPEN', 'RESOLVED', 'REJECTED')),
    description TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS duplicate_match_candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    import_id UUID REFERENCES dataset_imports(id) ON DELETE SET NULL,
    source_file VARCHAR(200) NOT NULL,
    source_record_key VARCHAR(100) NOT NULL,
    source_student_name VARCHAR(200) NOT NULL,
    source_dob VARCHAR(40),
    source_phone VARCHAR(40),
    source_usn VARCHAR(60),
    candidate_student_id UUID REFERENCES students(student_id) ON DELETE CASCADE,
    candidate_student_name VARCHAR(200) NOT NULL,
    candidate_usn VARCHAR(60) NOT NULL,
    match_confidence NUMERIC(5,2) NOT NULL CHECK (match_confidence BETWEEN 0 AND 100),
    matching_attributes JSONB NOT NULL DEFAULT '[]'::jsonb,
    conflicting_attributes JSONB NOT NULL DEFAULT '[]'::jsonb,
    proposed_action VARCHAR(40) NOT NULL CHECK (proposed_action IN ('EXACT_LINK', 'HUMAN_REVIEW', 'KEEP_SEPARATE')),
    review_status VARCHAR(30) NOT NULL DEFAULT 'PENDING_REVIEW'
        CHECK (review_status IN ('PENDING_REVIEW', 'CONFIRMED_DUPLICATE', 'DISTINCT_STUDENTS', 'AUTO_LINKED')),
    ground_truth_is_duplicate BOOLEAN, -- Used for Precision/Recall/F1 evaluation against ground truth
    reviewed_by UUID REFERENCES users(id),
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recipient_user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    student_id UUID REFERENCES students(student_id) ON DELETE CASCADE,
    campus_id UUID REFERENCES campuses(id),
    category VARCHAR(50) NOT NULL, -- FEE_POSTED, FEE_REMINDER, HOSTEL_ALLOCATION, TRANSFER_UPDATE, ATTENDANCE_WARNING, PRIVACY_UPDATE
    title VARCHAR(200) NOT NULL,
    message TEXT NOT NULL,
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    is_simulated BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS privacy_notices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version VARCHAR(20) UNIQUE NOT NULL,
    title VARCHAR(200) NOT NULL,
    framework_reference VARCHAR(120) NOT NULL DEFAULT 'DPDP Act, 2023 & DPDP Rules, 2025 (Engineering Controls)',
    content TEXT NOT NULL,
    purposes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    effective_date DATE NOT NULL DEFAULT CURRENT_DATE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS consent_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id UUID NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id),
    notice_id UUID NOT NULL REFERENCES privacy_notices(id),
    purpose_code VARCHAR(60) NOT NULL, -- ACADEMIC_ADMIN, PARENT_PORTAL_ALERTS, SCHOLARSHIP_EXPORT, ALUMNI_DIRECTORY
    legal_basis VARCHAR(60) NOT NULL DEFAULT 'CONSENT', -- CONSENT, VOLUNTARY_PROVISION, STATUTORY_OBLIGATION
    consent_status VARCHAR(30) NOT NULL DEFAULT 'GRANTED' CHECK (consent_status IN ('GRANTED', 'WITHDRAWN', 'EXPIRED')),
    is_minor_student BOOLEAN NOT NULL DEFAULT FALSE,
    guardian_verified_consent BOOLEAN NOT NULL DEFAULT TRUE,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    withdrawn_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS data_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id UUID NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
    requested_by_user_id UUID REFERENCES users(id),
    request_type VARCHAR(40) NOT NULL CHECK (request_type IN ('ACCESS_SUMMARY', 'CORRECTION', 'ERASURE', 'GRIEVANCE')),
    details TEXT NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'IN_REVIEW', 'COMPLETED', 'REJECTED_RETENTION_HOLD')),
    resolution_notes TEXT,
    resolved_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS retention_policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    record_category VARCHAR(80) UNIQUE NOT NULL, -- FINANCIAL_LEDGER, ACADEMIC_TRANSCRIPTS, ADMISSION_RECORDS, HOSTEL_LOGS
    retention_years INT NOT NULL,
    statutory_basis TEXT NOT NULL,
    allow_immediate_erasure BOOLEAN NOT NULL DEFAULT FALSE,
    disposal_action VARCHAR(40) NOT NULL DEFAULT 'ANONYMISE_AFTER_RETENTION'
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_user_id UUID,
    actor_role VARCHAR(40),
    campus_id UUID,
    action VARCHAR(80) NOT NULL,
    entity_type VARCHAR(60) NOT NULL,
    entity_id VARCHAR(100),
    summary TEXT NOT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ip_address VARCHAR(45) DEFAULT '127.0.0.1',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs(created_at DESC);

-- Prevent modification or deletion of audit_logs by ordinary users
CREATE OR REPLACE FUNCTION protect_audit_logs()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Security violation: audit_logs are append-only and cannot be modified or deleted.';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_protect_audit_logs ON audit_logs;
CREATE TRIGGER trg_protect_audit_logs
BEFORE UPDATE OR DELETE ON audit_logs
FOR EACH ROW EXECUTE FUNCTION protect_audit_logs();

-- =============================================================================
-- ROW-LEVEL SECURITY (RLS) POLICIES FOR MULTI-CAMPUS & ROLE ISOLATION
-- =============================================================================

-- Enable RLS on campus-scoped and student-scoped tables
ALTER TABLE students ENABLE ROW LEVEL SECURITY;
ALTER TABLE campus_enrollments ENABLE ROW LEVEL SECURITY;
ALTER TABLE student_fee_assessments ENABLE ROW LEVEL SECURITY;
ALTER TABLE payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE hostel_beds ENABLE ROW LEVEL SECURITY;
ALTER TABLE hostel_allocations ENABLE ROW LEVEL SECURITY;
ALTER TABLE academic_progress_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE government_reimbursement_claims ENABLE ROW LEVEL SECURITY;

-- 1. students RLS policy
DROP POLICY IF EXISTS rls_students_isolation ON students;
CREATE POLICY rls_students_isolation ON students
    FOR ALL
    TO trustos_app
    USING (
        app_current_role() = 'TRUST_MANAGEMENT'
        OR (app_current_role() IN ('COLLEGE_ADMIN', 'HOSTEL_WARDEN') AND primary_campus_id = app_current_campus_id())
        OR (app_current_role() = 'STUDENT' AND student_id = app_current_student_id())
        OR (app_current_role() = 'PARENT' AND EXISTS (
            SELECT 1 FROM parent_student_links psl
            WHERE psl.student_id = students.student_id
              AND psl.parent_user_id = app_current_user_id()
              AND psl.is_verified = TRUE
        ))
    )
    WITH CHECK (
        app_current_role() = 'TRUST_MANAGEMENT'
        OR (app_current_role() = 'COLLEGE_ADMIN' AND primary_campus_id = app_current_campus_id())
    );

-- 2. campus_enrollments RLS policy
DROP POLICY IF EXISTS rls_enrollments_isolation ON campus_enrollments;
CREATE POLICY rls_enrollments_isolation ON campus_enrollments
    FOR ALL
    TO trustos_app
    USING (
        app_current_role() = 'TRUST_MANAGEMENT'
        OR (app_current_role() IN ('COLLEGE_ADMIN', 'HOSTEL_WARDEN') AND campus_id = app_current_campus_id())
        OR (app_current_role() = 'STUDENT' AND student_id = app_current_student_id())
        OR (app_current_role() = 'PARENT' AND EXISTS (
            SELECT 1 FROM parent_student_links psl
            WHERE psl.student_id = campus_enrollments.student_id
              AND psl.parent_user_id = app_current_user_id()
              AND psl.is_verified = TRUE
        ))
    )
    WITH CHECK (
        app_current_role() = 'TRUST_MANAGEMENT'
        OR (app_current_role() = 'COLLEGE_ADMIN' AND campus_id = app_current_campus_id())
    );

-- 3. student_fee_assessments RLS policy (Note: Wardens cannot access financial tables!)
DROP POLICY IF EXISTS rls_fee_assessments_isolation ON student_fee_assessments;
CREATE POLICY rls_fee_assessments_isolation ON student_fee_assessments
    FOR ALL
    TO trustos_app
    USING (
        app_current_role() = 'TRUST_MANAGEMENT'
        OR (app_current_role() = 'COLLEGE_ADMIN' AND campus_id = app_current_campus_id())
        OR (app_current_role() = 'STUDENT' AND student_id = app_current_student_id())
        OR (app_current_role() = 'PARENT' AND EXISTS (
            SELECT 1 FROM parent_student_links psl
            WHERE psl.student_id = student_fee_assessments.student_id
              AND psl.parent_user_id = app_current_user_id()
              AND psl.is_verified = TRUE
        ))
    )
    WITH CHECK (
        app_current_role() = 'TRUST_MANAGEMENT'
        OR (app_current_role() = 'COLLEGE_ADMIN' AND campus_id = app_current_campus_id())
    );

-- 4. payments RLS policy (Wardens denied financial access)
DROP POLICY IF EXISTS rls_payments_isolation ON payments;
CREATE POLICY rls_payments_isolation ON payments
    FOR ALL
    TO trustos_app
    USING (
        app_current_role() = 'TRUST_MANAGEMENT'
        OR (app_current_role() = 'COLLEGE_ADMIN' AND campus_id = app_current_campus_id())
        OR (app_current_role() = 'STUDENT' AND student_id = app_current_student_id())
        OR (app_current_role() = 'PARENT' AND EXISTS (
            SELECT 1 FROM parent_student_links psl
            WHERE psl.student_id = payments.student_id
              AND psl.parent_user_id = app_current_user_id()
              AND psl.is_verified = TRUE
        ))
    )
    WITH CHECK (
        app_current_role() = 'TRUST_MANAGEMENT'
        OR (app_current_role() = 'COLLEGE_ADMIN' AND campus_id = app_current_campus_id())
    );

-- 5. hostel_beds RLS policy
DROP POLICY IF EXISTS rls_hostel_beds_isolation ON hostel_beds;
CREATE POLICY rls_hostel_beds_isolation ON hostel_beds
    FOR ALL
    TO trustos_app
    USING (
        app_current_role() = 'TRUST_MANAGEMENT'
        OR (app_current_role() IN ('COLLEGE_ADMIN', 'HOSTEL_WARDEN') AND campus_id = app_current_campus_id())
        OR (app_current_role() = 'STUDENT' AND (current_student_id = app_current_student_id() OR campus_id = app_current_campus_id()))
        OR (app_current_role() = 'PARENT' AND EXISTS (
            SELECT 1 FROM parent_student_links psl
            WHERE psl.student_id = hostel_beds.current_student_id
              AND psl.parent_user_id = app_current_user_id()
              AND psl.is_verified = TRUE
        ))
    )
    WITH CHECK (
        app_current_role() = 'TRUST_MANAGEMENT'
        OR (app_current_role() IN ('COLLEGE_ADMIN', 'HOSTEL_WARDEN') AND campus_id = app_current_campus_id())
    );

-- 6. hostel_allocations RLS policy
DROP POLICY IF EXISTS rls_hostel_allocations_isolation ON hostel_allocations;
CREATE POLICY rls_hostel_allocations_isolation ON hostel_allocations
    FOR ALL
    TO trustos_app
    USING (
        app_current_role() = 'TRUST_MANAGEMENT'
        OR (app_current_role() IN ('COLLEGE_ADMIN', 'HOSTEL_WARDEN') AND campus_id = app_current_campus_id())
        OR (app_current_role() = 'STUDENT' AND student_id = app_current_student_id())
        OR (app_current_role() = 'PARENT' AND EXISTS (
            SELECT 1 FROM parent_student_links psl
            WHERE psl.student_id = hostel_allocations.student_id
              AND psl.parent_user_id = app_current_user_id()
              AND psl.is_verified = TRUE
        ))
    )
    WITH CHECK (
        app_current_role() = 'TRUST_MANAGEMENT'
        OR (app_current_role() IN ('COLLEGE_ADMIN', 'HOSTEL_WARDEN') AND campus_id = app_current_campus_id())
    );

-- 7. academic_progress_records RLS policy
DROP POLICY IF EXISTS rls_academic_progress_isolation ON academic_progress_records;
CREATE POLICY rls_academic_progress_isolation ON academic_progress_records
    FOR ALL
    TO trustos_app
    USING (
        app_current_role() = 'TRUST_MANAGEMENT'
        OR (app_current_role() = 'COLLEGE_ADMIN' AND campus_id = app_current_campus_id())
        OR (app_current_role() = 'STUDENT' AND student_id = app_current_student_id())
        OR (app_current_role() = 'PARENT' AND EXISTS (
            SELECT 1 FROM parent_student_links psl
            WHERE psl.student_id = academic_progress_records.student_id
              AND psl.parent_user_id = app_current_user_id()
              AND psl.is_verified = TRUE
        ))
    )
    WITH CHECK (
        app_current_role() = 'TRUST_MANAGEMENT'
        OR (app_current_role() = 'COLLEGE_ADMIN' AND campus_id = app_current_campus_id())
    );

-- 8. government_reimbursement_claims RLS policy
DROP POLICY IF EXISTS rls_reimbursements_isolation ON government_reimbursement_claims;
CREATE POLICY rls_reimbursements_isolation ON government_reimbursement_claims
    FOR ALL
    TO trustos_app
    USING (
        app_current_role() = 'TRUST_MANAGEMENT'
        OR (app_current_role() = 'COLLEGE_ADMIN' AND campus_id = app_current_campus_id())
        OR (app_current_role() = 'STUDENT' AND student_id = app_current_student_id())
        OR (app_current_role() = 'PARENT' AND EXISTS (
            SELECT 1 FROM parent_student_links psl
            WHERE psl.student_id = government_reimbursement_claims.student_id
              AND psl.parent_user_id = app_current_user_id()
              AND psl.is_verified = TRUE
        ))
    )
    WITH CHECK (
        app_current_role() = 'TRUST_MANAGEMENT'
        OR (app_current_role() = 'COLLEGE_ADMIN' AND campus_id = app_current_campus_id())
    );

-- Grant permissions to trustos_app
GRANT USAGE ON SCHEMA public TO trustos_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO trustos_app;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO trustos_app;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO trustos_app;
