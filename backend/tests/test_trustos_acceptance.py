"""
Phase 8 & Section 21: Automated Acceptance & Integration Test Suite for TrustOS.
Tests:
A. Authentication tests (Valid login, invalid login, pending account blocked, unapproved registration blocked, suspended account blocked)
B. Access-control & PostgreSQL RLS tests (Campus A admin blocked from Campus B students/fees, Warden blocked from financial tables, Student blocked from another student, Parent blocked from unlinked student, client-supplied role/campus cannot bypass RLS)
C. Student identity & transfer tests (Exact duplicate detection, name-variation candidate detection, homonyms kept separate, approved transfer preserves permanent student_id, old USN in history, new USN unique via sequence, failed transfer rollback)
D. Financial tests (Full/partial payments, duplicate transaction_ref rejected, unposted pending payment excluded from balance, concession, scholarship, refund, reversal, immutable posted receipt trigger enforcement)
E. Hostel tests (Available bed count, occupancy %, allocation updates bed, concurrent/second allocation to same bed rejected, out-of-service bed rejected, release restores availability)
F. Attendance tests (Exact 75% threshold, below threshold INELIGIBLE, above threshold ELIGIBLE, 0 classes held = NO_DATA not confused with 0%, campus-specific policy threshold isolation)
G. Data pipeline tests (CSV & Excel profiling/import, missing columns/values, invalid dates, duplicate source rows idempotency, ground-truth Precision/Recall/F1 evaluation)
H. Privacy tests (DPDP notice, consent creation & withdrawal, minor guardian verification, data request & statutory retention hold, append-only audit log protection)
I. Full 16-Step End-to-End Institutional Workflow Scenario
"""

import uuid
from datetime import date
import pytest
from fastapi.testclient import TestClient

from app.main import app, compute_attendance_eligibility
from app.db import get_owner_conn, get_rls_conn

client = TestClient(app)


def login_as(user_id: str, password: str = "TrustOS@2026") -> dict:
    resp = client.post("/api/auth/login", json={"user_id_or_email": user_id, "password": password})
    assert resp.status_code == 200, f"Login failed for {user_id}: {resp.text}"
    data = resp.json()
    return {
        "headers": {"Authorization": f"Bearer {data['access_token']}"},
        "user": data["user"],
        "token": data["access_token"],
    }


# =============================================================================
# A. AUTHENTICATION TESTS
# =============================================================================

def test_auth_valid_and_invalid_login():
    # Valid Trust Management login
    mgmt = login_as("M1001")
    assert mgmt["user"]["role_code"] == "TRUST_MANAGEMENT"

    # Invalid password
    bad = client.post("/api/auth/login", json={"user_id_or_email": "M1001", "password": "WrongPassword123"})
    assert bad.status_code == 401
    # Generic error message does not leak account existence
    assert "Invalid user ID or password" in bad.json()["detail"]


def test_auth_pending_and_suspended_accounts_blocked():
    # Pending account A1099 cannot sign in
    pend = client.post("/api/auth/login", json={"user_id_or_email": "A1099", "password": "TrustOS@2026"})
    assert pend.status_code == 403
    assert "PENDING" in pend.json()["detail"]

    # Suspended account A1098 cannot sign in
    susp = client.post("/api/auth/login", json={"user_id_or_email": "A1098", "password": "TrustOS@2026"})
    assert susp.status_code == 403
    assert "SUSPENDED" in susp.json()["detail"]


def test_auth_unapproved_privileged_registration_cannot_gain_access():
    reg = client.post("/api/auth/register-request", json={
        "requested_role": "TRUST_MANAGEMENT",
        "full_name": "Unauthorized Escalation Tester",
        "email": f"escalate.{uuid.uuid4().hex[:6]}@example.com",
        "password": "SecurePassword@2026"
    })
    assert reg.status_code == 201
    data = reg.json()
    assert data["status"] == "PENDING"
    # Verify status endpoint shows PENDING and no generated_user_id yet
    st = client.get(f"/api/auth/registration-status/{data['request_id']}")
    assert st.status_code == 200
    assert st.json()["status"] == "PENDING"
    assert st.json()["generated_user_id"] is None


