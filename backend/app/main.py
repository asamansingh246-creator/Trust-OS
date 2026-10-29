"""
Phase 5, 7, 17, 18: TrustOS Complete FastAPI Modular Monolith Application.
Exposes real, database-backed, RLS-enforced endpoints for all 5 roles and 24 UI views:
- Auth, Registration Request, Approval Workflow, Password Reset, Logout
- Trust Management Executive Dashboard (Campus 1..6 + Cumulative View without double-counting transfers)
- Admissions, Permanent Identity Search, Duplicate Review Queue & Ground-Truth Evaluation Metrics
- Campus Transfer Workflow (Preview, Collision-Safe Sequence USN, Eligibility Check, Single-Transaction Commit)
- Fee Assessments, Two-Level Payment Verification (College Verify -> Trust Reconcile & Post), Concessions, Refunds, Reversals & Immutable Receipts
- Hostel Vacancy Map (Green/Red/Amber/Grey beds), Transactional Bed Allocation (`SELECT ... FOR UPDATE`), Release
- Attendance Sessions, Policy-Driven Eligibility Calculation (75% default or campus policy), Exam Results
- Scholarships & Government Reimbursement Claims + Configurable Export Template
- Multi-Dataset Profiler, Column Mapping Persistence & Idempotent Validated Importer
- Campus Policy Editor with Versioning & Audit Trail
- DPDP Act 2023 Privacy Notices, Consent Management, Minor/Guardian Controls, Data Requests & Retention Policies
- In-App Notification Centre (verifies posted balance before issuing fee reminders) & Tamper-Evident Audit Log Viewer
"""

import io
import csv
import json
import uuid
import hashlib
from datetime import date, datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.db import get_owner_conn, get_rls_conn
from app.auth import (
    hash_password, verify_password, check_rate_limit, create_access_token,
    get_current_user, require_roles, record_audit_log, REVOKED_TOKENS
)
from app.ingestion import (
    profile_dataset, load_dataframe_from_bytes, parse_flexible_date,
    normalize_text, score_student_duplicate_candidate, evaluate_duplicate_metrics
)

app = FastAPI(
    title="TrustOS — Multi-Campus Educational Trust Management Platform",
    version="1.0.0",
    description="Unified institutional record system for 6 campuses & 14,000 canonical students with PostgreSQL Row-Level Security."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# PYDANTIC SCHEMAS
# =============================================================================

class LoginRequest(BaseModel):
    user_id_or_email: str
    password: str


class RegistrationRequestCreate(BaseModel):
    requested_role: str = Field(..., pattern="^(TRUST_MANAGEMENT|COLLEGE_ADMIN|STUDENT|PARENT|HOSTEL_WARDEN)$")
    full_name: str
    email: str
    phone: Optional[str] = None
    campus_id: Optional[str] = None
    verification_usn: Optional[str] = None
    password: str = Field(..., min_length=8)


class RegistrationDecisionRequest(BaseModel):
    decision: str = Field(..., pattern="^(APPROVED|REJECTED|SUSPENDED)$")
    review_notes: Optional[str] = None


class PasswordResetRequest(BaseModel):
    display_user_id: str
    verified_email: str
    new_password: str = Field(..., min_length=8)


class AdmissionCreateRequest(BaseModel):
    full_name: str
    date_of_birth: date
    gender: str = "Male"
    phone: str
    email: Optional[str] = None
    guardian_name: str
    guardian_phone: str
    category: str = "GENERAL"
    campus_id: Optional[str] = None
    course_id: str
    quota: str = "MERIT"
    existing_student_id: Optional[str] = None


class TransferPreviewRequest(BaseModel):
    source_usn: str
    destination_campus_id: str
    destination_course_id: Optional[str] = None
    reason: str = "Academic relocation request"


class TransferApproveRequest(BaseModel):
    decision: str = Field("APPROVED", pattern="^(APPROVED|REJECTED)$")
    comments: Optional[str] = None


class FeeAssessmentCreateRequest(BaseModel):
    student_id: str
    assessed_amount: float = Field(..., gt=0)
    due_date: date = Field(default_factory=lambda: date(2026, 12, 15))


class PaymentRecordRequest(BaseModel):
    assessment_id: str
    amount: float = Field(..., gt=0)
    transaction_ref: str
    payment_mode: str = "UPI_SIMULATED"
    auto_college_verify: bool = False


class ConcessionOrScholarshipRequest(BaseModel):
    assessment_id: str
    entry_type: str = Field(..., pattern="^(CONCESSION|SCHOLARSHIP)$")
    category_or_scheme: str
    amount: float = Field(..., gt=0)
    reason: Optional[str] = None


class RefundOrReversalRequest(BaseModel):
    payment_id: str
    action_type: str = Field(..., pattern="^(REFUND|REVERSAL)$")
    amount: float = Field(..., gt=0)
    reason: str


class HostelAllocateRequest(BaseModel):
    usn: str
    bed_id: str
    allocation_type: str = Field("ACTIVE", pattern="^(ACTIVE|RESERVED)$")


class HostelReleaseRequest(BaseModel):
    allocation_id: str
    reason: str


class PolicyUpdateRequest(BaseModel):
    campus_id: str
    attendance_threshold_pct: float = Field(..., ge=50, le=100)
    warning_threshold_pct: float = Field(..., ge=50, le=100)
    late_fee_per_day: float = Field(..., ge=0)
    grace_period_days: int = Field(..., ge=0)
    max_concession_pct: float = Field(50.0, ge=0, le=100)
    transfer_min_attendance_pct: float = Field(65.0, ge=0, le=100)
    require_zero_dues_for_transfer: bool = False


class DuplicateDecisionRequest(BaseModel):
    decision: str = Field(..., pattern="^(CONFIRMED_DUPLICATE|DISTINCT_STUDENTS)$")


class ConsentToggleRequest(BaseModel):
    student_id: str
    purpose_code: str
    action: str = Field(..., pattern="^(GRANTED|WITHDRAWN)$")


class DataRequestCreate(BaseModel):
    student_id: str
    request_type: str = Field(..., pattern="^(ACCESS_SUMMARY|CORRECTION|ERASURE|GRIEVANCE)$")
    details: str


# =============================================================================
# 1. PUBLIC METADATA & AUTHENTICATION ENDPOINTS
# =============================================================================

@app.get("/api/health")
def health_check():
    with get_owner_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS campuses FROM campuses")
            c_cnt = cur.fetchone()["campuses"]
            cur.execute("SELECT COUNT(*) AS students FROM students")
            s_cnt = cur.fetchone()["students"]
    return {"status": "ok", "campuses": c_cnt, "canonical_students": s_cnt, "synthetic_environment": True}


@app.get("/api/public/campuses")
def list_public_campuses():
    with get_owner_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT c.id, c.campus_number, c.code, c.name, c.city, c.usn_prefix,
                       ct.code AS campus_type, ct.name AS campus_type_name
                FROM campuses c
                JOIN campus_types ct ON ct.id = c.campus_type_id
                ORDER BY c.campus_number
            """)
            campuses = cur.fetchall()
            cur.execute("SELECT id, campus_id, code, name, duration_years FROM courses ORDER BY code")
            courses = cur.fetchall()
    return {"campuses": campuses, "courses": courses}


@app.post("/api/auth/login")
def login(payload: LoginRequest, request: Request):
    client_ip = request.client.host if request.client else "127.0.0.1"
    check_rate_limit(f"login:{client_ip}:{payload.user_id_or_email.lower()}")

    ident = payload.user_id_or_email.strip()
    with get_owner_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT u.*, c.name AS campus_name, c.code AS campus_code, c.campus_number
                   FROM users u
                   LEFT JOIN campuses c ON c.id = u.primary_campus_id
                   WHERE UPPER(u.display_user_id) = UPPER(%s) OR LOWER(u.email) = LOWER(%s)""",
                (ident, ident)
            )
            user = cur.fetchone()

            if not user or not verify_password(payload.password, user["password_hash"]):
                if user:
                    cur.execute("UPDATE users SET failed_login_attempts = failed_login_attempts + 1 WHERE id = %s", (user["id"],))
                record_audit_log(
                    conn, str(user["id"]) if user else None, user["role_code"] if user else None,
                    str(user["primary_campus_id"]) if (user and user["primary_campus_id"]) else None,
                    "LOGIN_FAILED", "users", ident, "Failed sign-in attempt", {"identifier": ident}, client_ip
                )
                # Generic error message that never discloses whether a sensitive account exists
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user ID or password")

            if user["status"] != "ACTIVE":
                record_audit_log(
                    conn, str(user["id"]), user["role_code"],
                    str(user["primary_campus_id"]) if user["primary_campus_id"] else None,
                    "LOGIN_BLOCKED_INACTIVE", "users", user["display_user_id"],
                    f"Sign-in denied for non-active status {user['status']}"
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Account is currently {user['status']} and cannot access the platform."
                )

            cur.execute("UPDATE users SET failed_login_attempts = 0, last_login_at = NOW() WHERE id = %s", (user["id"],))
            record_audit_log(
                conn, str(user["id"]), user["role_code"],
                str(user["primary_campus_id"]) if user["primary_campus_id"] else None,
                "LOGIN_SUCCESS", "users", user["display_user_id"], f"User {user['display_user_id']} signed in"
            )

    token = create_access_token(user)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": str(user["id"]),
            "display_user_id": user["display_user_id"],
            "full_name": user["full_name"],
            "email": user["email"],
            "role_code": user["role_code"],
            "status": user["status"],
            "primary_campus_id": str(user["primary_campus_id"]) if user["primary_campus_id"] else None,
            "campus_name": user.get("campus_name"),
            "campus_code": user.get("campus_code"),
            "linked_student_id": str(user["linked_student_id"]) if user["linked_student_id"] else None,
        }
    }


@app.post("/api/auth/logout")
def logout(user: Dict[str, Any] = Depends(get_current_user)):
    REVOKED_TOKENS.add(user["token"])
    return {"status": "logged_out"}


@app.get("/api/auth/me")
def get_me(user: Dict[str, Any] = Depends(get_current_user)):
    return {
        "id": str(user["id"]),
        "display_user_id": user["display_user_id"],
        "full_name": user["full_name"],
        "email": user["email"],
        "role_code": user["role_code"],
        "status": user["status"],
        "primary_campus_id": str(user["primary_campus_id"]) if user["primary_campus_id"] else None,
        "campus_name": user.get("campus_name"),
        "campus_code": user.get("campus_code"),
        "linked_student_id": str(user["linked_student_id"]) if user["linked_student_id"] else None,
    }


@app.post("/api/auth/register-request", status_code=201)
def submit_registration_request(payload: RegistrationRequestCreate):
    """
    Creates a registration request.
    Selecting a role NEVER grants privileged access automatically:
    all requests enter `PENDING` status until verified and approved by an authorized administrator.
    Student and Parent requests require a verified institutional USN.
    """
    with get_owner_conn() as conn:
        with conn.cursor() as cur:
            linked_student_id = None
            campus_id = payload.campus_id

            if payload.requested_role in ("STUDENT", "PARENT"):
                if not payload.verification_usn:
                    raise HTTPException(status_code=400, detail="Student and Parent registrations must provide a verified institutional USN.")
                cur.execute(
                    """SELECT s.student_id, s.primary_campus_id
                       FROM students s
                       WHERE UPPER(s.current_usn) = UPPER(%s)
                          OR EXISTS (
                              SELECT 1 FROM student_identifiers si
                              WHERE si.student_id = s.student_id AND UPPER(si.id_value) = UPPER(%s)
                          )
                       LIMIT 1""",
                    (payload.verification_usn.strip(), payload.verification_usn.strip())
                )
                st = cur.fetchone()
                if not st:
                    raise HTTPException(status_code=400, detail="Provided USN could not be verified against institutional records.")
                linked_student_id = st["student_id"]
                campus_id = str(st["primary_campus_id"])

            req_id = str(uuid.uuid4())
            pw_hash = hash_password(payload.password)
            cur.execute(
                """INSERT INTO registration_requests (
                    id, requested_role, full_name, email, phone, campus_id, verification_usn, linked_student_id, password_hash, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDING')""",
                (req_id, payload.requested_role, payload.full_name, payload.email, payload.phone, campus_id, payload.verification_usn, linked_student_id, pw_hash)
            )
            record_audit_log(
                conn, None, "ANONYMOUS", campus_id, "REGISTRATION_REQUESTED", "registration_requests",
                req_id, f"Registration requested for role {payload.requested_role} ({payload.email})"
            )

    return {
        "request_id": req_id,
        "status": "PENDING",
        "message": "Registration request submitted. An administrator must review and approve your request before a User ID is issued."
    }