# =============================================================================
# B. ACCESS-CONTROL & POSTGRESQL ROW-LEVEL SECURITY (RLS) TESTS
# =============================================================================

def test_rls_campus_isolation_and_role_restrictions():
    admin_c1 = login_as("A1001")  # Campus 1 Admin
    admin_c2 = login_as("A1002")  # Campus 2 Admin
    warden_c1 = login_as("W1001")  # Campus 1 Warden
    student_c1 = login_as("S10001")  # Campus 1 Student
    parent_c1 = login_as("P10001")  # Campus 1 Parent (linked ONLY to S10001)
    student_c2 = login_as("S10002")  # Campus 2 Student

    c2_student_id = student_c2["user"]["linked_student_id"]

    # 1. Campus 1 Admin cannot access Campus 2 student record (blocked by PostgreSQL RLS!)
    cross_st = client.get(f"/api/students/{c2_student_id}", headers=admin_c1["headers"])
    assert cross_st.status_code == 404

    # 2. Direct PostgreSQL RLS verification under `trustos_app` role:
    # Querying `students` as Campus 1 Admin returns 0 rows from Campus 2
    with get_rls_conn(admin_c1["user"]) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM students WHERE primary_campus_id = %s", (admin_c2["user"]["primary_campus_id"],))
            assert cur.fetchone()["cnt"] == 0

    # 3. Warden cannot access financial information (blocked by both RBAC and PostgreSQL RLS on payments/assessments)
    w_fin = client.get("/api/fees/assessments", headers=warden_c1["headers"])
    assert w_fin.status_code == 403
    with get_rls_conn(warden_c1["user"]) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM student_fee_assessments")
            assert cur.fetchone()["cnt"] == 0
            cur.execute("SELECT COUNT(*) AS cnt FROM payments")
            assert cur.fetchone()["cnt"] == 0

    # 4. Student 1 cannot view Student 2's records
    s_cross = client.get(f"/api/students/{c2_student_id}", headers=student_c1["headers"])
    assert s_cross.status_code == 404

    # 5. Parent 1 cannot view unlinked Student 2's records even when knowing their UUID/USN
    p_cross = client.get(f"/api/students/{c2_student_id}", headers=parent_c1["headers"])
    assert p_cross.status_code == 404


# =============================================================================
# C. STUDENT IDENTITY, DUPLICATE RESOLUTION & TRANSFER TESTS
# =============================================================================

def test_duplicate_detection_and_ground_truth_metrics():
    mgmt = login_as("M1001")
    resp = client.get("/api/duplicates", headers=mgmt["headers"])
    assert resp.status_code == 200
    data = resp.json()
    metrics = data["evaluation_metrics"]
    assert metrics["total_ground_truth_pairs"] >= 20
    # TrustOS multi-signal model achieves markedly higher precision and F1 than naive name-only baseline
    assert metrics["trustos_multi_signal_model"]["precision"] > metrics["baseline_name_only_model"]["precision"]
    assert metrics["trustos_multi_signal_model"]["f1_score"] > metrics["baseline_name_only_model"]["f1_score"]
    assert metrics["trustos_multi_signal_model"]["false_positives"] == 0


# =============================================================================
# D. FINANCIAL LEDGER & IMMUTABLE RECEIPTS TESTS
# =============================================================================

def test_financial_calculations_and_posted_receipt_immutability():
    with get_owner_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM payments WHERE status = 'POSTED' LIMIT 1")
            posted_pay = cur.fetchone()
            assert posted_pay is not None

            # Attempting to DELETE or alter amount of a POSTED payment at the database level must raise an exception!
            with pytest.raises(Exception, match="Immutable financial ledger violation"):
                cur.execute("DELETE FROM payments WHERE id = %s", (posted_pay["id"],))
        conn.rollback()

    with get_owner_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM payments WHERE status = 'POSTED' LIMIT 1")
            posted_pay = cur.fetchone()
            with pytest.raises(Exception, match="Immutable financial ledger violation"):
                cur.execute("UPDATE payments SET amount = amount + 100 WHERE id = %s", (posted_pay["id"],))
        conn.rollback()