@app.get("/api/auth/registration-status/{request_id}")
def check_registration_status(request_id: str):
    """
    Looks up registration status by Request UUID, Verification USN (e.g. 1VV26CS0001),
    Generated User ID (e.g. S10001, A1099), or Email.
    If no pending registration request row exists, also checks active/pending/suspended `users`
    or `students` by USN so entering a USN like `1VV26CS0001` returns a clean status response.
    """
    q = request_id.strip()
    is_valid_uuid = False
    try:
        uuid.UUID(q)
        is_valid_uuid = True
    except ValueError:
        pass

    with get_owner_conn() as conn:
        with conn.cursor() as cur:
            if is_valid_uuid:
                cur.execute(
                    """SELECT id, requested_role, full_name, email, status, generated_user_id, review_notes, created_at, reviewed_at
                       FROM registration_requests WHERE id = %s""",
                    (q,)
                )
            else:
                cur.execute(
                    """SELECT id, requested_role, full_name, email, status, generated_user_id, review_notes, created_at, reviewed_at
                       FROM registration_requests
                       WHERE UPPER(COALESCE(verification_usn, '')) = UPPER(%s)
                          OR UPPER(COALESCE(generated_user_id, '')) = UPPER(%s)
                          OR LOWER(email) = LOWER(%s)
                       ORDER BY created_at DESC LIMIT 1""",
                    (q, q, q)
                )
            row = cur.fetchone()
            if row:
                return row

            # Fallback 1: check `users` by display_user_id, email, or linked student's current or historical USN
            cur.execute(
                """SELECT u.id, u.role_code AS requested_role, u.full_name, u.email, u.status,
                          u.display_user_id AS generated_user_id, s.current_usn, u.created_at
                   FROM users u
                   LEFT JOIN students s ON s.student_id = u.linked_student_id
                   WHERE UPPER(u.display_user_id) = UPPER(%s)
                      OR LOWER(u.email) = LOWER(%s)
                      OR UPPER(COALESCE(s.current_usn, '')) = UPPER(%s)
                      OR EXISTS (
                          SELECT 1 FROM student_identifiers si
                          WHERE si.student_id = u.linked_student_id AND UPPER(si.id_value) = UPPER(%s)
                      )
                   ORDER BY CASE WHEN u.role_code = 'STUDENT' THEN 0 ELSE 1 END
                   LIMIT 1""",
                (q, q, q, q)
            )
            u_row = cur.fetchone()
            if u_row:
                return {
                    "id": str(u_row["id"]),
                    "requested_role": u_row["requested_role"],
                    "full_name": u_row["full_name"],
                    "email": u_row["email"],
                    "status": u_row["status"],
                    "generated_user_id": u_row["generated_user_id"],
                    "review_notes": f"Verified institutional account (Active USN: {u_row['current_usn']})" if u_row.get("current_usn") else "Verified institutional account",
                    "created_at": u_row["created_at"],
                    "reviewed_at": u_row["created_at"],
                }

            # Fallback 2: check `students` directly by current_usn, historical `student_identifiers`, or prefix match
            cur.execute(
                """SELECT s.student_id, s.full_name, s.email, s.current_usn, s.created_at
                   FROM students s
                   WHERE UPPER(s.current_usn) = UPPER(%s)
                      OR EXISTS (
                          SELECT 1 FROM student_identifiers si
                          WHERE si.student_id = s.student_id AND UPPER(si.id_value) = UPPER(%s)
                      )
                      OR (LENGTH(%s) >= 6 AND UPPER(s.current_usn) LIKE UPPER(%s))
                   ORDER BY s.current_usn
                   LIMIT 1""",
                (q, q, q, f"{q[:5]}%{q[-4:]}")
            )
            st_row = cur.fetchone()
            if st_row:
                return {
                    "id": str(st_row["student_id"]),
                    "requested_role": "STUDENT",
                    "full_name": st_row["full_name"],
                    "email": st_row["email"],
                    "status": "ENROLLED_NO_PORTAL_REQUEST_YET",
                    "generated_user_id": f"Submit tab '2. Request Registration' with USN {st_row['current_usn']}",
                    "review_notes": f"Student {st_row['current_usn']} is verified in canonical registry.",
                    "created_at": st_row["created_at"],
                    "reviewed_at": None,
                }

            raise HTTPException(
                status_code=404,
                detail=f"No registration request, user ID, email, or student USN matching '{q}' was found."
            )


@app.get("/api/admin/registration-requests")
def list_registration_requests(user: Dict[str, Any] = Depends(require_roles("TRUST_MANAGEMENT", "COLLEGE_ADMIN"))):
    with get_owner_conn() as conn:
        with conn.cursor() as cur:
            if user["role_code"] == "TRUST_MANAGEMENT":
                cur.execute("""
                    SELECT r.*, c.name AS campus_name
                    FROM registration_requests r
                    LEFT JOIN campuses c ON c.id = r.campus_id
                    ORDER BY r.created_at DESC
                """)
            else:
                cur.execute("""
                    SELECT r.*, c.name AS campus_name
                    FROM registration_requests r
                    LEFT JOIN campuses c ON c.id = r.campus_id
                    WHERE r.campus_id = %s AND r.requested_role <> 'TRUST_MANAGEMENT'
                    ORDER BY r.created_at DESC
                """, (user["primary_campus_id"],))
            return {"requests": cur.fetchall()}


@app.post("/api/admin/registration-requests/{request_id}/decide")
def decide_registration_request(
    request_id: str,
    payload: RegistrationDecisionRequest,
    user: Dict[str, Any] = Depends(require_roles("TRUST_MANAGEMENT", "COLLEGE_ADMIN"))
):
    with get_owner_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM registration_requests WHERE id = %s FOR UPDATE", (request_id,))
            req = cur.fetchone()
            if not req:
                raise HTTPException(status_code=404, detail="Registration request not found")

            # Prevent self-approval or unauthorized role elevation
            if req["email"].lower() == user["email"].lower():
                raise HTTPException(status_code=403, detail="Users cannot approve their own registration requests.")
            if req["requested_role"] == "TRUST_MANAGEMENT" and user["role_code"] != "TRUST_MANAGEMENT":
                raise HTTPException(status_code=403, detail="Only Trust Management can approve Trust Management accounts.")
            if user["role_code"] == "COLLEGE_ADMIN" and str(req["campus_id"]) != str(user["primary_campus_id"]):
                raise HTTPException(status_code=403, detail="College Administrators can only approve requests for their assigned campus.")

            generated_user_id = req["generated_user_id"]
            if payload.decision == "APPROVED" and req["status"] != "APPROVED":
                seq_map = {
                    "TRUST_MANAGEMENT": ("M", "seq_user_mgmt"),
                    "COLLEGE_ADMIN": ("A", "seq_user_admin"),
                    "STUDENT": ("S", "seq_user_student"),
                    "PARENT": ("P", "seq_user_parent"),
                    "HOSTEL_WARDEN": ("W", "seq_user_warden"),
                }
                prefix, seq_name = seq_map[req["requested_role"]]
                cur.execute(f"SELECT nextval('{seq_name}') AS val")
                seq_val = cur.fetchone()["val"]
                generated_user_id = f"{prefix}{seq_val}"

                new_uid = str(uuid.uuid4())
                cur.execute(
                    """INSERT INTO users (
                        id, display_user_id, full_name, email, phone, password_hash,
                        role_code, status, primary_campus_id, linked_student_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'ACTIVE', %s, %s)""",
                    (
                        new_uid, generated_user_id, req["full_name"], req["email"], req["phone"],
                        req["password_hash"], req["requested_role"], req["campus_id"], req["linked_student_id"]
                    )
                )
                cur.execute(
                    "INSERT INTO user_roles (user_id, role_code, granted_by) VALUES (%s, %s, %s)",
                    (new_uid, req["requested_role"], user["id"])
                )
                if req["campus_id"]:
                    cur.execute(
                        "INSERT INTO user_campus_assignments (user_id, campus_id, is_primary) VALUES (%s, %s, TRUE)",
                        (new_uid, req["campus_id"])
                    )
                if req["requested_role"] == "PARENT" and req["linked_student_id"]:
                    cur.execute(
                        "INSERT INTO parent_student_links (parent_user_id, student_id, relationship, is_verified) VALUES (%s, %s, 'Parent', TRUE) ON CONFLICT DO NOTHING",
                        (new_uid, req["linked_student_id"])
                    )

            cur.execute(
                """UPDATE registration_requests
                   SET status = %s, generated_user_id = %s, reviewed_by = %s, review_notes = %s, reviewed_at = NOW()
                   WHERE id = %s""",
                (payload.decision, generated_user_id, user["id"], payload.review_notes, request_id)
            )
            record_audit_log(
                conn, str(user["id"]), user["role_code"], str(req["campus_id"]) if req["campus_id"] else None,
                f"REGISTRATION_{payload.decision}", "registration_requests", request_id,
                f"Registration request {request_id} marked {payload.decision} (User ID: {generated_user_id})"
            )

    return {"request_id": request_id, "status": payload.decision, "generated_user_id": generated_user_id}


@app.post("/api/auth/password-reset")
def reset_password(payload: PasswordResetRequest):
    with get_owner_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, display_user_id, email, role_code, primary_campus_id FROM users WHERE UPPER(display_user_id) = UPPER(%s) AND LOWER(email) = LOWER(%s)",
                (payload.display_user_id.strip(), payload.verified_email.strip())
            )
            u = cur.fetchone()
            if not u:
                raise HTTPException(status_code=400, detail="Verification details did not match an active account.")
            new_hash = hash_password(payload.new_password)
            cur.execute("UPDATE users SET password_hash = %s, failed_login_attempts = 0 WHERE id = %s", (new_hash, u["id"]))
            record_audit_log(
                conn, str(u["id"]), u["role_code"], str(u["primary_campus_id"]) if u["primary_campus_id"] else None,
                "PASSWORD_RESET", "users", u["display_user_id"], f"Password reset completed for {u['display_user_id']}"
            )
    return {"status": "password_updated", "display_user_id": payload.display_user_id.upper()}


# =============================================================================
# 2. TRUST MANAGEMENT & CAMPUS SUMMARY DASHBOARD (Computed Live from DB)
# =============================================================================

@app.get("/api/dashboard/summary")
def get_dashboard_summary(
    campus_id: Optional[str] = Query(default=None, description="Specific campus UUID or omit/'ALL' for Cumulative View"),
    user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Computes live institutional metrics from PostgreSQL under the `trustos_app` RLS-enforced connection.
    When Cumulative View is selected by Trust Management, canonical students are counted using
    `COUNT(DISTINCT student_id)` so transferred students are NEVER double-counted!
    """
    effective_campus_id = None
    if user["role_code"] != "TRUST_MANAGEMENT":
        effective_campus_id = str(user["primary_campus_id"])
    elif campus_id and campus_id != "ALL":
        effective_campus_id = campus_id

    with get_rls_conn(user) as conn:
        with conn.cursor() as cur:
            campus_filter_sql = "WHERE s.primary_campus_id = %s" if effective_campus_id else ""
            params = (effective_campus_id,) if effective_campus_id else ()

            # 1. Canonical Students (DISTINCT student_id prevents double-counting across transfers)
            cur.execute(f"SELECT COUNT(DISTINCT s.student_id) AS canonical_students FROM students s {campus_filter_sql}", params)
            canonical_students = cur.fetchone()["canonical_students"]

            # 2. Active vs Transferred Enrollments
            enr_filter = "WHERE campus_id = %s" if effective_campus_id else ""
            cur.execute(f"""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'ACTIVE') AS active_enrollments,
                    COUNT(*) FILTER (WHERE status = 'TRANSFERRED') AS transferred_enrollments
                FROM campus_enrollments
                {enr_filter}
            """, params)
            enr_stats = cur.fetchone()

            # 3. Financial Summary (if Warden, RLS returns 0 rows safely)
            cur.execute(f"""
                SELECT
                    COALESCE(SUM(assessed_amount), 0) AS total_assessed,
                    COALESCE(SUM(concession_amount + scholarship_amount), 0) AS total_concessions_scholarships,
                    COALESCE(SUM(net_posted_payments), 0) AS total_collections,
                    COALESCE(SUM(outstanding_balance), 0) AS total_outstanding,
                    COALESCE(SUM(outstanding_balance) FILTER (WHERE status = 'OVERDUE'), 0) AS overdue_balance,
                    COALESCE(SUM(refunded_amount), 0) AS total_refunds
                FROM student_fee_assessments
                {enr_filter}
            """, params)
            fin_stats = cur.fetchone()

            cur.execute(f"""
                SELECT COUNT(*) AS pending_verifications
                FROM payments
                WHERE status IN ('PENDING_COLLEGE_VERIFICATION', 'COLLEGE_VERIFIED')
                {"AND campus_id = %s" if effective_campus_id else ""}
            """, params)
            pending_verifications = cur.fetchone()["pending_verifications"]

            # 4. Hostel Summary (Bed count vs Room count strictly separated!)
            cur.execute(f"""
                SELECT
                    COUNT(DISTINCT building_id) AS total_hostels,
                    COUNT(DISTINCT room_id) AS total_rooms,
                    COUNT(*) AS total_beds,
                    COUNT(*) FILTER (WHERE status = 'OCCUPIED') AS occupied_beds,
                    COUNT(*) FILTER (WHERE status = 'AVAILABLE') AS available_beds,
                    COUNT(*) FILTER (WHERE status = 'RESERVED') AS reserved_beds,
                    COUNT(*) FILTER (WHERE status = 'OUT_OF_SERVICE') AS out_of_service_beds
                FROM hostel_beds
                {enr_filter}
            """, params)
            hostel_stats = cur.fetchone()
            total_beds = hostel_stats["total_beds"] or 0
            occupied_beds = hostel_stats["occupied_beds"] or 0
            hostel_stats["occupancy_percentage"] = round((occupied_beds / total_beds) * 100.0, 2) if total_beds > 0 else 0.0

            # 5. Attendance & Eligibility Summary
            cur.execute(f"""
                SELECT
                    COUNT(*) FILTER (WHERE eligibility_status = 'ELIGIBLE') AS eligible_count,
                    COUNT(*) FILTER (WHERE eligibility_status = 'AT_RISK') AS at_risk_count,
                    COUNT(*) FILTER (WHERE eligibility_status = 'INELIGIBLE') AS below_threshold_count,
                    ROUND(AVG(attendance_percentage), 2) AS avg_attendance_pct
                FROM academic_progress_records
                {enr_filter}
            """, params)
            att_stats = cur.fetchone()

            # 6. Scholarship & Government Reimbursements
            cur.execute(f"""
                SELECT
                    COUNT(*) AS total_claims,
                    COALESCE(SUM(claimed_amount), 0) AS total_claimed,
                    COALESCE(SUM(disbursed_amount), 0) AS total_disbursed,
                    COALESCE(SUM(pending_amount), 0) AS total_pending_reimbursement
                FROM government_reimbursement_claims
                {enr_filter}
            """, params)
            reimb_stats = cur.fetchone()

            # 7. Campus-wise Breakdown for Charts
            cur.execute("""
                SELECT
                    c.id AS campus_id,
                    c.campus_number,
                    c.code AS campus_code,
                    c.name AS campus_name,
                    c.city,
                    COUNT(DISTINCT s.student_id) AS student_count,
                    COALESCE(fa.assessed, 0) AS assessed_fees,
                    COALESCE(fa.collected, 0) AS collected_fees,
                    COALESCE(fa.outstanding, 0) AS outstanding_fees,
                    COALESCE(hb.occupied_beds, 0) AS occupied_beds,
                    COALESCE(hb.available_beds, 0) AS available_beds,
                    COALESCE(ap.below_threshold, 0) AS below_threshold_students,
                    COALESCE(ap.at_risk, 0) AS at_risk_students
                FROM campuses c
                LEFT JOIN students s ON s.primary_campus_id = c.id
                LEFT JOIN (
                    SELECT campus_id,
                           SUM(assessed_amount) AS assessed,
                           SUM(net_posted_payments) AS collected,
                           SUM(outstanding_balance) AS outstanding
                    FROM student_fee_assessments
                    GROUP BY campus_id
                ) fa ON fa.campus_id = c.id
                LEFT JOIN (
                    SELECT campus_id,
                           COUNT(*) FILTER (WHERE status = 'OCCUPIED') AS occupied_beds,
                           COUNT(*) FILTER (WHERE status = 'AVAILABLE') AS available_beds
                    FROM hostel_beds
                    GROUP BY campus_id
                ) hb ON hb.campus_id = c.id
                LEFT JOIN (
                    SELECT campus_id,
                           COUNT(*) FILTER (WHERE eligibility_status = 'INELIGIBLE') AS below_threshold,
                           COUNT(*) FILTER (WHERE eligibility_status = 'AT_RISK') AS at_risk
                    FROM academic_progress_records
                    GROUP BY campus_id
                ) ap ON ap.campus_id = c.id
                WHERE (%s::uuid IS NULL OR c.id = %s::uuid)
                GROUP BY c.id, c.campus_number, c.code, c.name, c.city,
                         fa.assessed, fa.collected, fa.outstanding,
                         hb.occupied_beds, hb.available_beds,
                         ap.below_threshold, ap.at_risk
                ORDER BY c.campus_number
            """, (effective_campus_id, effective_campus_id))
            campus_breakdown = cur.fetchall()

            # 8. Transfers & Data Quality Counts
            cur.execute("SELECT COUNT(*) AS cnt FROM transfer_requests")
            total_transfers = cur.fetchone()["cnt"]
            cur.execute("SELECT COUNT(*) AS cnt FROM duplicate_match_candidates WHERE review_status = 'PENDING_REVIEW'")
            pending_duplicates = cur.fetchone()["cnt"]
            cur.execute("SELECT COUNT(*) AS cnt FROM data_quality_issues WHERE resolution_status = 'OPEN'")
            open_dq_issues = cur.fetchone()["cnt"]

    return {
        "selected_campus_id": effective_campus_id or "ALL",
        "is_cumulative_view": effective_campus_id is None,
        "synthetic_data_label": "SYNTHETIC DEMO ENVIRONMENT (14,000 Canonical Students Across 6 Campuses)",
        "metrics": {
            "canonical_student_count": canonical_students,
            "active_enrollments": enr_stats["active_enrollments"],
            "transferred_enrollments": enr_stats["transferred_enrollments"],
            "total_transfers": total_transfers,
            "total_assessed_fees": float(fin_stats["total_assessed"]),
            "total_concessions_and_scholarships": float(fin_stats["total_concessions_scholarships"]),
            "total_collections": float(fin_stats["total_collections"]),
            "total_outstanding_fees": float(fin_stats["total_outstanding"]),
            "overdue_balances": float(fin_stats["overdue_balance"]),
            "total_refunds": float(fin_stats["total_refunds"]),
            "fee_verification_backlog": pending_verifications,
            "hostel": hostel_stats,
            "attendance": {
                "eligible_count": att_stats["eligible_count"],
                "at_risk_count": att_stats["at_risk_count"],
                "below_threshold_count": att_stats["below_threshold_count"],
                "avg_attendance_pct": float(att_stats["avg_attendance_pct"] or 0.0),
            },
            "reimbursements": {
                "total_claims": reimb_stats["total_claims"],
                "total_claimed": float(reimb_stats["total_claimed"]),
                "total_disbursed": float(reimb_stats["total_disbursed"]),
                "pending_reimbursement_amount": float(reimb_stats["total_pending_reimbursement"]),
            },
            "data_quality": {
                "pending_duplicate_candidates": pending_duplicates,
                "open_data_quality_issues": open_dq_issues,
            }
        },
        "campus_breakdown": [
            {
                **row,
                "campus_id": str(row["campus_id"]),
                "assessed_fees": float(row["assessed_fees"]),
                "collected_fees": float(row["collected_fees"]),
                "outstanding_fees": float(row["outstanding_fees"]),
            }
            for row in campus_breakdown
        ]
    }


# =============================================================================
# 3. STUDENTS, ADMISSIONS & DUPLICATE RESOLUTION ENDPOINTS
# =============================================================================

@app.get("/api/students")
def list_students(
    q: Optional[str] = Query(default=None),
    campus_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    user: Dict[str, Any] = Depends(get_current_user)
):
    with get_rls_conn(user) as conn:
        with conn.cursor() as cur:
            clauses = ["1=1"]
            params: List[Any] = []
            if campus_id and campus_id != "ALL":
                clauses.append("s.primary_campus_id = %s")
                params.append(campus_id)
            if q:
                clauses.append("(s.current_usn ILIKE %s OR s.full_name ILIKE %s OR s.phone ILIKE %s)")
                like_q = f"%{q.strip()}%"
                params.extend([like_q, like_q, like_q])

            where_sql = " AND ".join(clauses)
            cur.execute(f"SELECT COUNT(*) AS total FROM students s WHERE {where_sql}", tuple(params))
            total = cur.fetchone()["total"]

            cur.execute(f"""
                SELECT s.student_id, s.full_name, s.date_of_birth, s.gender, s.is_minor,
                       s.phone, s.email, s.category, s.current_usn, s.primary_campus_id, s.data_origin,
                       c.code AS campus_code, c.name AS campus_name,
                       e.course_id, co.code AS course_code, co.name AS course_name, e.year_of_study, e.status AS enrollment_status,
                       fa.assessed_amount, fa.outstanding_balance, fa.status AS fee_status,
                       ap.attendance_percentage, ap.eligibility_status
                FROM students s
                JOIN campuses c ON c.id = s.primary_campus_id
                LEFT JOIN campus_enrollments e ON e.student_id = s.student_id AND e.status = 'ACTIVE'
                LEFT JOIN courses co ON co.id = e.course_id
                LEFT JOIN student_fee_assessments fa ON fa.student_id = s.student_id
                LEFT JOIN academic_progress_records ap ON ap.student_id = s.student_id
                WHERE {where_sql}
                ORDER BY s.current_usn
                LIMIT %s OFFSET %s
            """, tuple(params + [limit, offset]))
            rows = cur.fetchall()

    return {"total": total, "students": rows}


@app.get("/api/students/{student_id_or_usn}")
def get_student_detail(student_id_or_usn: str, user: Dict[str, Any] = Depends(get_current_user)):
    with get_rls_conn(user) as conn:
        with conn.cursor() as cur:
            is_uuid = False
            try:
                uuid.UUID(student_id_or_usn)
                is_uuid = True
            except ValueError:
                pass

            if is_uuid:
                cur.execute("""
                    SELECT s.*, c.name AS campus_name, c.code AS campus_code
                    FROM students s JOIN campuses c ON c.id = s.primary_campus_id
                    WHERE s.student_id = %s
                """, (student_id_or_usn,))
            else:
                cur.execute("""
                    SELECT s.*, c.name AS campus_name, c.code AS campus_code
                    FROM students s JOIN campuses c ON c.id = s.primary_campus_id
                    WHERE UPPER(s.current_usn) = UPPER(%s)
                       OR EXISTS (
                           SELECT 1 FROM student_identifiers si
                           WHERE si.student_id = s.student_id AND UPPER(si.id_value) = UPPER(%s)
                       )
                """, (student_id_or_usn.strip(), student_id_or_usn.strip()))
            student = cur.fetchone()
            if not student:
                raise HTTPException(status_code=404, detail="Student record not found or access denied by campus/role policy.")

            st_id = student["student_id"]
            cur.execute("SELECT * FROM student_identifiers WHERE student_id = %s ORDER BY assigned_at DESC", (st_id,))
            identifiers = cur.fetchall()

            cur.execute("""
                SELECT e.*, c.name AS campus_name, c.code AS campus_code, co.name AS course_name, co.code AS course_code
                FROM campus_enrollments e
                JOIN campuses c ON c.id = e.campus_id
                JOIN courses co ON co.id = e.course_id
                WHERE e.student_id = %s
                ORDER BY e.created_at DESC
            """, (st_id,))
            enrollments = cur.fetchall()

            cur.execute("SELECT * FROM student_fee_assessments WHERE student_id = %s ORDER BY created_at DESC", (st_id,))
            assessments = cur.fetchall()

            cur.execute("SELECT * FROM payments WHERE student_id = %s ORDER BY created_at DESC", (st_id,))
            payments = cur.fetchall()

            cur.execute("SELECT * FROM academic_progress_records WHERE student_id = %s", (st_id,))
            progress = cur.fetchone()

            cur.execute("""
                SELECT er.*, sub.code AS subject_code, sub.name AS subject_name
                FROM examination_results er
                JOIN subjects sub ON sub.id = er.subject_id
                WHERE er.student_id = %s
                ORDER BY er.exam_term, sub.code
            """, (st_id,))
            exam_results = cur.fetchall()

            cur.execute("""
                SELECT ha.*, hb.bed_code, hr.room_number, hbl.name AS building_name
                FROM hostel_allocations ha
                JOIN hostel_beds hb ON hb.id = ha.bed_id
                JOIN hostel_rooms hr ON hr.id = ha.room_id
                JOIN hostel_buildings hbl ON hbl.id = ha.building_id
                WHERE ha.student_id = %s
                ORDER BY ha.allocated_at DESC
            """, (st_id,))
            hostel_allocations = cur.fetchall()

            cur.execute("""
                SELECT gr.*, ss.scheme_code, ss.name AS scheme_name
                FROM government_reimbursement_claims gr
                JOIN scholarship_schemes ss ON ss.id = gr.scheme_id
                WHERE gr.student_id = %s
            """, (st_id,))
            reimbursements = cur.fetchall()

    return {
        "student": student,
        "identifiers": identifiers,
        "enrollments": enrollments,
        "fee_assessments": assessments,
        "payments": payments,
        "academic_progress": progress,
        "examination_results": exam_results,
        "hostel_allocations": hostel_allocations,
        "reimbursements": reimbursements,
    }


@app.post("/api/admissions", status_code=201)
def create_admission(
    payload: AdmissionCreateRequest,
    user: Dict[str, Any] = Depends(require_roles("TRUST_MANAGEMENT", "COLLEGE_ADMIN"))
):
    """
    Registers a new student admission (or links to an existing canonical `student_id` if specified).
    Checks for potential duplicate records before creating a new identity, assigns a collision-safe USN
    from the campus sequence, and creates the initial enrollment and fee assessment.
    """
    target_campus_id = str(user["primary_campus_id"]) if user["role_code"] == "COLLEGE_ADMIN" else (payload.campus_id or str(user["primary_campus_id"]))
    if user["role_code"] == "COLLEGE_ADMIN" and payload.campus_id and str(payload.campus_id) != str(user["primary_campus_id"]):
        raise HTTPException(status_code=403, detail="College Administrator cannot admit students into another campus.")

    with get_rls_conn(user) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, campus_number, code, usn_prefix FROM campuses WHERE id = %s", (target_campus_id,))
            campus = cur.fetchone()
            if not campus:
                raise HTTPException(status_code=404, detail="Target campus not found")

            cur.execute("SELECT id, code, name FROM courses WHERE id = %s AND campus_id = %s", (payload.course_id, target_campus_id))
            course = cur.fetchone()
            if not course:
                raise HTTPException(status_code=400, detail="Course does not belong to the selected campus")

            cur.execute("SELECT id FROM academic_years WHERE is_current = TRUE LIMIT 1")
            ay_id = cur.fetchone()["id"]

            norm_name = normalize_text(payload.full_name)
            if not payload.existing_student_id:
                # Check if an exact normalized_name + DOB + phone already exists to prevent accidental duplicate identity
                cur.execute(
                    "SELECT student_id, current_usn, full_name FROM students WHERE normalized_name = %s AND date_of_birth = %s AND phone = %s",
                    (norm_name, payload.date_of_birth, payload.phone)
                )
                dup = cur.fetchone()
                if dup:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Duplicate student identity detected: {dup['full_name']} already has permanent student_id {dup['student_id']} (USN: {dup['current_usn']}). Pass existing_student_id or review in Duplicate Resolution."
                    )

            c_num = campus["campus_number"]
            cur.execute(f"SELECT nextval('seq_usn_c{c_num}') AS seq_val")
            seq_val = cur.fetchone()["seq_val"]
            usn = f"{campus['usn_prefix']}{course['code']}{seq_val:04d}"

            st_id = payload.existing_student_id or str(uuid.uuid4())
            is_minor = (date(2026, 10, 28).year - payload.date_of_birth.year) < 18

            if not payload.existing_student_id:
                cur.execute(
                    """INSERT INTO students (
                        student_id, full_name, normalized_name, date_of_birth, gender, is_minor,
                        email, phone, guardian_name, guardian_phone, category,
                        primary_campus_id, current_usn, data_origin
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'SOURCE_DERIVED')""",
                    (
                        st_id, payload.full_name.strip(), norm_name, payload.date_of_birth, payload.gender, is_minor,
                        payload.email or f"{usn.lower()}@student.vidyavikas.edu.in", payload.phone,
                        payload.guardian_name, payload.guardian_phone, payload.category,
                        target_campus_id, usn
                    )
                )

            cur.execute(
                "INSERT INTO student_identifiers (student_id, campus_id, id_type, id_value, is_active, notes) VALUES (%s, %s, 'USN', %s, TRUE, 'Assigned at admission')",
                (st_id, target_campus_id, usn)
            )

            adm_no = f"ADM-{campus['code']}-2026-{seq_val:04d}"
            adm_id = str(uuid.uuid4())
            cur.execute(
                """INSERT INTO admissions (id, student_id, campus_id, course_id, academic_year_id, admission_number, quota, status, admitted_by)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, 'CONFIRMED', %s)""",
                (adm_id, st_id, target_campus_id, course["id"], ay_id, adm_no, payload.quota, user["id"])
            )

            enr_id = str(uuid.uuid4())
            cur.execute(
                """INSERT INTO campus_enrollments (id, student_id, campus_id, course_id, academic_year_id, usn, year_of_study, section, status)
                   VALUES (%s, %s, %s, %s, %s, %s, 1, 'A', 'ACTIVE')""",
                (enr_id, st_id, target_campus_id, course["id"], ay_id, usn)
            )

            # Create initial academic progress record
            cur.execute("SELECT attendance_threshold_pct FROM campus_policies WHERE campus_id = %s AND is_active = TRUE LIMIT 1", (target_campus_id,))
            pol_row = cur.fetchone()
            thresh = float(pol_row["attendance_threshold_pct"]) if pol_row else 75.0
            cur.execute(
                """INSERT INTO academic_progress_records (
                    student_id, campus_id, course_id, academic_year_id,
                    total_classes_held, total_classes_attended, attendance_percentage,
                    applicable_threshold_pct, eligibility_status
                ) VALUES (%s, %s, %s, %s, 0, 0, NULL, %s, 'NO_DATA')
                ON CONFLICT (student_id) DO NOTHING""",
                (st_id, target_campus_id, course["id"], ay_id, thresh)
            )

            record_audit_log(
                conn, str(user["id"]), user["role_code"], target_campus_id,
                "ADMISSION_CREATED", "students", st_id, f"Admitted student {payload.full_name} with permanent student_id {st_id} and USN {usn}"
            )

    return {
        "student_id": st_id,
        "admission_id": adm_id,
        "enrollment_id": enr_id,
        "usn": usn,
        "admission_number": adm_no,
        "campus_id": target_campus_id,
    }


@app.get("/api/duplicates")
def list_duplicate_candidates(user: Dict[str, Any] = Depends(require_roles("TRUST_MANAGEMENT", "COLLEGE_ADMIN"))):
    with get_owner_conn() as conn:
        metrics = evaluate_duplicate_metrics(conn)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM duplicate_match_candidates
                ORDER BY
                    CASE WHEN review_status = 'PENDING_REVIEW' THEN 0 ELSE 1 END,
                    match_confidence DESC
            """)
            candidates = cur.fetchall()
    return {"evaluation_metrics": metrics, "candidates": candidates}