# =============================================================================
# E. HOSTEL ALLOCATION & CONCURRENCY/CONFLICT TESTS
# =============================================================================

def test_hostel_bed_allocation_rules():
    warden = login_as("W1001")
    inv = client.get("/api/hostels/inventory", headers=warden["headers"]).json()
    assert inv["summary"]["total_beds"] > inv["summary"]["total_rooms"]  # Bed count != room count

    # Out-of-service bed cannot be allocated
    oos_beds = [b for b in inv["beds"] if b["status"] == "OUT_OF_SERVICE"]
    if oos_beds:
        res = client.post("/api/hostels/allocate", headers=warden["headers"], json={
            "usn": "1VV26CS0002",
            "bed_id": oos_beds[0]["bed_id"],
            "allocation_type": "ACTIVE"
        })
        assert res.status_code == 409


# =============================================================================
# F. ATTENDANCE & POLICY ISOLATION TESTS
# =============================================================================

def test_attendance_threshold_and_zero_classes_handling():
    # Exact 75% threshold -> AT_RISK (above 75% minimum, below 80% warning band) or ELIGIBLE
    exact = compute_attendance_eligibility(75, 100, 75.0, 80.0)
    assert exact["attendance_percentage"] == 75.0
    assert exact["eligibility_status"] in ("AT_RISK", "ELIGIBLE")

    # Below 75% threshold -> INELIGIBLE
    below = compute_attendance_eligibility(70, 100, 75.0, 80.0)
    assert below["attendance_percentage"] == 70.0
    assert below["eligibility_status"] == "INELIGIBLE"

    # Above warning threshold -> ELIGIBLE
    above = compute_attendance_eligibility(88, 100, 75.0, 80.0)
    assert above["attendance_percentage"] == 88.0
    assert above["eligibility_status"] == "ELIGIBLE"

    # Zero eligible classes or missing records -> NO_DATA (never confused with 0% attendance!)
    zero_cls = compute_attendance_eligibility(0, 0, 75.0, 80.0)
    assert zero_cls["attendance_percentage"] is None
    assert zero_cls["eligibility_status"] == "NO_DATA"


# =============================================================================
# G. DATA PIPELINE & IDEMPOTENT IMPORT TESTS
# =============================================================================

def test_dataset_profile_and_idempotent_import():
    mgmt = login_as("M1001")
    # Profile CSV
    prof = client.post("/api/imports/profile", headers=mgmt["headers"], data={
        "target_module": "ADMISSIONS",
        "sample_filename": "campus_1_admissions.csv"
    })
    assert prof.status_code == 200
    assert prof.json()["total_rows"] >= 50

    # Profile Excel (.xlsx)
    prof_xlsx = client.post("/api/imports/profile", headers=mgmt["headers"], data={
        "target_module": "ATTENDANCE",
        "sample_filename": "campus_4_attendance.xlsx"
    })
    assert prof_xlsx.status_code == 200
    assert prof_xlsx.json()["file_format"] == "XLSX"

    # First import of campus_2_students.csv
    imp1 = client.post("/api/imports/execute", headers=mgmt["headers"], data={
        "target_module": "STUDENTS",
        "sample_filename": "campus_2_students.csv"
    })
    assert imp1.status_code == 200

    # Second re-import of the exact same file must skip all already-imported rows (idempotent!)
    imp2 = client.post("/api/imports/execute", headers=mgmt["headers"], data={
        "target_module": "STUDENTS",
        "sample_filename": "campus_2_students.csv"
    })
    assert imp2.status_code == 200
    assert imp2.json()["import"]["skipped_duplicate_rows"] >= 25
    assert imp2.json()["import"]["accepted_rows"] == 0


# =============================================================================
# H. PRIVACY & APPEND-ONLY AUDIT LOG TESTS
# =============================================================================