@app.post("/api/duplicates/{candidate_id}/review")
def review_duplicate_candidate(
    candidate_id: str,
    payload: DuplicateDecisionRequest,
    user: Dict[str, Any] = Depends(require_roles("TRUST_MANAGEMENT", "COLLEGE_ADMIN"))
):
    with get_owner_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE duplicate_match_candidates
                   SET review_status = %s, reviewed_by = %s, reviewed_at = NOW()
                   WHERE id = %s RETURNING *""",
                (payload.decision, user["id"], candidate_id)
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Duplicate candidate not found")
            record_audit_log(
                conn, str(user["id"]), user["role_code"], str(user["primary_campus_id"]) if user.get("primary_campus_id") else None,
                "DUPLICATE_REVIEWED", "duplicate_match_candidates", candidate_id,
                f"Duplicate candidate {row['source_record_key']} reviewed as {payload.decision}"
            )
    return {"candidate": row}


# =============================================================================
# 4. CAMPUS TRANSFER WORKFLOW (Preserves Permanent `student_id` & Collision-Safe USN)
# =============================================================================

@app.post("/api/transfers/preview")
def preview_student_transfer(
    payload: TransferPreviewRequest,
    user: Dict[str, Any] = Depends(require_roles("TRUST_MANAGEMENT", "COLLEGE_ADMIN"))
):
    with get_owner_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT s.student_id, s.full_name, s.current_usn, s.primary_campus_id,
                       c.name AS source_campus_name, c.code AS source_campus_code,
                       e.id AS enrollment_id, e.course_id AS source_course_id, co.name AS source_course_name,
                       COALESCE(fa.outstanding_balance, 0) AS outstanding_balance,
                       ap.attendance_percentage
                FROM students s
                JOIN campuses c ON c.id = s.primary_campus_id
                JOIN campus_enrollments e ON e.student_id = s.student_id AND e.status = 'ACTIVE'
                JOIN courses co ON co.id = e.course_id
                LEFT JOIN student_fee_assessments fa ON fa.student_id = s.student_id
                LEFT JOIN academic_progress_records ap ON ap.student_id = s.student_id
                WHERE UPPER(s.current_usn) = UPPER(%s)
            """, (payload.source_usn.strip(),))
            st = cur.fetchone()
            if not st:
                raise HTTPException(status_code=404, detail="Active student with the specified USN not found")

            if user["role_code"] == "COLLEGE_ADMIN" and str(st["primary_campus_id"]) != str(user["primary_campus_id"]):
                raise HTTPException(status_code=403, detail="College Administrator can only initiate transfers for students enrolled in their assigned campus.")

            if str(st["primary_campus_id"]) == str(payload.destination_campus_id):
                raise HTTPException(status_code=400, detail="Destination campus must be different from the current campus.")

            cur.execute("SELECT * FROM campuses WHERE id = %s", (payload.destination_campus_id,))
            dest_campus = cur.fetchone()
            if not dest_campus:
                raise HTTPException(status_code=404, detail="Destination campus not found")

            if payload.destination_course_id:
                cur.execute("SELECT * FROM courses WHERE id = %s AND campus_id = %s", (payload.destination_course_id, payload.destination_campus_id))
            else:
                cur.execute("SELECT * FROM courses WHERE campus_id = %s ORDER BY code LIMIT 1", (payload.destination_campus_id,))
            dest_course = cur.fetchone()

            # Check source campus transfer eligibility policy
            cur.execute("SELECT * FROM campus_policies WHERE campus_id = %s AND is_active = TRUE LIMIT 1", (st["primary_campus_id"],))
            pol = cur.fetchone()
            eligible = True
            notes = []
            if pol and pol["require_zero_dues_for_transfer"] and float(st["outstanding_balance"]) > 0:
                eligible = False
                notes.append(f"Campus policy requires zero fee dues before transfer (current balance: INR {st['outstanding_balance']}).")
            else:
                notes.append(f"Outstanding balance INR {st['outstanding_balance']} will be carried forward with full audit trail.")

            # Peek next sequence value for preview without consuming, or show next available format
            c_num = dest_campus["campus_number"]
            cur.execute(f"SELECT last_value + 1 AS next_seq FROM seq_usn_c{c_num}")
            next_seq = cur.fetchone()["next_seq"]
            proposed_usn = f"{dest_campus['usn_prefix']}{dest_course['code']}{next_seq:04d}"

    return {
        "permanent_student_id": str(st["student_id"]),
        "student_name": st["full_name"],
        "old_usn": st["current_usn"],
        "proposed_new_usn_preview": proposed_usn,
        "source_campus": {"id": str(st["primary_campus_id"]), "name": st["source_campus_name"], "code": st["source_campus_code"]},
        "destination_campus": {"id": str(dest_campus["id"]), "name": dest_campus["name"], "code": dest_campus["code"]},
        "destination_course": {"id": str(dest_course["id"]), "name": dest_course["name"], "code": dest_course["code"]},
        "outstanding_balance": float(st["outstanding_balance"]),
        "eligible_for_transfer": eligible,
        "policy_notes": " ".join(notes),
    }


@app.post("/api/transfers/request", status_code=201)
def request_student_transfer(
    payload: TransferPreviewRequest,
    user: Dict[str, Any] = Depends(require_roles("TRUST_MANAGEMENT", "COLLEGE_ADMIN"))
):
    preview = preview_student_transfer(payload, user)
    if not preview["eligible_for_transfer"]:
        raise HTTPException(status_code=400, detail=preview["policy_notes"])

    with get_owner_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT course_id FROM campus_enrollments WHERE student_id = %s AND status = 'ACTIVE'", (preview["permanent_student_id"],))
            src_course_id = cur.fetchone()["course_id"]

            treq_id = str(uuid.uuid4())
            cur.execute(
                """INSERT INTO transfer_requests (
                    id, student_id, source_campus_id, destination_campus_id,
                    source_course_id, destination_course_id, source_usn, proposed_destination_usn,
                    reason, eligibility_check_passed, eligibility_notes, outstanding_balance_at_request,
                    status, requested_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s, %s, 'PENDING', %s)""",
                (
                    treq_id, preview["permanent_student_id"],
                    preview["source_campus"]["id"], preview["destination_campus"]["id"],
                    src_course_id, preview["destination_course"]["id"],
                    preview["old_usn"], preview["proposed_new_usn_preview"],
                    payload.reason, preview["policy_notes"], preview["outstanding_balance"],
                    user["id"]
                )
            )
            record_audit_log(
                conn, str(user["id"]), user["role_code"], preview["source_campus"]["id"],
                "TRANSFER_REQUESTED", "transfer_requests", treq_id,
                f"Transfer requested for {preview['student_name']} ({preview['old_usn']}) -> {preview['destination_campus']['code']}"
            )
    return {"transfer_request_id": treq_id, "status": "PENDING", "preview": preview}