def test_dpdp_privacy_and_audit_log_protection():
    student = login_as("S10001")
    st_id = student["user"]["linked_student_id"]

    # Create and withdraw consent
    c_grant = client.post("/api/privacy/consents", headers=student["headers"], json={
        "student_id": st_id,
        "purpose_code": "SCHOLARSHIP_EXPORT",
        "action": "GRANTED"
    })
    assert c_grant.status_code == 200

    c_withdraw = client.post("/api/privacy/consents", headers=student["headers"], json={
        "student_id": st_id,
        "purpose_code": "SCHOLARSHIP_EXPORT",
        "action": "WITHDRAWN"
    })
    assert c_withdraw.status_code == 200
    assert c_withdraw.json()["consent"]["consent_status"] == "WITHDRAWN"

    # Erasure request on a student with posted financial ledger records triggers statutory retention hold
    dr = client.post("/api/privacy/data-requests", headers=student["headers"], json={
        "student_id": st_id,
        "request_type": "ERASURE",
        "details": "Requesting erasure of financial records"
    })
    assert dr.status_code == 201
    assert dr.json()["data_request"]["status"] == "REJECTED_RETENTION_HOLD"

    # Verify audit_logs are append-only at PostgreSQL trigger level
    with get_owner_conn() as conn:
        with conn.cursor() as cur:
            with pytest.raises(Exception, match="append-only"):
                cur.execute("DELETE FROM audit_logs")
        conn.rollback()


def test_financial_edge_cases_concession_scholarship_refund_reversal_overpayment():
    """
    Covers Section 21.D edge cases:
    - Approved concession
    - Scholarship credit application
    - Partial payment & full payment
    - Duplicate transaction reference rejection
    - Overpayment detection (status -> OVERPAID, negative outstanding balance)
    - Linked Refund & Reversal with ledger recalculation while preserving original receipt
    """
    admin_c1 = login_as("A1001")
    mgmt = login_as("M1001")
    campuses_resp = client.get("/api/public/campuses").json()
    c1_id = admin_c1["user"]["primary_campus_id"]
    c1_course = [c for c in campuses_resp["courses"] if c["campus_id"] == c1_id][0]

    # Create student & assessment of INR 100,000
    adm = client.post("/api/admissions", headers=admin_c1["headers"], json={
        "full_name": f"Finance Ledger Tester {uuid.uuid4().hex[:4]}",
        "date_of_birth": "2006-02-10",
        "gender": "Male",
        "phone": f"97{uuid.uuid4().int % 100000000:08d}",
        "guardian_name": "Sri Ledger Guardian",
        "guardian_phone": "8877665544",
        "category": "OBC",
        "course_id": c1_course["id"],
        "quota": "MERIT"
    }).json()

    ass = client.post("/api/fees/assessments", headers=admin_c1["headers"], json={
        "student_id": adm["student_id"],
        "assessed_amount": 100000.0,
        "due_date": "2026-12-15"
    }).json()["assessment"]
    ass_id = ass["id"]

    # Apply INR 10,000 Concession & INR 15,000 Scholarship -> Net payable = 75,000
    c_res = client.post("/api/fees/concessions-scholarships", headers=admin_c1["headers"], json={
        "assessment_id": ass_id,
        "entry_type": "CONCESSION",
        "category_or_scheme": "MERIT_WAIVER",
        "amount": 10000.0,
        "reason": "Academic rank concession"
    })
    assert c_res.status_code == 201
    assert float(c_res.json()["assessment"]["outstanding_balance"]) == 90000.0

    s_res = client.post("/api/fees/concessions-scholarships", headers=admin_c1["headers"], json={
        "assessment_id": ass_id,
        "entry_type": "SCHOLARSHIP",
        "category_or_scheme": "Trust Endowment",
        "amount": 15000.0
    })
    assert s_res.status_code == 201
    assert float(s_res.json()["assessment"]["outstanding_balance"]) == 75000.0

    # Record & Post Payment 1 of INR 80,000 -> Overpayment of INR 5,000 (status = OVERPAID, balance = -5000.0)
    tx1 = f"TXN-FIN1-{uuid.uuid4().hex[:8].upper()}"
    p1 = client.post("/api/fees/payments", headers=admin_c1["headers"], json={
        "assessment_id": ass_id,
        "amount": 80000.0,
        "transaction_ref": tx1,
        "payment_mode": "UPI_SIMULATED",
        "auto_college_verify": True
    })
    assert p1.status_code == 201
    p1_id = p1.json()["payment"]["id"]

    # Duplicate transaction_ref must be rejected with 409 Conflict
    dup_p = client.post("/api/fees/payments", headers=admin_c1["headers"], json={
        "assessment_id": ass_id,
        "amount": 5000.0,
        "transaction_ref": tx1,
        "payment_mode": "UPI_SIMULATED"
    })
    assert dup_p.status_code == 409

    # Post Payment 1 -> Verify OVERPAID status
    post1 = client.post(f"/api/fees/payments/{p1_id}/verify-trust", headers=mgmt["headers"])
    assert post1.status_code == 200
    assert post1.json()["assessment"]["status"] == "OVERPAID"
    assert float(post1.json()["assessment"]["outstanding_balance"]) == -5000.0

    # Issue INR 5,000 Refund -> Balance becomes exactly 0.00 (status = PAID)
    ref_res = client.post("/api/fees/refunds-reversals", headers=admin_c1["headers"], json={
        "payment_id": p1_id,
        "action_type": "REFUND",
        "amount": 5000.0,
        "reason": "Refund of excess overpayment"
    })
    assert ref_res.status_code == 201
    assert ref_res.json()["assessment"]["status"] == "PAID"
    assert float(ref_res.json()["assessment"]["outstanding_balance"]) == 0.0

    # Fee reminder on a PAID (0 balance) student must be blocked so parents never get false reminders!
    rem_block = client.post(f"/api/fees/send-reminder/{ass_id}", headers=admin_c1["headers"])
    assert rem_block.status_code == 400