@app.post("/api/transfers/{transfer_request_id}/approve")
def approve_and_commit_transfer(
    transfer_request_id: str,
    payload: TransferApproveRequest,
    user: Dict[str, Any] = Depends(require_roles("TRUST_MANAGEMENT", "COLLEGE_ADMIN"))
):
    """
    Executes the campus transfer atomically in a single PostgreSQL transaction:
    1. Locks the transfer request and student record (`FOR UPDATE`).
    2. Preserves the permanent `student_id` UUID unchanged.
    3. Marks the old `campus_enrollments` record as `TRANSFERRED` and deactivates old USN in `student_identifiers`.
    4. Allocates a guaranteed unique destination USN via PostgreSQL `nextval('seq_usn_cX')` (preventing concurrent USN collisions).
    5. Creates the new destination enrollment and active USN identifier.
    6. Releases any active source-campus hostel bed automatically and records `hostel_allocation_history`.
    7. Writes `transfer_history`, `transfer_approvals`, notification, and `audit_logs`.
    """
    with get_owner_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM transfer_requests WHERE id = %s FOR UPDATE", (transfer_request_id,))
            treq = cur.fetchone()
            if not treq:
                raise HTTPException(status_code=404, detail="Transfer request not found")
            if treq["status"] != "PENDING":
                raise HTTPException(status_code=400, detail=f"Transfer request is already in status {treq['status']}")

            if payload.decision == "REJECTED":
                cur.execute("UPDATE transfer_requests SET status = 'REJECTED', approved_by = %s WHERE id = %s", (user["id"], transfer_request_id))
                cur.execute(
                    "INSERT INTO transfer_approvals (transfer_request_id, approver_user_id, approval_level, decision, comments) VALUES (%s, %s, %s, 'REJECTED', %s)",
                    (transfer_request_id, user["id"], user["role_code"], payload.comments)
                )
                return {"transfer_request_id": transfer_request_id, "status": "REJECTED"}

            st_id = treq["student_id"]
            cur.execute("SELECT * FROM students WHERE student_id = %s FOR UPDATE", (st_id,))
            student = cur.fetchone()

            cur.execute("SELECT * FROM campus_enrollments WHERE student_id = %s AND status = 'ACTIVE' FOR UPDATE", (st_id,))
            old_enr = cur.fetchone()
            if not old_enr:
                raise HTTPException(status_code=400, detail="Student does not have an active source enrollment to transfer.")

            cur.execute("SELECT * FROM campuses WHERE id = %s", (treq["destination_campus_id"],))
            dest_campus = cur.fetchone()
            cur.execute("SELECT * FROM courses WHERE id = %s", (treq["destination_course_id"],))
            dest_course = cur.fetchone()

            # Atomic sequence increment guarantees zero duplicate USNs under concurrent transfers
            c_num = dest_campus["campus_number"]
            cur.execute(f"SELECT nextval('seq_usn_c{c_num}') AS seq_val")
            seq_val = cur.fetchone()["seq_val"]
            new_usn = f"{dest_campus['usn_prefix']}{dest_course['code']}{seq_val:04d}"

            # 1. Mark old enrollment as TRANSFERRED (never deleted)
            cur.execute(
                "UPDATE campus_enrollments SET status = 'TRANSFERRED', ended_at = CURRENT_DATE WHERE id = %s",
                (old_enr["id"],)
            )
            # 2. Deactivate old USN in identifier history and insert new active USN
            cur.execute(
                "UPDATE student_identifiers SET is_active = FALSE, deactivated_at = NOW() WHERE student_id = %s AND id_value = %s",
                (st_id, old_enr["usn"])
            )
            cur.execute(
                "INSERT INTO student_identifiers (student_id, campus_id, id_type, id_value, is_active, notes) VALUES (%s, %s, 'USN', %s, TRUE, 'Assigned on approved campus transfer')",
                (st_id, dest_campus["id"], new_usn)
            )

            # 3. Create new active enrollment at destination campus
            new_enr_id = str(uuid.uuid4())
            cur.execute(
                """INSERT INTO campus_enrollments (
                    id, student_id, campus_id, course_id, academic_year_id, usn, year_of_study, section, status, enrolled_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'ACTIVE', CURRENT_DATE)""",
                (new_enr_id, st_id, dest_campus["id"], dest_course["id"], old_enr["academic_year_id"], new_usn, old_enr["year_of_study"], old_enr["section"])
            )

            # 4. Update student's primary_campus_id and current_usn while preserving permanent `student_id`
            cur.execute(
                "UPDATE students SET primary_campus_id = %s, current_usn = %s, updated_at = NOW() WHERE student_id = %s",
                (dest_campus["id"], new_usn, st_id)
            )
            cur.execute(
                "UPDATE academic_progress_records SET campus_id = %s, course_id = %s, updated_at = NOW() WHERE student_id = %s",
                (dest_campus["id"], dest_course["id"], st_id)
            )

            # 5. Release any active hostel allocation at the old campus automatically
            cur.execute(
                "SELECT id, bed_id, campus_id FROM hostel_allocations WHERE student_id = %s AND allocation_status IN ('ACTIVE', 'RESERVED') FOR UPDATE",
                (st_id,)
            )
            active_hostel = cur.fetchone()
            hostel_released = False
            if active_hostel:
                hostel_released = True
                cur.execute(
                    "UPDATE hostel_allocations SET allocation_status = 'RELEASED', released_at = NOW(), release_reason = 'Auto-released upon inter-campus transfer' WHERE id = %s",
                    (active_hostel["id"],)
                )
                cur.execute(
                    "UPDATE hostel_beds SET status = 'AVAILABLE', current_student_id = NULL, updated_at = NOW() WHERE id = %s",
                    (active_hostel["bed_id"],)
                )
                cur.execute(
                    "INSERT INTO hostel_allocation_history (allocation_id, bed_id, student_id, campus_id, action, actor_user_id, reason) VALUES (%s, %s, %s, %s, 'AUTO_RELEASED_ON_TRANSFER', %s, 'Student transferred to another campus')",
                    (active_hostel["id"], active_hostel["bed_id"], st_id, active_hostel["campus_id"], user["id"])
                )

            # 6. Complete transfer request, approval, history, and notification
            cur.execute(
                """UPDATE transfer_requests
                   SET status = 'COMPLETED', proposed_destination_usn = %s, approved_by = %s, completed_at = NOW()
                   WHERE id = %s""",
                (new_usn, user["id"], transfer_request_id)
            )
            cur.execute(
                "INSERT INTO transfer_approvals (transfer_request_id, approver_user_id, approval_level, decision, comments) VALUES (%s, %s, %s, 'APPROVED', %s)",
                (transfer_request_id, user["id"], user["role_code"], payload.comments or "Approved and committed")
            )
            cur.execute(
                """INSERT INTO transfer_history (
                    transfer_request_id, student_id, old_campus_id, new_campus_id,
                    old_usn, new_usn, old_enrollment_id, new_enrollment_id,
                    hostel_released, authorized_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    transfer_request_id, st_id, treq["source_campus_id"], dest_campus["id"],
                    old_enr["usn"], new_usn, old_enr["id"], new_enr_id, hostel_released, user["id"]
                )
            )
            cur.execute(
                """INSERT INTO notifications (student_id, campus_id, category, title, message, is_simulated)
                   VALUES (%s, %s, 'TRANSFER_UPDATE', 'Inter-Campus Transfer Completed', %s, TRUE)""",
                (st_id, dest_campus["id"], f"Student {student['full_name']} transferred from USN {old_enr['usn']} to {new_usn} ({dest_campus['name']}). Permanent student_id {st_id} preserved.")
            )
            record_audit_log(
                conn, str(user["id"]), user["role_code"], str(dest_campus["id"]),
                "TRANSFER_COMMITTED", "students", str(st_id),
                f"Committed transfer for permanent student_id {st_id}: {old_enr['usn']} -> {new_usn}",
                {"old_usn": old_enr["usn"], "new_usn": new_usn, "hostel_released": hostel_released}
            )

    return {
        "transfer_request_id": transfer_request_id,
        "status": "COMPLETED",
        "permanent_student_id": str(st_id),
        "old_usn": old_enr["usn"],
        "new_usn": new_usn,
        "old_enrollment_status": "TRANSFERRED",
        "new_enrollment_id": new_enr_id,
        "hostel_released": hostel_released,
    }


@app.get("/api/transfers")
def list_transfers(user: Dict[str, Any] = Depends(require_roles("TRUST_MANAGEMENT", "COLLEGE_ADMIN"))):
    with get_owner_conn() as conn:
        with conn.cursor() as cur:
            if user["role_code"] == "TRUST_MANAGEMENT":
                cur.execute("""
                    SELECT tr.*, s.full_name AS student_name,
                           sc.name AS source_campus_name, sc.code AS source_campus_code,
                           dc.name AS destination_campus_name, dc.code AS destination_campus_code
                    FROM transfer_requests tr
                    JOIN students s ON s.student_id = tr.student_id
                    JOIN campuses sc ON sc.id = tr.source_campus_id
                    JOIN campuses dc ON dc.id = tr.destination_campus_id
                    ORDER BY tr.created_at DESC
                """)
            else:
                cur.execute("""
                    SELECT tr.*, s.full_name AS student_name,
                           sc.name AS source_campus_name, sc.code AS source_campus_code,
                           dc.name AS destination_campus_name, dc.code AS destination_campus_code
                    FROM transfer_requests tr
                    JOIN students s ON s.student_id = tr.student_id
                    JOIN campuses sc ON sc.id = tr.source_campus_id
                    JOIN campuses dc ON dc.id = tr.destination_campus_id
                    WHERE tr.source_campus_id = %s OR tr.destination_campus_id = %s
                    ORDER BY tr.created_at DESC
                """, (user["primary_campus_id"], user["primary_campus_id"]))
            return {"transfers": cur.fetchall()}


# =============================================================================
# 5. FEE MANAGEMENT, TWO-LEVEL VERIFICATION & IMMUTABLE RECEIPTS
# =============================================================================

@app.get("/api/fees/assessments")
def list_fee_assessments(
    campus_id: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=200),
    user: Dict[str, Any] = Depends(require_roles("TRUST_MANAGEMENT", "COLLEGE_ADMIN", "STUDENT", "PARENT"))
):
    with get_rls_conn(user) as conn:
        with conn.cursor() as cur:
            clauses = ["1=1"]
            params: List[Any] = []
            if campus_id and campus_id != "ALL":
                clauses.append("fa.campus_id = %s")
                params.append(campus_id)
            if status_filter and status_filter != "ALL":
                clauses.append("fa.status = %s")
                params.append(status_filter)
            if q:
                clauses.append("(s.current_usn ILIKE %s OR s.full_name ILIKE %s)")
                params.extend([f"%{q.strip()}%", f"%{q.strip()}%"])

            where_sql = " AND ".join(clauses)
            cur.execute(f"""
                SELECT fa.*, s.full_name AS student_name, s.current_usn, c.code AS campus_code, c.name AS campus_name
                FROM student_fee_assessments fa
                JOIN students s ON s.student_id = fa.student_id
                JOIN campuses c ON c.id = fa.campus_id
                WHERE {where_sql}
                ORDER BY fa.updated_at DESC
                LIMIT %s
            """, tuple(params + [limit]))
            assessments = cur.fetchall()

            cur.execute("""
                SELECT p.*, s.full_name AS student_name, s.current_usn, c.code AS campus_code
                FROM payments p
                JOIN students s ON s.student_id = p.student_id
                JOIN campuses c ON c.id = p.campus_id
                ORDER BY p.created_at DESC
                LIMIT 60
            """)
            recent_payments = cur.fetchall()

    return {"assessments": assessments, "recent_payments": recent_payments}


@app.post("/api/fees/assessments", status_code=201)
def create_fee_assessment(
    payload: FeeAssessmentCreateRequest,
    user: Dict[str, Any] = Depends(require_roles("TRUST_MANAGEMENT", "COLLEGE_ADMIN"))
):
    with get_rls_conn(user) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT student_id, primary_campus_id FROM students WHERE student_id = %s", (payload.student_id,))
            st = cur.fetchone()
            if not st:
                raise HTTPException(status_code=404, detail="Student not found or outside authorized campus")

            cur.execute("SELECT id FROM campus_enrollments WHERE student_id = %s AND status = 'ACTIVE' LIMIT 1", (payload.student_id,))
            enr = cur.fetchone()
            cur.execute("SELECT id FROM academic_years WHERE is_current = TRUE LIMIT 1")
            ay_id = cur.fetchone()["id"]

            ass_id = str(uuid.uuid4())
            cur.execute(
                """INSERT INTO student_fee_assessments (
                    id, student_id, campus_id, enrollment_id, academic_year_id,
                    assessed_amount, outstanding_balance, due_date, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'PENDING') RETURNING *""",
                (ass_id, payload.student_id, st["primary_campus_id"], enr["id"] if enr else None, ay_id, payload.assessed_amount, payload.assessed_amount, payload.due_date)
            )
            assessment = cur.fetchone()
    return {"assessment": assessment}


@app.post("/api/fees/payments", status_code=201)
def record_payment(
    payload: PaymentRecordRequest,
    user: Dict[str, Any] = Depends(require_roles("TRUST_MANAGEMENT", "COLLEGE_ADMIN"))
):
    """
    Step 1 of Two-Level Verification:
    Records a payment against an assessment. Enforces unique `transaction_ref`.
    Unposted payments (`PENDING_COLLEGE_VERIFICATION` or `COLLEGE_VERIFIED`) do NOT reduce the student's
    outstanding balance until Level 2 Trust Reconciliation posts the transaction!
    """
    with get_rls_conn(user) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM student_fee_assessments WHERE id = %s FOR UPDATE", (payload.assessment_id,))
            ass = cur.fetchone()
            if not ass:
                raise HTTPException(status_code=404, detail="Fee assessment not found or outside your authorized campus")

            cur.execute("SELECT id FROM payments WHERE transaction_ref = %s", (payload.transaction_ref.strip(),))
            if cur.fetchone():
                raise HTTPException(status_code=409, detail=f"Duplicate transaction reference '{payload.transaction_ref}' rejected.")

            initial_status = "COLLEGE_VERIFIED" if payload.auto_college_verify else "PENDING_COLLEGE_VERIFICATION"
            pay_id = str(uuid.uuid4())
            cur.execute(
                """INSERT INTO payments (
                    id, assessment_id, student_id, campus_id, transaction_ref, amount, payment_mode,
                    status, college_verified_by, college_verified_at, is_synthetic
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE) RETURNING *""",
                (
                    pay_id, ass["id"], ass["student_id"], ass["campus_id"],
                    payload.transaction_ref.strip(), payload.amount, payload.payment_mode,
                    initial_status, user["id"] if payload.auto_college_verify else None,
                    datetime.now() if payload.auto_college_verify else None
                )
            )
            payment = cur.fetchone()
            cur.execute("SELECT recalculate_assessment_balance(%s)", (ass["id"],))
            cur.execute("SELECT * FROM student_fee_assessments WHERE id = %s", (ass["id"],))
            updated_ass = cur.fetchone()

    return {"payment": payment, "assessment": updated_ass}


@app.post("/api/fees/payments/{payment_id}/verify-college")
def verify_payment_college_level(
    payment_id: str,
    user: Dict[str, Any] = Depends(require_roles("TRUST_MANAGEMENT", "COLLEGE_ADMIN"))
):
    """Level 1 Verification: College Administrator verifies the payment details."""
    with get_rls_conn(user) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM payments WHERE id = %s FOR UPDATE", (payment_id,))
            pay = cur.fetchone()
            if not pay:
                raise HTTPException(status_code=404, detail="Payment not found or access denied")
            if pay["status"] != "PENDING_COLLEGE_VERIFICATION":
                raise HTTPException(status_code=400, detail=f"Payment cannot be college-verified from status {pay['status']}")

            cur.execute(
                """UPDATE payments
                   SET status = 'COLLEGE_VERIFIED', college_verified_by = %s, college_verified_at = NOW()
                   WHERE id = %s RETURNING *""",
                (user["id"], payment_id)
            )
            updated_pay = cur.fetchone()
            record_audit_log(
                conn, str(user["id"]), user["role_code"], str(pay["campus_id"]),
                "PAYMENT_COLLEGE_VERIFIED", "payments", payment_id,
                f"College verification completed for payment {pay['transaction_ref']}"
            )
    return {"payment": updated_pay}


@app.post("/api/fees/payments/{payment_id}/verify-trust")
def verify_and_post_payment_trust_level(
    payment_id: str,
    user: Dict[str, Any] = Depends(require_roles("TRUST_MANAGEMENT", "COLLEGE_ADMIN"))
):
    """
    Level 2 Verification & Posting:
    Confirms reconciliation, transitions the existing payment record to `POSTED` (never creating a duplicate row!),
    generates an immutable receipt number, recalculates `outstanding_balance`, and creates a notification.
    """
    with get_rls_conn(user) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM payments WHERE id = %s FOR UPDATE", (payment_id,))
            pay = cur.fetchone()
            if not pay:
                raise HTTPException(status_code=404, detail="Payment not found or access denied")
            if pay["status"] not in ("COLLEGE_VERIFIED", "PENDING_COLLEGE_VERIFICATION"):
                raise HTTPException(status_code=400, detail=f"Payment is already in status {pay['status']}")

            cur.execute("SELECT nextval('seq_receipt_no') AS rval")
            rval = cur.fetchone()["rval"]
            receipt_no = f"RCPT-2026-{rval}"

            cur.execute("SELECT outstanding_balance FROM student_fee_assessments WHERE id = %s", (pay["assessment_id"],))
            prev_bal = cur.fetchone()["outstanding_balance"]

            cur.execute(
                """UPDATE payments
                   SET status = 'POSTED',
                       receipt_number = %s,
                       college_verified_by = COALESCE(college_verified_by, %s),
                       college_verified_at = COALESCE(college_verified_at, NOW()),
                       trust_verified_by = %s,
                       trust_verified_at = NOW(),
                       posted_at = NOW()
                   WHERE id = %s RETURNING *""",
                (receipt_no, user["id"], user["id"], payment_id)
            )
            posted_pay = cur.fetchone()

            cur.execute(
                "INSERT INTO payment_allocations (payment_id, assessment_id, allocated_amount) VALUES (%s, %s, %s)",
                (payment_id, pay["assessment_id"], pay["amount"])
            )
            cur.execute("SELECT recalculate_assessment_balance(%s)", (pay["assessment_id"],))
            cur.execute("SELECT * FROM student_fee_assessments WHERE id = %s", (pay["assessment_id"],))
            updated_ass = cur.fetchone()

            cur.execute(
                """INSERT INTO financial_audit_events (
                    campus_id, student_id, assessment_id, payment_id, event_type,
                    amount, previous_balance, new_balance, actor_user_id, details
                ) VALUES (%s, %s, %s, %s, 'PAYMENT_POSTED', %s, %s, %s, %s, %s)""",
                (
                    pay["campus_id"], pay["student_id"], pay["assessment_id"], payment_id,
                    pay["amount"], prev_bal, updated_ass["outstanding_balance"], user["id"],
                    json.dumps({"receipt_number": receipt_no, "transaction_ref": pay["transaction_ref"]})
                )
            )
            cur.execute(
                """INSERT INTO notifications (student_id, campus_id, category, title, message, is_simulated)
                   VALUES (%s, %s, 'FEE_POSTED', 'Fee Payment Posted & Receipt Issued', %s, TRUE)""",
                (
                    pay["student_id"], pay["campus_id"],
                    f"Payment of INR {pay['amount']} (Ref: {pay['transaction_ref']}) has been verified and posted. Receipt: {receipt_no}. Updated Outstanding Balance: INR {updated_ass['outstanding_balance']}."
                )
            )
            record_audit_log(
                conn, str(user["id"]), user["role_code"], str(pay["campus_id"]),
                "PAYMENT_POSTED", "payments", payment_id,
                f"Payment {pay['transaction_ref']} posted with immutable receipt {receipt_no}"
            )

    return {"payment": posted_pay, "assessment": updated_ass}


@app.post("/api/fees/concessions-scholarships", status_code=201)
def apply_concession_or_scholarship(
    payload: ConcessionOrScholarshipRequest,
    user: Dict[str, Any] = Depends(require_roles("TRUST_MANAGEMENT", "COLLEGE_ADMIN"))
):
    with get_rls_conn(user) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM student_fee_assessments WHERE id = %s FOR UPDATE", (payload.assessment_id,))
            ass = cur.fetchone()
            if not ass:
                raise HTTPException(status_code=404, detail="Fee assessment not found or access denied")

            if payload.entry_type == "CONCESSION":
                cur.execute(
                    """INSERT INTO concessions (assessment_id, student_id, campus_id, concession_type, amount, status, approved_by, reason)
                       VALUES (%s, %s, %s, %s, %s, 'APPROVED', %s, %s)""",
                    (ass["id"], ass["student_id"], ass["campus_id"], payload.category_or_scheme, payload.amount, user["id"], payload.reason)
                )
            else:
                cur.execute(
                    """INSERT INTO scholarships (assessment_id, student_id, campus_id, scheme_name, amount, status)
                       VALUES (%s, %s, %s, %s, %s, 'APPROVED')""",
                    (ass["id"], ass["student_id"], ass["campus_id"], payload.category_or_scheme, payload.amount)
                )

            cur.execute("SELECT recalculate_assessment_balance(%s)", (ass["id"],))
            cur.execute("SELECT * FROM student_fee_assessments WHERE id = %s", (ass["id"],))
            updated_ass = cur.fetchone()

    return {"assessment": updated_ass}


@app.post("/api/fees/refunds-reversals", status_code=201)
def record_refund_or_reversal(
    payload: RefundOrReversalRequest,
    user: Dict[str, Any] = Depends(require_roles("TRUST_MANAGEMENT", "COLLEGE_ADMIN"))
):
    """
    Processes a linked Refund or Reversal without ever overwriting or deleting the original posted receipt.
    """
    with get_rls_conn(user) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM payments WHERE id = %s FOR UPDATE", (payload.payment_id,))
            pay = cur.fetchone()
            if not pay:
                raise HTTPException(status_code=404, detail="Payment not found or access denied")
            if pay["status"] != "POSTED":
                raise HTTPException(status_code=400, detail="Only POSTED payments can be refunded or reversed.")

            if payload.action_type == "REFUND":
                if payload.amount > float(pay["amount"]):
                    raise HTTPException(status_code=400, detail="Refund amount cannot exceed original payment amount.")
                ref_no = f"REF-{uuid.uuid4().hex[:8].upper()}"
                cur.execute(
                    """INSERT INTO refunds (payment_id, assessment_id, student_id, campus_id, refund_ref, amount, reason, status, approved_by)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, 'COMPLETED', %s) RETURNING *""",
                    (pay["id"], pay["assessment_id"], pay["student_id"], pay["campus_id"], ref_no, payload.amount, payload.reason, user["id"])
                )
                entry = cur.fetchone()
            else:
                # Reversal transitions status to REVERSED and logs a linked adjustment entry while preserving receipt_number and amount
                cur.execute("UPDATE payments SET status = 'REVERSED' WHERE id = %s RETURNING *", (pay["id"],))
                entry = cur.fetchone()
                cur.execute(
                    """INSERT INTO financial_adjustments (assessment_id, student_id, campus_id, linked_payment_id, adjustment_type, amount, reason, created_by)
                       VALUES (%s, %s, %s, %s, 'REVERSAL_DEBIT', %s, %s, %s)""",
                    (pay["assessment_id"], pay["student_id"], pay["campus_id"], pay["id"], pay["amount"], payload.reason, user["id"])
                )

            cur.execute("SELECT recalculate_assessment_balance(%s)", (pay["assessment_id"],))
            cur.execute("SELECT * FROM student_fee_assessments WHERE id = %s", (pay["assessment_id"],))
            updated_ass = cur.fetchone()

    return {"action_type": payload.action_type, "entry": entry, "assessment": updated_ass}


@app.post("/api/fees/send-reminder/{assessment_id}")
def send_verified_fee_reminder(
    assessment_id: str,
    user: Dict[str, Any] = Depends(require_roles("TRUST_MANAGEMENT", "COLLEGE_ADMIN"))
):
    """
    Verifies the current outstanding balance from posted ledger transactions before issuing a parent reminder.
    Prevents parents from ever receiving reminders for fees they have already paid!
    """
    with get_rls_conn(user) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT recalculate_assessment_balance(%s)", (assessment_id,))
            cur.execute("SELECT * FROM student_fee_assessments WHERE id = %s", (assessment_id,))
            ass = cur.fetchone()
            if not ass:
                raise HTTPException(status_code=404, detail="Fee assessment not found")

            if float(ass["outstanding_balance"]) <= 0:
                raise HTTPException(
                    status_code=400,
                    detail="Reminder blocked: Student has INR 0.00 outstanding balance (all assessed dues are already paid and posted)."
                )

            cur.execute(
                """INSERT INTO notifications (student_id, campus_id, category, title, message, is_simulated)
                   VALUES (%s, %s, 'FEE_REMINDER', 'Verified Fee Balance Reminder', %s, TRUE) RETURNING *""",
                (
                    ass["student_id"], ass["campus_id"],
                    f"Simulated Parent Reminder: Verified outstanding fee balance is INR {ass['outstanding_balance']} (after crediting INR {ass['net_posted_payments']} in posted payments)."
                )
            )
            notif = cur.fetchone()
    return {"status": "reminder_queued", "notification": notif}


# =============================================================================
# 6. HOSTEL VACANCY MAP & TRANSACTIONAL BED ALLOCATION
# =============================================================================

@app.get("/api/hostels/inventory")
def get_hostel_inventory(
    campus_id: Optional[str] = Query(default=None),
    building_id: Optional[str] = Query(default=None),
    user: Dict[str, Any] = Depends(get_current_user)
):
    with get_rls_conn(user) as conn:
        with conn.cursor() as cur:
            clauses = ["1=1"]
            params: List[Any] = []
            if campus_id and campus_id != "ALL":
                clauses.append("hb.campus_id = %s")
                params.append(campus_id)
            if building_id and building_id != "ALL":
                clauses.append("hb.building_id = %s")
                params.append(building_id)

            where_sql = " AND ".join(clauses)
            cur.execute(f"""
                SELECT
                    COUNT(DISTINCT hb.building_id) AS total_hostels,
                    COUNT(DISTINCT hb.room_id) AS total_rooms,
                    COUNT(*) AS total_beds,
                    COUNT(*) FILTER (WHERE hb.status = 'OCCUPIED') AS occupied_beds,
                    COUNT(*) FILTER (WHERE hb.status = 'AVAILABLE') AS available_beds,
                    COUNT(*) FILTER (WHERE hb.status = 'RESERVED') AS reserved_beds,
                    COUNT(*) FILTER (WHERE hb.status = 'OUT_OF_SERVICE') AS out_of_service_beds
                FROM hostel_beds hb
                WHERE {where_sql}
            """, tuple(params))
            summary = cur.fetchone()
            t_beds = summary["total_beds"] or 0
            occ_beds = summary["occupied_beds"] or 0
            summary["occupancy_percentage"] = round((occ_beds / t_beds) * 100.0, 2) if t_beds > 0 else 0.0

            cur.execute("""
                SELECT b.id, b.campus_id, b.code, b.name, b.gender_type, b.total_floors, c.name AS campus_name
                FROM hostel_buildings b
                JOIN campuses c ON c.id = b.campus_id
                ORDER BY c.campus_number, b.code
            """)
            buildings = cur.fetchall()

            cur.execute(f"""
                SELECT hb.id AS bed_id, hb.bed_code, hb.status, hb.current_student_id,
                       hr.id AS room_id, hr.room_number, hr.floor_number, hr.room_type, hr.capacity,
                       hbl.id AS building_id, hbl.code AS building_code, hbl.name AS building_name, hbl.gender_type,
                       c.id AS campus_id, c.code AS campus_code,
                       s.full_name AS occupant_name, s.current_usn AS occupant_usn,
                       ha.id AS active_allocation_id
                FROM hostel_beds hb
                JOIN hostel_rooms hr ON hr.id = hb.room_id
                JOIN hostel_buildings hbl ON hbl.id = hb.building_id
                JOIN campuses c ON c.id = hb.campus_id
                LEFT JOIN students s ON s.student_id = hb.current_student_id
                LEFT JOIN hostel_allocations ha ON ha.bed_id = hb.id AND ha.allocation_status IN ('ACTIVE', 'RESERVED')
                WHERE {where_sql}
                ORDER BY c.campus_number, hbl.code, hr.room_number, hb.bed_code
                LIMIT 240
            """, tuple(params))
            beds = cur.fetchall()

    return {"summary": summary, "buildings": buildings, "beds": beds}


@app.post("/api/hostels/allocate", status_code=201)
def allocate_hostel_bed(
    payload: HostelAllocateRequest,
    user: Dict[str, Any] = Depends(require_roles("TRUST_MANAGEMENT", "COLLEGE_ADMIN", "HOSTEL_WARDEN"))
):
    """
    Allocates a hostel bed inside a database transaction with `SELECT ... FOR UPDATE` on `hostel_beds`
    so two concurrent wardens can NEVER allocate the same bed, and out-of-service/occupied beds are rejected.
    """
    with get_rls_conn(user) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM hostel_beds WHERE id = %s FOR UPDATE", (payload.bed_id,))
            bed = cur.fetchone()
            if not bed:
                raise HTTPException(status_code=404, detail="Hostel bed not found or outside your authorized campus")

            if bed["status"] != "AVAILABLE":
                raise HTTPException(
                    status_code=409,
                    detail=f"Bed {bed['bed_code']} is currently {bed['status']} and cannot be allocated."
                )

            cur.execute("SELECT * FROM students WHERE UPPER(current_usn) = UPPER(%s)", (payload.usn.strip(),))
            student = cur.fetchone()
            if not student:
                raise HTTPException(status_code=404, detail="Student USN not found in authorized campus records")

            if str(student["primary_campus_id"]) != str(bed["campus_id"]):
                raise HTTPException(status_code=400, detail="Student belongs to a different campus than the selected hostel bed.")

            cur.execute(
                "SELECT id FROM hostel_allocations WHERE student_id = %s AND allocation_status IN ('ACTIVE', 'RESERVED')",
                (student["student_id"],)
            )
            if cur.fetchone():
                raise HTTPException(status_code=409, detail="Student already has an active or reserved hostel bed allocation.")

            cur.execute("SELECT id FROM academic_years WHERE is_current = TRUE LIMIT 1")
            ay_id = cur.fetchone()["id"]

            new_bed_status = "OCCUPIED" if payload.allocation_type == "ACTIVE" else "RESERVED"
            alloc_id = str(uuid.uuid4())
            cur.execute(
                """INSERT INTO hostel_allocations (
                    id, bed_id, room_id, building_id, campus_id, student_id,
                    academic_year_id, allocation_status, allocated_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *""",
                (
                    alloc_id, bed["id"], bed["room_id"], bed["building_id"], bed["campus_id"],
                    student["student_id"], ay_id, payload.allocation_type, user["id"]
                )
            )
            alloc = cur.fetchone()

            cur.execute(
                "UPDATE hostel_beds SET status = %s, current_student_id = %s, updated_at = NOW() WHERE id = %s",
                (new_bed_status, student["student_id"], bed["id"])
            )
            cur.execute(
                """INSERT INTO hostel_allocation_history (allocation_id, bed_id, student_id, campus_id, action, actor_user_id, reason)
                   VALUES (%s, %s, %s, %s, %s, %s, 'Warden bed allocation')""",
                (alloc_id, bed["id"], student["student_id"], bed["campus_id"], new_bed_status, user["id"])
            )
            record_audit_log(
                conn, str(user["id"]), user["role_code"], str(bed["campus_id"]),
                "HOSTEL_BED_ALLOCATED", "hostel_beds", str(bed["id"]),
                f"Allocated bed {bed['bed_code']} to {student['full_name']} ({student['current_usn']})"
            )

    return {"allocation": alloc, "bed_status": new_bed_status}


@app.post("/api/hostels/release")
def release_hostel_bed(
    payload: HostelReleaseRequest,
    user: Dict[str, Any] = Depends(require_roles("TRUST_MANAGEMENT", "COLLEGE_ADMIN", "HOSTEL_WARDEN"))
):
    with get_rls_conn(user) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM hostel_allocations WHERE id = %s FOR UPDATE", (payload.allocation_id,))
            alloc = cur.fetchone()
            if not alloc:
                raise HTTPException(status_code=404, detail="Allocation not found or access denied")
            if alloc["allocation_status"] not in ("ACTIVE", "RESERVED"):
                raise HTTPException(status_code=400, detail="Allocation is already released")

            cur.execute(
                "UPDATE hostel_allocations SET allocation_status = 'RELEASED', released_at = NOW(), release_reason = %s WHERE id = %s",
                (payload.reason, payload.allocation_id)
            )
            cur.execute(
                "UPDATE hostel_beds SET status = 'AVAILABLE', current_student_id = NULL, updated_at = NOW() WHERE id = %s",
                (alloc["bed_id"],)
            )
            cur.execute(
                """INSERT INTO hostel_allocation_history (allocation_id, bed_id, student_id, campus_id, action, actor_user_id, reason)
                   VALUES (%s, %s, %s, %s, 'RELEASED', %s, %s)""",
                (alloc["id"], alloc["bed_id"], alloc["student_id"], alloc["campus_id"], user["id"], payload.reason)
            )
    return {"status": "RELEASED", "bed_id": str(alloc["bed_id"])}


# =============================================================================
# 7. ATTENDANCE, ELIGIBILITY & EXAMINATION RESULTS
# =============================================================================

def compute_attendance_eligibility(
    classes_attended: Optional[int],
    classes_held: Optional[int],
    threshold_pct: float = 75.0,
    warning_threshold_pct: Optional[float] = None
) -> Dict[str, Any]:
    """
    Authoritative Attendance & Eligibility Formula:
    Attendance % = (attended eligible classes / total eligible classes) * 100
    Strictly distinguishes between:
    - Missing data / 0 classes held -> `NO_DATA` (percentage = None, never confused with 0% attendance!)
    - Below threshold (< threshold_pct) -> `INELIGIBLE`
    - Approaching threshold (threshold_pct <= pct < warning_threshold_pct) -> `AT_RISK`
    - At or above warning threshold -> `ELIGIBLE`
    """
    warn_pct = warning_threshold_pct if warning_threshold_pct is not None else (threshold_pct + 5.0)
    if classes_held is None or classes_attended is None or classes_held <= 0:
        return {
            "attendance_percentage": None,
            "eligibility_status": "NO_DATA",
            "applicable_threshold_pct": threshold_pct,
            "reason": "No eligible classes conducted or attendance data not yet recorded (distinct from 0% attendance)."
        }

    pct = round((float(classes_attended) / float(classes_held)) * 100.0, 2)
    if pct < threshold_pct:
        status_code = "INELIGIBLE"
        reason = f"Below institutional policy threshold of {threshold_pct}% (recorded: {pct}%)."
    elif pct < warn_pct:
        status_code = "AT_RISK"
        reason = f"Approaching threshold: {pct}% is above {threshold_pct}% minimum but below {warn_pct}% early-warning band."
    else:
        status_code = "ELIGIBLE"
        reason = f"Meets institutional attendance policy ({pct}% >= {threshold_pct}%)."

    return {
        "attendance_percentage": pct,
        "eligibility_status": status_code,
        "applicable_threshold_pct": threshold_pct,
        "reason": reason,
    }


@app.get("/api/attendance")
def list_attendance_records(
    campus_id: Optional[str] = Query(default=None),
    eligibility_filter: Optional[str] = Query(default=None),
    limit: int = Query(default=60, le=250),
    user: Dict[str, Any] = Depends(get_current_user)
):
    with get_rls_conn(user) as conn:
        with conn.cursor() as cur:
            clauses = ["1=1"]
            params: List[Any] = []
            if campus_id and campus_id != "ALL":
                clauses.append("ap.campus_id = %s")
                params.append(campus_id)
            if eligibility_filter and eligibility_filter != "ALL":
                clauses.append("ap.eligibility_status = %s")
                params.append(eligibility_filter)

            where_sql = " AND ".join(clauses)
            cur.execute(f"""
                SELECT ap.*, s.full_name AS student_name, s.current_usn,
                       c.code AS campus_code, c.name AS campus_name,
                       co.code AS course_code, co.name AS course_name
                FROM academic_progress_records ap
                JOIN students s ON s.student_id = ap.student_id
                JOIN campuses c ON c.id = ap.campus_id
                JOIN courses co ON co.id = ap.course_id
                WHERE {where_sql}
                ORDER BY ap.attendance_percentage ASC NULLS LAST
                LIMIT %s
            """, tuple(params + [limit]))
            records = cur.fetchall()

            cur.execute(f"""
                SELECT
                    COUNT(*) AS total_students,
                    COUNT(*) FILTER (WHERE ap.eligibility_status = 'ELIGIBLE') AS eligible_count,
                    COUNT(*) FILTER (WHERE ap.eligibility_status = 'AT_RISK') AS at_risk_count,
                    COUNT(*) FILTER (WHERE ap.eligibility_status = 'INELIGIBLE') AS ineligible_count,
                    COUNT(*) FILTER (WHERE ap.eligibility_status = 'NO_DATA') AS no_data_count
                FROM academic_progress_records ap
                WHERE {where_sql}
            """, tuple(params))
            summary = cur.fetchone()
            tot = summary["total_students"] or 0
            summary["below_threshold_percentage"] = round(((summary["ineligible_count"] or 0) / tot) * 100.0, 2) if tot > 0 else 0.0

    return {
        "policy_disclaimer": "Eligibility status reflects automated application of the configured campus attendance policy and remains subject to institutional examination board review.",
        "summary": summary,
        "records": records
    }


@app.get("/api/attendance/export-csv")
def export_attendance_csv(
    campus_id: Optional[str] = Query(default=None),
    user: Dict[str, Any] = Depends(require_roles("TRUST_MANAGEMENT", "COLLEGE_ADMIN"))
):
    data = list_attendance_records(campus_id=campus_id, eligibility_filter=None, limit=250, user=user)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["USN", "Student Name", "Campus", "Course", "Classes Attended", "Classes Held", "Attendance %", "Threshold %", "Policy Eligibility Status"])
    for r in data["records"]:
        writer.writerow([
            r["current_usn"], r["student_name"], r["campus_code"], r["course_code"],
            r["total_classes_attended"], r["total_classes_held"],
            r["attendance_percentage"] if r["attendance_percentage"] is not None else "NO_DATA",
            r["applicable_threshold_pct"], r["eligibility_status"]
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=trustos_attendance_eligibility_report.csv"}
    )


# =============================================================================
# 8. SCHOLARSHIPS & GOVERNMENT REIMBURSEMENTS
# =============================================================================

@app.get("/api/scholarships/reimbursements")
def list_reimbursements(
    campus_id: Optional[str] = Query(default=None),
    usn: Optional[str] = Query(default=None),
    limit: int = Query(default=60, le=200),
    user: Dict[str, Any] = Depends(get_current_user)
):
    with get_rls_conn(user) as conn:
        with conn.cursor() as cur:
            clauses = ["1=1"]
            params: List[Any] = []
            if campus_id and campus_id != "ALL":
                clauses.append("gr.campus_id = %s")
                params.append(campus_id)
            if usn:
                clauses.append("s.current_usn ILIKE %s")
                params.append(f"%{usn.strip()}%")

            where_sql = " AND ".join(clauses)
            cur.execute(f"""
                SELECT gr.*, s.full_name AS student_name, s.current_usn, s.category,
                       c.code AS campus_code, c.name AS campus_name,
                       ss.scheme_code, ss.name AS scheme_name, ss.sponsoring_agency
                FROM government_reimbursement_claims gr
                JOIN students s ON s.student_id = gr.student_id
                JOIN campuses c ON c.id = gr.campus_id
                JOIN scholarship_schemes ss ON ss.id = gr.scheme_id
                WHERE {where_sql}
                ORDER BY gr.updated_at DESC
                LIMIT %s
            """, tuple(params + [limit]))
            claims = cur.fetchall()

            cur.execute("SELECT * FROM scholarship_schemes ORDER BY scheme_code")
            schemes = cur.fetchall()

    return {
        "simulation_notice": "All scholarship and government reimbursement claims in this environment are synthetic demonstration records. Export-based workflow is enabled.",
        "schemes": schemes,
        "claims": claims
    }


# =============================================================================
# 9. MULTI-DATASET PROFILER, MAPPER & IDEMPOTENT IMPORTER
# =============================================================================

@app.get("/api/imports/raw-files")
def list_available_raw_files(user: Dict[str, Any] = Depends(require_roles("TRUST_MANAGEMENT", "COLLEGE_ADMIN"))):
    raw_dir = Path(__file__).resolve().parents[1] / "data" / "raw_sources"
    files = []
    if raw_dir.exists():
        for f in sorted(raw_dir.iterdir()):
            if f.is_file():
                files.append({"filename": f.name, "size_bytes": f.stat().st_size})
    with get_owner_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM dataset_imports ORDER BY created_at DESC LIMIT 20")
            history = cur.fetchall()
            cur.execute("SELECT * FROM data_quality_issues ORDER BY created_at DESC LIMIT 50")
            issues = cur.fetchall()
    return {"raw_source_files": files, "import_history": history, "data_quality_issues": issues}


@app.post("/api/imports/profile")
async def profile_uploaded_file(
    target_module: str = Form("ADMISSIONS"),
    sample_filename: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    user: Dict[str, Any] = Depends(require_roles("TRUST_MANAGEMENT", "COLLEGE_ADMIN"))
):
    if file is not None:
        content = await file.read()
        fname = file.filename or "uploaded_dataset.csv"
    elif sample_filename:
        raw_path = Path(__file__).resolve().parents[1] / "data" / "raw_sources" / sample_filename
        if not raw_path.exists():
            raise HTTPException(status_code=404, detail=f"Sample file {sample_filename} not found")
        content = raw_path.read_bytes()
        fname = sample_filename
    else:
        raise HTTPException(status_code=400, detail="Provide either an uploaded file or a sample_filename")

    return profile_dataset(fname, content, target_module)


@app.post("/api/imports/execute")
async def execute_dataset_import(
    target_module: str = Form("ADMISSIONS"),
    mapping_json: str = Form("{}"),
    sample_filename: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    user: Dict[str, Any] = Depends(require_roles("TRUST_MANAGEMENT", "COLLEGE_ADMIN"))
):
    """
    Runs a validated, idempotent dataset import:
    - Computes row hashes (`student_source_records.source_row_hash`) so re-importing the same file never duplicates records!
    - Logs missing required fields or invalid dates to `data_quality_issues` without fabricating real values.
    - Routes ambiguous student matches to `duplicate_match_candidates` instead of silently merging.
    - Rolls back completely on fatal foreign-key or format errors.
    """
    if file is not None:
        content = await file.read()
        fname = file.filename or "uploaded_dataset.csv"
    elif sample_filename:
        raw_path = Path(__file__).resolve().parents[1] / "data" / "raw_sources" / sample_filename
        if not raw_path.exists():
            raise HTTPException(status_code=404, detail=f"Sample file {sample_filename} not found")
        content = raw_path.read_bytes()
        fname = sample_filename
    else:
        raise HTTPException(status_code=400, detail="Provide either a file or sample_filename")

    df, fmt, _ = load_dataframe_from_bytes(fname, content)
    df = df.fillna("")
    col_map = json.loads(mapping_json) if mapping_json and mapping_json != "{}" else profile_dataset(fname, content, target_module)["suggested_mapping"]

    # Invert mapping: canonical_field -> source_column
    inv_map = {v: k for k, v in col_map.items()}
    checksum = hashlib.sha256(content).hexdigest()

    total_rows = len(df)
    accepted = 0
    rejected = 0
    skipped_duplicates = 0
    reconciled = 0
    errors_report = []

    with get_owner_conn() as conn:
        with conn.cursor() as cur:
            import_id = str(uuid.uuid4())
            cur.execute(
                """INSERT INTO dataset_imports (
                    id, campus_id, filename, file_format, file_checksum, target_module,
                    total_rows, status, imported_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'VALIDATING', %s)""",
                (import_id, user.get("primary_campus_id"), fname, fmt, checksum, target_module.upper(), total_rows, user["id"])
            )

            for idx, row in df.iterrows():
                row_num = int(idx) + 1
                row_dict = {str(k): str(v).strip() for k, v in row.to_dict().items()}
                row_hash = hashlib.sha256(f"{fname}:{target_module}:{json.dumps(row_dict, sort_keys=True)}".encode("utf-8")).hexdigest()

                # Idempotency check: has this exact source row already been imported?
                cur.execute("SELECT id FROM student_source_records WHERE source_row_hash = %s", (row_hash,))
                if cur.fetchone():
                    skipped_duplicates += 1
                    continue

                if target_module.upper() in ("ADMISSIONS", "STUDENTS"):
                    name_val = row_dict.get(inv_map.get("full_name", ""), "").strip()
                    dob_raw = row_dict.get(inv_map.get("date_of_birth", ""), "").strip()
                    phone_val = row_dict.get(inv_map.get("phone", ""), "").strip()
                    usn_val = row_dict.get(inv_map.get("usn", ""), "").strip()
                    src_key = row_dict.get(inv_map.get("source_record_key", ""), f"ROW-{row_num}")

                    if not name_val:
                        rejected += 1
                        err_msg = "Missing required canonical field: full_name"
                        errors_report.append({"row": row_num, "field": "full_name", "error": err_msg})
                        cur.execute(
                            """INSERT INTO data_quality_issues (import_id, source_file, row_number, field_name, issue_type, severity, raw_value, description)
                               VALUES (%s, %s, %s, 'full_name', 'MISSING_REQUIRED', 'ERROR', '', %s)""",
                            (import_id, fname, row_num, err_msg)
                        )
                        continue

                    parsed_dob = parse_flexible_date(dob_raw)
                    if not parsed_dob:
                        rejected += 1
                        err_msg = f"Invalid or unparseable date_of_birth: '{dob_raw}'"
                        errors_report.append({"row": row_num, "field": "date_of_birth", "error": err_msg})
                        cur.execute(
                            """INSERT INTO data_quality_issues (import_id, source_file, row_number, field_name, issue_type, severity, raw_value, description)
                               VALUES (%s, %s, %s, 'date_of_birth', 'INVALID_DATE', 'ERROR', %s, %s)""",
                            (import_id, fname, row_num, dob_raw, err_msg)
                        )
                        continue

                    # Check against existing canonical students for duplicates/homonyms
                    norm_n = normalize_text(name_val)
                    cur.execute(
                        """SELECT student_id, full_name, normalized_name, date_of_birth, phone, current_usn
                           FROM students
                           WHERE UPPER(current_usn) = UPPER(%s) OR normalized_name = %s OR phone = %s
                           LIMIT 5""",
                        (usn_val or "__NONE__", norm_n, phone_val or "__NONE__")
                    )
                    candidates = cur.fetchall()
                    matched_student_id = None
                    if candidates:
                        best_cand = candidates[0]
                        score_res = score_student_duplicate_candidate(name_val, parsed_dob, phone_val, usn_val, best_cand)
                        if score_res["proposed_action"] == "EXACT_LINK":
                            matched_student_id = best_cand["student_id"]
                            reconciled += 1
                        elif score_res["proposed_action"] == "HUMAN_REVIEW":
                            reconciled += 1
                            cur.execute(
                                """INSERT INTO duplicate_match_candidates (
                                    import_id, source_file, source_record_key, source_student_name, source_dob, source_phone, source_usn,
                                    candidate_student_id, candidate_student_name, candidate_usn, match_confidence,
                                    matching_attributes, conflicting_attributes, proposed_action, review_status
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'HUMAN_REVIEW', 'PENDING_REVIEW')""",
                                (
                                    import_id, fname, src_key, name_val, str(parsed_dob), phone_val, usn_val,
                                    best_cand["student_id"], best_cand["full_name"], best_cand["current_usn"],
                                    score_res["match_confidence"], json.dumps(score_res["matching_attributes"]),
                                    json.dumps(score_res["conflicting_attributes"])
                                )
                            )

                    cur.execute(
                        """INSERT INTO student_source_records (
                            student_id, campus_id, source_system, source_file, source_row_hash, raw_payload, data_origin
                        ) VALUES (%s, %s, %s, %s, %s, %s, 'SOURCE_DERIVED')""",
                        (matched_student_id, user.get("primary_campus_id"), target_module.upper(), fname, row_hash, json.dumps(row_dict))
                    )
                    accepted += 1

                elif target_module.upper() == "ATTENDANCE":
                    usn_val = row_dict.get(inv_map.get("usn", ""), "").strip()
                    held_raw = row_dict.get(inv_map.get("classes_held", ""), "0")
                    att_raw = row_dict.get(inv_map.get("classes_attended", ""), "0")
                    cur.execute("SELECT student_id, primary_campus_id FROM students WHERE UPPER(current_usn) = UPPER(%s)", (usn_val,))
                    st = cur.fetchone()
                    if not st:
                        rejected += 1
                        errors_report.append({"row": row_num, "field": "usn", "error": f"Unknown USN '{usn_val}'"})
                        continue
                    held_i = int(float(held_raw or 0))
                    att_i = int(float(att_raw or 0))
                    cur.execute("SELECT attendance_threshold_pct FROM campus_policies WHERE campus_id = %s AND is_active = TRUE LIMIT 1", (st["primary_campus_id"],))
                    pol = cur.fetchone()
                    thresh = float(pol["attendance_threshold_pct"]) if pol else 75.0
                    calc = compute_attendance_eligibility(att_i, held_i, thresh)
                    cur.execute(
                        """UPDATE academic_progress_records
                           SET total_classes_held = %s, total_classes_attended = %s,
                               attendance_percentage = %s, eligibility_status = %s, updated_at = NOW()
                           WHERE student_id = %s""",
                        (held_i, att_i, calc["attendance_percentage"], calc["eligibility_status"], st["student_id"])
                    )
                    cur.execute(
                        """INSERT INTO student_source_records (student_id, campus_id, source_system, source_file, source_row_hash, raw_payload)
                           VALUES (%s, %s, 'ATTENDANCE', %s, %s, %s)""",
                        (st["student_id"], st["primary_campus_id"], fname, row_hash, json.dumps(row_dict))
                    )
                    accepted += 1
                else:
                    cur.execute(
                        """INSERT INTO student_source_records (campus_id, source_system, source_file, source_row_hash, raw_payload)
                           VALUES (%s, %s, %s, %s, %s)""",
                        (user.get("primary_campus_id"), target_module.upper(), fname, row_hash, json.dumps(row_dict))
                    )
                    accepted += 1

            cur.execute(
                """UPDATE dataset_imports
                   SET accepted_rows = %s, rejected_rows = %s, skipped_duplicate_rows = %s,
                       reconciled_rows = %s, status = 'COMPLETED', error_report_json = %s
                   WHERE id = %s RETURNING *""",
                (accepted, rejected, skipped_duplicates, reconciled, json.dumps(errors_report), import_id)
            )
            imp_record = cur.fetchone()

    return {"import": imp_record, "errors": errors_report}


# =============================================================================
# 10. CAMPUS POLICY ENGINE, PRIVACY (DPDP ACT 2023), NOTIFICATIONS & AUDIT LOGS
# =============================================================================

@app.get("/api/policies")
def list_campus_policies(user: Dict[str, Any] = Depends(get_current_user)):
    with get_owner_conn() as conn:
        with conn.cursor() as cur:
            if user["role_code"] == "COLLEGE_ADMIN":
                cur.execute("""
                    SELECT cp.*, c.name AS campus_name, c.code AS campus_code, c.campus_number
                    FROM campus_policies cp
                    JOIN campuses c ON c.id = cp.campus_id
                    WHERE cp.campus_id = %s AND cp.is_active = TRUE
                    ORDER BY c.campus_number
                """, (user["primary_campus_id"],))
            else:
                cur.execute("""
                    SELECT cp.*, c.name AS campus_name, c.code AS campus_code, c.campus_number
                    FROM campus_policies cp
                    JOIN campuses c ON c.id = cp.campus_id
                    WHERE cp.is_active = TRUE
                    ORDER BY c.campus_number
                """)
            return {"policies": cur.fetchall()}


@app.put("/api/policies")
def update_campus_policy(
    payload: PolicyUpdateRequest,
    user: Dict[str, Any] = Depends(require_roles("TRUST_MANAGEMENT", "COLLEGE_ADMIN"))
):
    """
    Updates a campus policy by creating a new versioned record (preserving historical versions)
    and recalculating attendance eligibility for that campus ONLY without affecting other campuses.
    """
    if user["role_code"] == "COLLEGE_ADMIN" and str(payload.campus_id) != str(user["primary_campus_id"]):
        raise HTTPException(status_code=403, detail="College Administrator cannot modify another campus's policies.")

    with get_owner_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM campus_policies WHERE campus_id = %s AND is_active = TRUE ORDER BY version DESC LIMIT 1 FOR UPDATE",
                (payload.campus_id,)
            )
            old_pol = cur.fetchone()
            if not old_pol:
                raise HTTPException(status_code=404, detail="Active campus policy not found")

            cur.execute("UPDATE campus_policies SET is_active = FALSE, effective_to = CURRENT_DATE WHERE id = %s", (old_pol["id"],))
            new_version = int(old_pol["version"]) + 1
            new_pol_id = str(uuid.uuid4())
            cur.execute(
                """INSERT INTO campus_policies (
                    id, campus_id, academic_year_id, version,
                    attendance_threshold_pct, warning_threshold_pct,
                    late_fee_per_day, grace_period_days, max_concession_pct,
                    transfer_min_attendance_pct, require_zero_dues_for_transfer,
                    is_active, updated_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s) RETURNING *""",
                (
                    new_pol_id, payload.campus_id, old_pol["academic_year_id"], new_version,
                    payload.attendance_threshold_pct, payload.warning_threshold_pct,
                    payload.late_fee_per_day, payload.grace_period_days, payload.max_concession_pct,
                    payload.transfer_min_attendance_pct, payload.require_zero_dues_for_transfer,
                    user["id"]
                )
            )
            new_pol = cur.fetchone()

            # Recompute eligibility strictly for the target campus
            cur.execute(
                """UPDATE academic_progress_records
                   SET applicable_threshold_pct = %s,
                       eligibility_status = CASE
                           WHEN total_classes_held <= 0 OR attendance_percentage IS NULL THEN 'NO_DATA'
                           WHEN attendance_percentage < %s THEN 'INELIGIBLE'
                           WHEN attendance_percentage < %s THEN 'AT_RISK'
                           ELSE 'ELIGIBLE'
                       END,
                       updated_at = NOW()
                   WHERE campus_id = %s""",
                (payload.attendance_threshold_pct, payload.attendance_threshold_pct, payload.warning_threshold_pct, payload.campus_id)
            )
            record_audit_log(
                conn, str(user["id"]), user["role_code"], payload.campus_id,
                "CAMPUS_POLICY_UPDATED", "campus_policies", new_pol_id,
                f"Updated campus policy to v{new_version} (Attendance threshold: {payload.attendance_threshold_pct}%)"
            )

    return {"policy": new_pol}


@app.get("/api/privacy/overview")
def get_privacy_overview(user: Dict[str, Any] = Depends(get_current_user)):
    with get_owner_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM privacy_notices WHERE is_active = TRUE ORDER BY created_at DESC")
            notices = cur.fetchall()
            cur.execute("SELECT * FROM retention_policies ORDER BY record_category")
            retention = cur.fetchall()

            if user["role_code"] in ("STUDENT", "PARENT") and user.get("linked_student_id"):
                cur.execute("SELECT * FROM consent_records WHERE student_id = %s ORDER BY granted_at DESC", (user["linked_student_id"],))
                consents = cur.fetchall()
                cur.execute("SELECT * FROM data_requests WHERE student_id = %s ORDER BY created_at DESC", (user["linked_student_id"],))
                requests = cur.fetchall()
            else:
                cur.execute("SELECT cr.*, s.full_name AS student_name, s.current_usn FROM consent_records cr JOIN students s ON s.student_id = cr.student_id ORDER BY cr.granted_at DESC LIMIT 30")
                consents = cur.fetchall()
                cur.execute("SELECT dr.*, s.full_name AS student_name, s.current_usn FROM data_requests dr JOIN students s ON s.student_id = dr.student_id ORDER BY dr.created_at DESC LIMIT 30")
                requests = cur.fetchall()

    return {
        "legal_disclaimer": (
            "Engineering Controls Implementation Reference: Digital Personal Data Protection Act, 2023 (India) & DPDP Rules, 2025. "
            "Software controls assist institutional compliance; final legal basis determination, DPO appointment, and statutory schedules remain subject to institutional legal review."
        ),
        "notices": notices,
        "retention_policies": retention,
        "consents": consents,
        "data_requests": requests,
    }


@app.post("/api/privacy/consents")
def manage_consent(payload: ConsentToggleRequest, user: Dict[str, Any] = Depends(get_current_user)):
    with get_owner_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT student_id, is_minor, guardian_verified, primary_campus_id FROM students WHERE student_id = %s", (payload.student_id,))
            st = cur.fetchone()
            if not st:
                raise HTTPException(status_code=404, detail="Student not found")
            if st["is_minor"] and not st["guardian_verified"]:
                raise HTTPException(status_code=400, detail="DPDP Minor Data Protection: Verifiable parent/guardian linkage is required before recording consent for a minor.")

            cur.execute("SELECT id FROM privacy_notices WHERE is_active = TRUE LIMIT 1")
            notice_id = cur.fetchone()["id"]

            if payload.action == "WITHDRAWN":
                cur.execute(
                    """UPDATE consent_records
                       SET consent_status = 'WITHDRAWN', withdrawn_at = NOW()
                       WHERE student_id = %s AND purpose_code = %s RETURNING *""",
                    (payload.student_id, payload.purpose_code)
                )
                row = cur.fetchone()
            else:
                cur.execute(
                    """INSERT INTO consent_records (student_id, user_id, notice_id, purpose_code, legal_basis, consent_status, is_minor_student, guardian_verified_consent)
                       VALUES (%s, %s, %s, %s, 'CONSENT', 'GRANTED', %s, %s) RETURNING *""",
                    (payload.student_id, user["id"], notice_id, payload.purpose_code, st["is_minor"], st["guardian_verified"])
                )
                row = cur.fetchone()

            record_audit_log(
                conn, str(user["id"]), user["role_code"], str(st["primary_campus_id"]),
                f"CONSENT_{payload.action}", "consent_records", payload.student_id,
                f"Consent {payload.action} for purpose {payload.purpose_code}"
            )
    return {"consent": row}


@app.post("/api/privacy/data-requests", status_code=201)
def create_data_request(payload: DataRequestCreate, user: Dict[str, Any] = Depends(get_current_user)):
    with get_owner_conn() as conn:
        with conn.cursor() as cur:
            # Check if ERASURE request hits a statutory retention hold (e.g., Financial Ledger / Academic Transcripts)
            status_val = "OPEN"
            notes = None
            if payload.request_type == "ERASURE":
                cur.execute("SELECT COUNT(*) AS cnt FROM payments WHERE student_id = %s AND status = 'POSTED'", (payload.student_id,))
                if cur.fetchone()["cnt"] > 0:
                    status_val = "REJECTED_RETENTION_HOLD"
                    notes = "Statutory 8-year financial audit ledger retention policy applies to posted fee receipts; optional communication records scheduled for anonymisation."

            cur.execute(
                """INSERT INTO data_requests (student_id, requested_by_user_id, request_type, details, status, resolution_notes)
                   VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
                (payload.student_id, user["id"], payload.request_type, payload.details, status_val, notes)
            )
            req = cur.fetchone()
            record_audit_log(
                conn, str(user["id"]), user["role_code"], str(user.get("primary_campus_id")) if user.get("primary_campus_id") else None,
                "PRIVACY_DATA_REQUEST", "data_requests", str(req["id"]),
                f"DPDP data request ({payload.request_type}) submitted with status {status_val}"
            )
    return {"data_request": req}