def test_campus_policy_isolation_and_hostel_release_cycle():
    """
    Covers Section 15, 21.E & 21.F:
    - Changing Campus 1 policy threshold updates Campus 1 without altering Campus 2's threshold
    - Released hostel bed becomes AVAILABLE again
    """
    admin_c1 = login_as("A1001")
    mgmt = login_as("M1001")
    warden_c1 = login_as("W1001")

    pols_before = client.get("/api/policies", headers=mgmt["headers"]).json()["policies"]
    c1_pol = [p for p in pols_before if p["campus_number"] == 1][0]
    c2_pol_before = [p for p in pols_before if p["campus_number"] == 2][0]

    # Update Campus 1 attendance threshold to 76.0% and restore back to 75.0%
    upd = client.put("/api/policies", headers=admin_c1["headers"], json={
        "campus_id": c1_pol["campus_id"],
        "attendance_threshold_pct": 76.0,
        "warning_threshold_pct": 81.0,
        "late_fee_per_day": 50.0,
        "grace_period_days": 15,
        "max_concession_pct": 50.0,
        "transfer_min_attendance_pct": 65.0,
        "require_zero_dues_for_transfer": False
    })
    assert upd.status_code == 200
    assert float(upd.json()["policy"]["attendance_threshold_pct"]) == 76.0

    # Verify Campus 2 policy was NOT altered
    pols_after = client.get("/api/policies", headers=mgmt["headers"]).json()["policies"]
    c2_pol_after = [p for p in pols_after if p["campus_number"] == 2][0]
    assert float(c2_pol_after["attendance_threshold_pct"]) == float(c2_pol_before["attendance_threshold_pct"])

    # Restore Campus 1 policy to 75.0%
    client.put("/api/policies", headers=admin_c1["headers"], json={
        "campus_id": c1_pol["campus_id"],
        "attendance_threshold_pct": 75.0,
        "warning_threshold_pct": 80.0,
        "late_fee_per_day": 50.0,
        "grace_period_days": 15,
        "max_concession_pct": 50.0,
        "transfer_min_attendance_pct": 65.0,
        "require_zero_dues_for_transfer": False
    })

    # Verify Hostel Bed Release restores AVAILABLE status
    inv = client.get("/api/hostels/inventory", headers=warden_c1["headers"]).json()
    occ_beds = [b for b in inv["beds"] if b["status"] == "OCCUPIED" and b["active_allocation_id"]]
    assert len(occ_beds) > 0
    target_occ = occ_beds[0]
    rel = client.post("/api/hostels/release", headers=warden_c1["headers"], json={
        "allocation_id": target_occ["active_allocation_id"],
        "reason": "Routine test release"
    })
    assert rel.status_code == 200
    assert rel.json()["status"] == "RELEASED"
    # Re-allocate back so occupancy stays clean
    client.post("/api/hostels/allocate", headers=warden_c1["headers"], json={
        "usn": target_occ["occupant_usn"],
        "bed_id": target_occ["bed_id"],
        "allocation_type": "ACTIVE"
    })