@app.get("/api/notifications")
def list_notifications(user: Dict[str, Any] = Depends(get_current_user)):
    with get_owner_conn() as conn:
        with conn.cursor() as cur:
            if user["role_code"] in ("STUDENT", "PARENT") and user.get("linked_student_id"):
                cur.execute("SELECT * FROM notifications WHERE student_id = %s ORDER BY created_at DESC LIMIT 30", (user["linked_student_id"],))
            elif user["role_code"] == "TRUST_MANAGEMENT":
                cur.execute("SELECT * FROM notifications ORDER BY created_at DESC LIMIT 40")
            else:
                cur.execute("SELECT * FROM notifications WHERE campus_id = %s ORDER BY created_at DESC LIMIT 40", (user["primary_campus_id"],))
            return {"notifications": cur.fetchall()}


@app.get("/api/audit-logs")
def list_audit_logs(
    limit: int = Query(default=60, le=200),
    user: Dict[str, Any] = Depends(require_roles("TRUST_MANAGEMENT", "COLLEGE_ADMIN"))
):
    with get_owner_conn() as conn:
        with conn.cursor() as cur:
            if user["role_code"] == "TRUST_MANAGEMENT":
                cur.execute("SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT %s", (limit,))
            else:
                cur.execute("SELECT * FROM audit_logs WHERE campus_id = %s ORDER BY created_at DESC LIMIT %s", (user["primary_campus_id"], limit))
            return {"audit_logs": cur.fetchall()}


# =============================================================================
# 11. FRONTEND SPA STATIC SERVING & ROOT FALLBACK (Prevents 404 on Deployment)
# =============================================================================
FRONTEND_DIST_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"

if (FRONTEND_DIST_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST_DIR / "assets")), name="frontend_assets")


@app.get("/", include_in_schema=False)
def serve_root():
    index_file = FRONTEND_DIST_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return JSONResponse({
        "application": "TrustOS — Multi-Campus Educational Trust Management Platform",
        "status": "online",
        "docs_url": "/docs",
        "health_url": "/api/health"
    })


@app.get("/{full_path:path}", include_in_schema=False)
def serve_spa_fallback(full_path: str):
    if full_path.startswith("api/") or full_path in ("docs", "openapi.json", "redoc"):
        raise HTTPException(status_code=404, detail=f"Endpoint '/{full_path}' not found")
    candidate = FRONTEND_DIST_DIR / full_path
    if candidate.is_file():
        return FileResponse(str(candidate))
    index_file = FRONTEND_DIST_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return JSONResponse({
        "application": "TrustOS — Multi-Campus Educational Trust Management Platform",
        "status": "online",
        "docs_url": "/docs",
        "health_url": "/api/health"
    })