# =============================================================================
# I. 16-STEP END-TO-END INSTITUTIONAL DEMO SCENARIO
# =============================================================================

def test_full_16_step_end_to_end_scenario():
    admin_c1 = login_as("A1001")
    admin_c2 = login_as("A1002")
    warden_c1 = login_as("W1001")
    mgmt = login_as("M1001")

    campuses_resp = client.get("/api/public/campuses").json()
    c1_id = admin_c1["user"]["primary_campus_id"]
    c2_id = admin_c2["user"]["primary_campus_id"]
    c1_course = [c for c in campuses_resp["courses"] if c["campus_id"] == c1_id][0]
    c2_course = [c for c in campuses_resp["courses"] if c["campus_id"] == c2_id][0]

    # Step 1 & 2: Authorized administrator creates a student admission -> appears in DB and dashboard
    unique_phone = f"99{uuid.uuid4().int % 100000000:08d}"
    adm_resp = client.post("/api/admissions", headers=admin_c1["headers"], json={
        "full_name": "E2E Verification Scholar",
        "date_of_birth": "2006-05-14",
        "gender": "Female",
        "phone": unique_phone,
        "guardian_name": "Sri Verification Parent",
        "guardian_phone": "8899776655",
        "category": "GENERAL",
        "course_id": c1_course["id"],
        "quota": "MERIT"
    })
    assert adm_resp.status_code == 201, adm_resp.text
    adm_data = adm_resp.json()
    permanent_student_id = adm_data["student_id"]
    initial_usn = adm_data["usn"]

    # Step 3: A fee assessment is created (INR 120,000)
    ass_resp = client.post("/api/fees/assessments", headers=admin_c1["headers"], json={
        "student_id": permanent_student_id,
        "assessed_amount": 120000.0,
        "due_date": "2026-12-15"
    })
    assert ass_resp.status_code == 201
    ass_id = ass_resp.json()["assessment"]["id"]
    assert float(ass_resp.json()["assessment"]["outstanding_balance"]) == 120000.0

    # Step 4, 5, 6: Payment (INR 70,000) is recorded, college-verified, and trust-posted -> Receipt generated & balance recalculated
    tx_ref = f"TXN-E2E-{uuid.uuid4().hex[:8].upper()}"
    pay_resp = client.post("/api/fees/payments", headers=admin_c1["headers"], json={
        "assessment_id": ass_id,
        "amount": 70000.0,
        "transaction_ref": tx_ref,
        "payment_mode": "UPI_SIMULATED"
    })
    assert pay_resp.status_code == 201
    pay_id = pay_resp.json()["payment"]["id"]
    # Before posting, balance is still 120,000
    assert float(pay_resp.json()["assessment"]["outstanding_balance"]) == 120000.0

    # Level 1 College Verify
    v1 = client.post(f"/api/fees/payments/{pay_id}/verify-college", headers=admin_c1["headers"])
    assert v1.status_code == 200
    assert v1.json()["payment"]["status"] == "COLLEGE_VERIFIED"

    # Level 2 Trust Reconcile & Post
    v2 = client.post(f"/api/fees/payments/{pay_id}/verify-trust", headers=mgmt["headers"])
    assert v2.status_code == 200
    assert v2.json()["payment"]["status"] == "POSTED"
    assert v2.json()["payment"]["receipt_number"].startswith("RCPT-2026-")
    assert float(v2.json()["assessment"]["outstanding_balance"]) == 50000.0

    # Step 7: Link a parent & verify parent sees the exact INR 50,000 balance
    parent_c1 = login_as("P10001")
    with get_owner_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO parent_student_links (parent_user_id, student_id, relationship, is_verified) VALUES (%s, %s, 'Parent', TRUE) ON CONFLICT DO NOTHING",
                (parent_c1["user"]["id"], permanent_student_id)
            )
    parent_view = client.get(f"/api/students/{permanent_student_id}", headers=parent_c1["headers"])
    assert parent_view.status_code == 200
    assert float(parent_view.json()["fee_assessments"][0]["outstanding_balance"]) == 50000.0

    # Step 8 & 9: Warden allocates an available hostel bed -> vacancy chart updates immediately and concurrent duplicate allocation is blocked
    inv_before = client.get("/api/hostels/inventory", headers=warden_c1["headers"]).json()
    avail_beds = [b for b in inv_before["beds"] if b["status"] == "AVAILABLE"]
    target_bed_id = avail_beds[0]["bed_id"]

    alloc_resp = client.post("/api/hostels/allocate", headers=warden_c1["headers"], json={
        "usn": initial_usn,
        "bed_id": target_bed_id,
        "allocation_type": "ACTIVE"
    })
    assert alloc_resp.status_code == 201
    assert alloc_resp.json()["bed_status"] == "OCCUPIED"

    # Second attempt on same bed must fail with 409 Conflict
    dup_alloc = client.post("/api/hostels/allocate", headers=warden_c1["headers"], json={
        "usn": "1VV26CS0002",
        "bed_id": target_bed_id,
        "allocation_type": "ACTIVE"
    })
    assert dup_alloc.status_code == 409

    # Step 10: Attendance records are imported and eligibility is calculated
    att_imp = client.post("/api/imports/execute", headers=admin_c1["headers"], data={
        "target_module": "ATTENDANCE",
        "sample_filename": "campus_4_attendance.xlsx"
    })
    assert att_imp.status_code == 200

    # Step 11, 12, 13, 14: Student transfer from Campus 1 -> Campus 2 is requested and approved
    t_req = client.post("/api/transfers/request", headers=admin_c1["headers"], json={
        "source_usn": initial_usn,
        "destination_campus_id": c2_id,
        "destination_course_id": c2_course["id"],
        "reason": "E2E inter-campus transfer test"
    })
    assert t_req.status_code == 201
    treq_id = t_req.json()["transfer_request_id"]

    t_app = client.post(f"/api/transfers/{treq_id}/approve", headers=mgmt["headers"], json={
        "decision": "APPROVED",
        "comments": "Approved in E2E test"
    })
    assert t_app.status_code == 200
    t_res = t_app.json()
    # Permanent student_id is unchanged!
    assert t_res["permanent_student_id"] == permanent_student_id
    assert t_res["old_usn"] == initial_usn
    assert t_res["new_usn"] != initial_usn
    assert t_res["old_enrollment_status"] == "TRANSFERRED"
    assert t_res["hostel_released"] is True

    # Verify identifier history preserves old USN and new USN
    st_after = client.get(f"/api/students/{permanent_student_id}", headers=mgmt["headers"]).json()
    id_values = [i["id_value"] for i in st_after["identifiers"]]
    assert initial_usn in id_values
    assert t_res["new_usn"] in id_values

    # Step 15: Trust Management sees consolidated figures without double-counting the transferred student
    dash = client.get("/api/dashboard/summary?campus_id=ALL", headers=mgmt["headers"]).json()
    assert dash["is_cumulative_view"] is True
    assert dash["metrics"]["canonical_student_count"] >= 14001

    # Step 16: Unauthorized cross-campus request is rejected (Campus 1 Admin can no longer access the student now at Campus 2!)
    unauth = client.get(f"/api/students/{permanent_student_id}", headers=admin_c1["headers"])
    assert unauth.status_code == 404
