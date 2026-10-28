"""
Phase 3: Deterministic Synthetic Environment & Imperfect Raw Source Dataset Generator.
Generates:
1. Clean Canonical PostgreSQL Dataset:
   - 1 Educational Trust ("VidyaVikas Multi-Campus Educational Trust")
   - 6 Campuses (2 Engineering, 2 Polytechnic, 2 Schools)
   - 14,000 Canonical Students with permanent UUID `student_id`, USNs, and enrollments
   - Campus-specific Fee Structures, 14,000 Student Fee Assessments, Concessions, Scholarships, Payments, and Refunds
   - Hostel Buildings, Rooms, Individual Beds, and Active/Reserved Allocations
   - Subjects, Dated Attendance Sessions, Attendance Records, Academic Progress & Exam Results
   - Scholarship Schemes, Applications, and Government Reimbursement Claims
   - Student Transfers with preserved permanent `student_id` and historical USNs
   - Role-specific Demo Accounts (Trust Management, 6 College Admins, 6 Wardens, Students, Linked Parents)
   - DPDP Act 2023 Privacy Notices, Consents, Retention Policies, and Data Requests

2. Deliberately Imperfect Source Datasets (`data/raw_sources/`):
   - `campus_1_admissions.csv`
   - `campus_2_students.csv`
   - `campus_3_fee_records.csv`
   - `campus_4_attendance.xlsx`
   - `campus_5_hostel_inventory.csv`
   - `campus_6_scholarships.csv`
   - `campus_transfer_records.csv`
   - `ground_truth_duplicates.csv` (Explicit ground-truth labels for duplicate reconciliation precision/recall/F1)
"""

import os
import csv
import json
import uuid
import random
import hashlib
from datetime import date, datetime, timedelta
from pathlib import Path
import bcrypt
import pandas as pd
from app.db import get_owner_conn
from psycopg.pq import Format


def bulk_insert(cur, sql: str, rows: list):
    if not rows:
        return
    with cur.copy(sql) as copy:
        for r in rows:
            copy.write_row(r)


SEED = 20261028

FIRST_NAMES = [
    "Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Reyansh", "Ayaan", "Krishna", "Ishaan",
    "Ananya", "Diya", "Aditi", "Kavya", "Meera", "Saanvi", "Priya", "Neha", "Riya", "Sneha",
    "Rohan", "Karthik", "Pranav", "Siddharth", "Nikhil", "Varun", "Harsha", "Darshan", "Tejas", "Akash",
    "Pooja", "Divya", "Shruti", "Nandini", "Anjali", "Swati", "Bhavya", "Tanvi", "Chaitra", "Deepika"
]

LAST_NAMES = [
    "Sharma", "Verma", "Reddy", "Gowda", "Patil", "Kulkarni", "Rao", "Nair", "Iyer", "Hegde",
    "Shetty", "Naik", "Joshi", "Deshpande", "Menon", "Pillai", "Kamble", "Bhat", "Murthy", "Chavan",
    "Kumar", "Singh", "Gupta", "Mehta", "Mishra", "Pandey", "Chatterjee", "Das", "Bose", "Sen"
]

CATEGORIES = ["GENERAL", "OBC", "SC", "ST", "EWS"]
QUOTAS = ["MERIT", "GOVERNMENT", "MANAGEMENT", "RTE"]
BLOOD_GROUPS = ["O+", "A+", "B+", "AB+", "O-", "A-", "B-"]


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("utf-8")


def normalize_name(name: str) -> str:
    return "".join(ch.lower() for ch in name if ch.isalnum())


def det_uuid(namespace_key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"trustos.{namespace_key}"))


def seed_all(total_students: int = 14000):
    rng = random.Random(SEED)
    base_dir = Path(__file__).resolve().parents[1]
    raw_dir = base_dir / "data" / "raw_sources"
    raw_dir.mkdir(parents=True, exist_ok=True)

    print(f"[Seed] Connecting to PostgreSQL and checking state...")
    with get_owner_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM students")
            existing_count = cur.fetchone()["cnt"]
            if existing_count >= total_students:
                print(f"[Seed] Database already contains {existing_count} canonical students. Ensuring raw files exist...")
                generate_imperfect_source_files(conn, raw_dir, rng)
                return {"status": "already_seeded", "students": existing_count}

            print("[Seed] Cleaning existing tables for deterministic fresh seed...")
            cur.execute("""
                TRUNCATE TABLE
                    reimbursement_status_history, government_reimbursement_claims, scholarship_awards,
                    scholarship_applications, scholarship_schemes,
                    academic_progress_records, examination_results, attendance_records, attendance_sessions, subjects,
                    hostel_allocation_history, hostel_allocations, hostel_beds, hostel_rooms, hostel_buildings,
                    financial_audit_events, financial_adjustments, refunds, payment_allocations, payments,
                    scholarships, concessions, fee_assessment_lines, student_fee_assessments, fee_structures, fee_heads,
                    transfer_approvals, transfer_history, transfer_requests, campus_enrollments, admissions,
                    duplicate_match_candidates, data_quality_issues, dataset_column_mappings, dataset_imports,
                    notifications, data_requests, consent_records, privacy_notices, retention_policies,
                    registration_requests, parent_student_links, user_campus_assignments, user_roles, users,
                    student_source_records, student_identifiers, students,
                    campus_policies, courses, academic_years, campuses, campus_types, trusts
                RESTART IDENTITY CASCADE;
            """)

            # 1. Trust & Campus Types
            trust_id = det_uuid("trust.vidyavikas")
            cur.execute(
                "INSERT INTO trusts (id, name, code, headquarters, established_year) VALUES (%s, %s, %s, %s, %s)",
                (trust_id, "VidyaVikas Multi-Campus Educational Trust", "VVMET", "Bengaluru, Karnataka", 1988)
            )

            ct_eng = det_uuid("campus_type.ENG")
            ct_poly = det_uuid("campus_type.POLY")
            ct_sch = det_uuid("campus_type.SCH")
            cur.executemany(
                "INSERT INTO campus_types (id, code, name, description) VALUES (%s, %s, %s, %s)",
                [
                    (ct_eng, "ENGINEERING", "Engineering College", "AICTE/VTU Affiliated 4-Year B.E./B.Tech Institution"),
                    (ct_poly, "POLYTECHNIC", "Polytechnic Institute", "DTE 3-Year Diploma Technical Institution"),
                    (ct_sch, "SCHOOL", "K-12 Public School", "CBSE/State Board Secondary & Senior Secondary School"),
                ]
            )

            # 2. Six Campuses with realistic distributions summing to 14,000 students
            campuses_spec = [
                (1, "VVE-BLR", "VidyaVikas Institute of Technology, Bengaluru", "Bengaluru", ct_eng, "1VV26", 3400, 75.0, 145000),
                (2, "VVE-MYS", "VidyaVikas College of Engineering, Mysuru", "Mysuru", ct_eng, "4VM26", 2800, 75.0, 130000),
                (3, "VVP-HBL", "VidyaVikas Polytechnic, Hubballi", "Hubballi", ct_poly, "2VP26", 2100, 75.0, 58000),
                (4, "VVP-MLR", "VidyaVikas Memorial Polytechnic, Mangaluru", "Mangaluru", ct_poly, "3MP26", 1900, 72.0, 54000),
                (5, "VVS-BGV", "VidyaVikas Central School, Belagavi", "Belagavi", ct_sch, "5VS26", 2000, 75.0, 42000),
                (6, "VVS-TMK", "VidyaVikas Public School, Tumakuru", "Tumakuru", ct_sch, "6TS26", 1800, 70.0, 38000),
            ]
            # Adjust counts if total_students != 14000
            scale = total_students / 14000.0
            campus_rows = []
            campus_map = {}
            for c_num, c_code, c_name, city, c_type, usn_pfx, base_cnt, att_thresh, base_fee in campuses_spec:
                cid = det_uuid(f"campus.{c_num}")
                cnt = int(round(base_cnt * scale))
                campus_rows.append((cid, trust_id, c_type, c_num, c_code, c_name, city, "Karnataka", usn_pfx))
                campus_map[c_num] = {
                    "id": cid, "code": c_code, "name": c_name, "city": city, "type_id": c_type,
                    "usn_prefix": usn_pfx, "target_students": cnt, "att_threshold": att_thresh, "base_fee": base_fee
                }
            # Ensure exact sum == total_students
            diff = total_students - sum(c["target_students"] for c in campus_map.values())
            campus_map[1]["target_students"] += diff

            cur.executemany(
                """INSERT INTO campuses (id, trust_id, campus_type_id, campus_number, code, name, city, state, usn_prefix)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                campus_rows
            )

            # 3. Academic Years
            ay_prev = det_uuid("ay.2025-26")
            ay_curr = det_uuid("ay.2026-27")
            cur.executemany(
                "INSERT INTO academic_years (id, code, start_date, end_date, is_current) VALUES (%s, %s, %s, %s, %s)",
                [
                    (ay_prev, "2025-26", date(2025, 8, 1), date(2026, 5, 31), False),
                    (ay_curr, "2026-27", date(2026, 8, 1), date(2027, 5, 31), True),
                ]
            )

            # 4. Courses, Policies, Fee Heads & Structures, Subjects per Campus
            fee_heads_spec = [
                (det_uuid("fh.TUITION"), "TUITION", "Tuition Fee", False),
                (det_uuid("fh.LAB"), "LAB", "Laboratory & Computer Fee", False),
                (det_uuid("fh.LIBRARY"), "LIBRARY", "Library & Digital Resources", False),
                (det_uuid("fh.EXAM"), "EXAM", "Examination & Evaluation Fee", False),
                (det_uuid("fh.DEV"), "DEVELOPMENT", "Campus Infrastructure Development", False),
                (det_uuid("fh.CAUTION"), "CAUTION", "Refundable Caution Deposit", True),
            ]
            cur.executemany(
                "INSERT INTO fee_heads (id, code, name, is_refundable) VALUES (%s, %s, %s, %s)",
                fee_heads_spec
            )

            courses_by_campus = {}
            fee_structures_by_course = {}
            subjects_by_course = {}

            for c_num, c_info in campus_map.items():
                cid = c_info["id"]
                # Policy
                pol_id = det_uuid(f"policy.{c_num}")
                cur.execute(
                    """INSERT INTO campus_policies (
                        id, campus_id, academic_year_id, version, attendance_threshold_pct, warning_threshold_pct,
                        late_fee_per_day, grace_period_days, max_concession_pct, transfer_min_attendance_pct,
                        require_zero_dues_for_transfer, policy_json
                    ) VALUES (%s, %s, %s, 1, %s, %s, %s, %s, 50.0, 65.0, FALSE, %s)""",
                    (
                        pol_id, cid, ay_curr, c_info["att_threshold"], c_info["att_threshold"] + 5.0,
                        50.0 if c_num <= 2 else 25.0, 15,
                        json.dumps({"campus_code": c_info["code"], "allow_installments": True, "biometric_attendance": c_num <= 4})
                    )
                )

                if c_num in (1, 2):
                    c_defs = [("CS", "B.E. Computer Science & Engineering", 4, 8), ("EC", "B.E. Electronics & Comm.", 4, 8), ("ME", "B.E. Mechanical Engineering", 4, 8)]
                elif c_num in (3, 4):
                    c_defs = [("DCS", "Diploma in Computer Science", 3, 6), ("DEC", "Diploma in Electronics", 3, 6), ("DCE", "Diploma in Civil Engg", 3, 6)]
                else:
                    c_defs = [("G10", "Class X Secondary Stream", 1, 2), ("G12S", "Class XII Science Stream", 2, 4), ("G12C", "Class XII Commerce Stream", 2, 4)]

                courses_by_campus[c_num] = []
                for code, name, dur, sems in c_defs:
                    course_id = det_uuid(f"course.{c_num}.{code}")
                    cur.execute(
                        "INSERT INTO courses (id, campus_id, code, name, duration_years, total_semesters, max_intake) VALUES (%s, %s, %s, %s, %s, %s, 400)",
                        (course_id, cid, code, name, dur, sems)
                    )
                    courses_by_campus[c_num].append({"id": course_id, "code": code, "name": name})

                    # Fee structure
                    fs_id = det_uuid(f"fs.{c_num}.{code}")
                    total_fee = float(c_info["base_fee"] + (10000 if code in ("CS", "G12S") else 0))
                    breakdown = {
                        "TUITION": round(total_fee * 0.70, 2),
                        "LAB": round(total_fee * 0.12, 2),
                        "LIBRARY": round(total_fee * 0.05, 2),
                        "EXAM": round(total_fee * 0.05, 2),
                        "DEVELOPMENT": round(total_fee * 0.08, 2),
                    }
                    cur.execute(
                        """INSERT INTO fee_structures (id, campus_id, course_id, academic_year_id, year_of_study, total_amount, due_date, breakdown_json)
                           VALUES (%s, %s, %s, %s, 1, %s, %s, %s)""",
                        (fs_id, cid, course_id, ay_curr, total_fee, date(2026, 11, 15), json.dumps(breakdown))
                    )
                    fee_structures_by_course[course_id] = {"id": fs_id, "amount": total_fee, "breakdown": breakdown}

                    # Subjects (3 per course)
                    subjects_by_course[course_id] = []
                    for s_idx in range(1, 4):
                        sub_id = det_uuid(f"sub.{c_num}.{code}.{s_idx}")
                        sub_code = f"{code}10{s_idx}"
                        sub_name = f"{name.split()[-1]} Core Paper {s_idx}"
                        cur.execute(
                            "INSERT INTO subjects (id, campus_id, course_id, code, name, semester, credits) VALUES (%s, %s, %s, %s, %s, 1, 4)",
                            (sub_id, cid, course_id, sub_code, sub_name)
                        )
                        subjects_by_course[course_id].append(sub_id)

            # 5. Scholarship Schemes
            schemes = [
                (det_uuid("sch.SSP"), "SSP_POST_MATRIC", "State Scholarship Portal (SSP) Post-Matric", "Govt of Karnataka", 65000.00),
                (det_uuid("sch.NSP"), "NSP_MERIT", "National Scholarship Portal Merit-cum-Means", "Ministry of Education", 50000.00),
                (det_uuid("sch.PRAGATI"), "AICTE_PRAGATI", "AICTE Pragati Scholarship for Girls", "AICTE", 50000.00),
                (det_uuid("sch.RTE"), "RTE_REIMBURSEMENT", "Right to Education (RTE) State Reimbursement", "Dept of School Education", 38000.00),
            ]
            cur.executemany(
                "INSERT INTO scholarship_schemes (id, scheme_code, name, sponsoring_agency, max_annual_amount) VALUES (%s, %s, %s, %s, %s)",
                schemes
            )

            # 6. Seed Default Users for all 5 Roles
            default_pw_hash = hash_password("TrustOS@2026")
            users_to_insert = []
            user_roles_to_insert = []
            user_campuses_to_insert = []

            # Trust Management (M1001)
            mgmt_uid = det_uuid("user.M1001")
            users_to_insert.append((
                mgmt_uid, "M1001", "Dr. Rajendra Prasad Hegde (Trust Chairman)", "chairman@vidyavikas.edu.in",
                "9845011001", default_pw_hash, "TRUST_MANAGEMENT", "ACTIVE", campus_map[1]["id"], None
            ))
            user_roles_to_insert.append((det_uuid("ur.M1001"), mgmt_uid, "TRUST_MANAGEMENT"))

            # 6 College Administrators (A1001..A1006) & 6 Hostel Wardens (W1001..W1006)
            admin_uids = {}
            warden_uids = {}
            for c_num, c_info in campus_map.items():
                aid = det_uuid(f"user.A100{c_num}")
                admin_uids[c_num] = aid
                users_to_insert.append((
                    aid, f"A100{c_num}", f"Prof. Admin {c_info['code']} ({c_info['city']})",
                    f"admin.c{c_num}@vidyavikas.edu.in", f"984502100{c_num}", default_pw_hash,
                    "COLLEGE_ADMIN", "ACTIVE", c_info["id"], None
                ))
                user_roles_to_insert.append((det_uuid(f"ur.A100{c_num}"), aid, "COLLEGE_ADMIN"))
                user_campuses_to_insert.append((det_uuid(f"uca.A100{c_num}"), aid, c_info["id"], True))

                wid = det_uuid(f"user.W100{c_num}")
                warden_uids[c_num] = wid
                users_to_insert.append((
                    wid, f"W100{c_num}", f"Warden Ramesh {c_info['code']}",
                    f"warden.c{c_num}@vidyavikas.edu.in", f"984503100{c_num}", default_pw_hash,
                    "HOSTEL_WARDEN", "ACTIVE", c_info["id"], None
                ))
                user_roles_to_insert.append((det_uuid(f"ur.W100{c_num}"), wid, "HOSTEL_WARDEN"))
                user_campuses_to_insert.append((det_uuid(f"uca.W100{c_num}"), wid, c_info["id"], True))

            # Also add 1 PENDING and 1 SUSPENDED account for authentication testing
            pending_uid = det_uuid("user.A1099")
            users_to_insert.append((
                pending_uid, "A1099", "Pending Admin Applicant", "pending@vidyavikas.edu.in",
                "9845099001", default_pw_hash, "COLLEGE_ADMIN", "PENDING", campus_map[1]["id"], None
            ))
            suspended_uid = det_uuid("user.A1098")
            users_to_insert.append((
                suspended_uid, "A1098", "Suspended Operator Account", "suspended@vidyavikas.edu.in",
                "9845099002", default_pw_hash, "COLLEGE_ADMIN", "SUSPENDED", campus_map[1]["id"], None
            ))

            cur.executemany(
                """INSERT INTO users (id, display_user_id, full_name, email, phone, password_hash, role_code, status, primary_campus_id, linked_student_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                users_to_insert
            )
            cur.executemany(
                "INSERT INTO user_roles (id, user_id, role_code) VALUES (%s, %s, %s)",
                user_roles_to_insert
            )
            cur.executemany(
                "INSERT INTO user_campus_assignments (id, user_id, campus_id, is_primary) VALUES (%s, %s, %s, %s)",
                user_campuses_to_insert
            )

            # 7. Hostel Inventory across all 6 Campuses (12 Hostel Buildings, 240 Rooms, 960 Beds)
            print("[Seed] Generating Hostel Buildings, Rooms, and 960 Individual Beds...")
            buildings_rows = []
            rooms_rows = []
            beds_rows = []
            available_beds_by_campus = {c_num: [] for c_num in range(1, 7)}

            for c_num, c_info in campus_map.items():
                cid = c_info["id"]
                for b_idx, (b_code, b_name, gender) in enumerate([
                    (f"HB-{c_num}A", f"{c_info['city']} Boys Hostel Block A", "BOYS"),
                    (f"HG-{c_num}B", f"{c_info['city']} Girls Hostel Block B", "GIRLS"),
                ], start=1):
                    bid = det_uuid(f"hostel.b.{c_num}.{b_idx}")
                    buildings_rows.append((bid, cid, b_code, b_name, gender, 2, warden_uids[c_num]))
                    for r_idx in range(1, 21):  # 20 rooms per building
                        rid = det_uuid(f"hostel.r.{c_num}.{b_idx}.{r_idx}")
                        floor_no = 1 if r_idx <= 10 else 2
                        room_no = f"{floor_no}{r_idx:02d}"
                        rooms_rows.append((rid, bid, cid, room_no, floor_no, "STANDARD_4_SHARE", 4, 48000.00))
                        for bed_let in ("A", "B", "C", "D"):
                            bed_id = det_uuid(f"hostel.bed.{c_num}.{b_idx}.{r_idx}.{bed_let}")
                            bed_code = f"{room_no}-{bed_let}"
                            # Mark a small slice as OUT_OF_SERVICE or RESERVED, rest AVAILABLE initially
                            if r_idx == 20 and bed_let == "D":
                                status = "OUT_OF_SERVICE"
                            elif r_idx == 19 and bed_let in ("C", "D"):
                                status = "RESERVED"
                            else:
                                status = "AVAILABLE"
                                available_beds_by_campus[c_num].append((bed_id, rid, bid))
                            beds_rows.append((bed_id, rid, bid, cid, bed_code, status, None))

            cur.executemany(
                "INSERT INTO hostel_buildings (id, campus_id, code, name, gender_type, total_floors, warden_user_id) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                buildings_rows
            )
            cur.executemany(
                "INSERT INTO hostel_rooms (id, building_id, campus_id, room_number, floor_number, room_type, capacity, annual_fee) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                rooms_rows
            )
            cur.executemany(
                "INSERT INTO hostel_beds (id, room_id, building_id, campus_id, bed_code, status, current_student_id) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                beds_rows
            )

            # 8. Generate 14,000 Canonical Students & Associated Module Records in Batch
            print(f"[Seed] Generating {total_students} Canonical Students and full relational records across 6 Campuses...")
            students_rows = []
            identifiers_rows = []
            admissions_rows = []
            enrollments_rows = []
            assessments_rows = []
            concessions_rows = []
            scholarships_rows = []
            payments_rows = []
            refunds_rows = []
            progress_rows = []
            reimbursements_rows = []
            hostel_alloc_rows = []
            bed_occupy_updates = []

            global_idx = 0
            first_student_by_campus = {}

            for c_num, c_info in campus_map.items():
                cid = c_info["id"]
                c_courses = courses_by_campus[c_num]
                is_school = c_num in (5, 6)
                c_beds = available_beds_by_campus[c_num]
                bed_ptr = 0

                for local_idx in range(1, c_info["target_students"] + 1):
                    global_idx += 1
                    st_id = det_uuid(f"student.canonical.{global_idx}")
                    fname = FIRST_NAMES[(global_idx * 7 + c_num) % len(FIRST_NAMES)]
                    lname = LAST_NAMES[(global_idx * 13 + c_num * 3) % len(LAST_NAMES)]
                    full_name = f"{fname} {lname}"
                    norm_name = normalize_name(full_name)

                    if is_school:
                        dob = date(2010 + (local_idx % 3), ((local_idx % 12) + 1), ((local_idx % 28) + 1))
                        is_minor = True
                    else:
                        dob = date(2005 + (local_idx % 4), ((local_idx % 12) + 1), ((local_idx % 28) + 1))
                        is_minor = False

                    gender = "Female" if (global_idx % 2 == 0) else "Male"
                    bg = BLOOD_GROUPS[global_idx % len(BLOOD_GROUPS)]
                    cat = CATEGORIES[global_idx % len(CATEGORIES)]
                    course = c_courses[local_idx % len(c_courses)]
                    course_id = course["id"]
                    usn = f"{c_info['usn_prefix']}{course['code']}{local_idx:04d}"

                    phone = f"9{c_num}{global_idx:08d}"[:10]
                    g_name = f"Sri/Smt {LAST_NAMES[(global_idx + 5) % len(LAST_NAMES)]} {lname}"
                    g_phone = f"8{c_num}{global_idx:08d}"[:10]

                    students_rows.append((
                        st_id, full_name, norm_name, dob, gender, is_minor, bg,
                        f"{usn.lower()}@student.vidyavikas.edu.in", phone,
                        g_name, g_phone, f"parent.{usn.lower()}@example.com",
                        cat, cid, usn, "SYNTHETIC"
                    ))

                    if local_idx == 1:
                        first_student_by_campus[c_num] = {
                            "student_id": st_id, "usn": usn, "full_name": full_name,
                            "campus_id": cid, "course_id": course_id
                        }

                    # Identifier
                    identifiers_rows.append((
                        det_uuid(f"ident.usn.{global_idx}"), st_id, cid, "USN", usn, True, "Initial canonical USN"
                    ))

                    # Admission & Enrollment
                    adm_no = f"ADM-{c_info['code']}-2026-{local_idx:04d}"
                    quota = QUOTAS[global_idx % len(QUOTAS)]
                    admissions_rows.append((
                        det_uuid(f"adm.{global_idx}"), st_id, cid, course_id, ay_curr, adm_no, date(2026, 7, 15), quota, "CONFIRMED"
                    ))

                    enr_id = det_uuid(f"enr.{global_idx}")
                    enrollments_rows.append((
                        enr_id, st_id, cid, course_id, ay_curr, usn, (local_idx % 3) + 1,
                        chr(65 + (local_idx % 3)), "ACTIVE", date(2026, 8, 1)
                    ))

                    # Fee Assessment & Financial Ledger
                    fs = fee_structures_by_course[course_id]
                    ass_id = det_uuid(f"ass.{global_idx}")
                    assessed = fs["amount"]
                    concession_amt = 10000.00 if (local_idx % 10 == 0) else 0.00
                    scholarship_amt = 15000.00 if (local_idx % 8 == 0) else 0.00
                    net_payable = assessed - concession_amt - scholarship_amt

                    # Payment distribution across 14,000 students
                    mod_p = local_idx % 10
                    refund_amt = 0.00
                    if mod_p in (0, 1, 2, 3, 4):  # 50% Fully Paid (POSTED)
                        paid_amt = net_payable
                        pay_status = "POSTED"
                        ass_status = "PAID"
                    elif mod_p in (5, 6, 7):  # 30% Partial Payment (POSTED)
                        paid_amt = round(net_payable * 0.5, 2)
                        pay_status = "POSTED"
                        ass_status = "PARTIAL"
                    elif mod_p == 8:  # 10% Pending Verification (unposted -> does NOT reduce balance yet!)
                        paid_amt = 0.00
                        pay_status = "PENDING_COLLEGE_VERIFICATION"
                        ass_status = "PENDING"
                    else:  # 10% Overdue or Refunded sample
                        if local_idx % 50 == 9:
                            paid_amt = net_payable
                            refund_amt = 5000.00
                            pay_status = "POSTED"
                            ass_status = "PARTIAL"
                        else:
                            paid_amt = 0.00
                            pay_status = None
                            ass_status = "OVERDUE"

                    net_posted = max(paid_amt - refund_amt, 0.00)
                    outstanding = assessed - concession_amt - scholarship_amt - net_posted
                    due_dt = date(2026, 9, 15) if ass_status == "OVERDUE" else date(2026, 11, 30)

                    assessments_rows.append((
                        ass_id, st_id, cid, enr_id, ay_curr, fs["id"],
                        assessed, concession_amt, scholarship_amt, 0.00,
                        net_posted, refund_amt, outstanding, due_dt, ass_status
                    ))

                    if concession_amt > 0:
                        concessions_rows.append((
                            det_uuid(f"conc.{global_idx}"), ass_id, st_id, cid, "MERIT_WAIVER", concession_amt, "APPROVED", "Merit rank concession"
                        ))
                    if scholarship_amt > 0:
                        scholarships_rows.append((
                            det_uuid(f"sch_credit.{global_idx}"), ass_id, st_id, cid, "Trust Merit Endowment", scholarship_amt, "APPROVED"
                        ))

                    if pay_status is not None:
                        pay_id = det_uuid(f"pay.{global_idx}")
                        tx_amount = paid_amt if pay_status == "POSTED" else round(net_payable * 0.5, 2)
                        receipt_no = f"RCPT-2026-{500000 + global_idx}" if pay_status == "POSTED" else None
                        posted_ts = datetime(2026, 9, 10, 11, 0) if pay_status == "POSTED" else None
                        payments_rows.append((
                            pay_id, ass_id, st_id, cid, f"TXN-{c_info['code']}-{global_idx:06d}",
                            receipt_no, tx_amount, "UPI_SIMULATED", pay_status, posted_ts, True
                        ))
                        if refund_amt > 0:
                            refunds_rows.append((
                                det_uuid(f"ref.{global_idx}"), pay_id, ass_id, st_id, cid,
                                f"REF-{c_info['code']}-{global_idx:06d}", refund_amt, "Excess Lab Deposit Refund", "COMPLETED"
                            ))

                    # Attendance & Academic Progress
                    total_held = 60
                    if local_idx % 12 == 0:
                        attended = 38  # ~63.33% -> INELIGIBLE
                    elif local_idx % 9 == 0:
                        attended = 46  # ~76.67% -> AT_RISK
                    else:
                        attended = 48 + (local_idx % 12)  # 80% - 98% -> ELIGIBLE
                    att_pct = round((attended / total_held) * 100.0, 2)
                    thresh = c_info["att_threshold"]
                    if att_pct < thresh:
                        elig = "INELIGIBLE"
                    elif att_pct < thresh + 5.0:
                        elig = "AT_RISK"
                    else:
                        elig = "ELIGIBLE"

                    cgpa = round(6.5 + ((global_idx % 32) * 0.1), 2)
                    progress_rows.append((
                        det_uuid(f"prog.{global_idx}"), st_id, cid, course_id, ay_curr,
                        total_held, attended, att_pct, thresh, elig, cgpa, round(cgpa - 0.2, 2), round(cgpa + 0.1, 2),
                        1 if elig == "INELIGIBLE" else 0
                    ))

                    # Hostel Allocation for ~68% of available beds per campus
                    if bed_ptr < int(len(c_beds) * 0.68) and (local_idx % 15 == 1):
                        bed_id, rid, bid = c_beds[bed_ptr]
                        bed_ptr += 1
                        hostel_alloc_rows.append((
                            det_uuid(f"halloc.{global_idx}"), bed_id, rid, bid, cid, st_id, ay_curr, "ACTIVE", warden_uids[c_num]
                        ))
                        bed_occupy_updates.append((st_id, bed_id))

                    # Scholarship & Government Reimbursement Claims (~15% of students)
                    if local_idx % 7 == 0:
                        sch_scheme = schemes[(global_idx) % len(schemes)]
                        sanc_amt = 45000.00 if c_num <= 2 else 28000.00
                        cl_status = ["PENDING_STATE_APPROVAL", "PARTIALLY_REIMBURSED", "SETTLED", "SUBMITTED_TO_PORTAL"][global_idx % 4]
                        if cl_status == "SETTLED":
                            disb = sanc_amt
                        elif cl_status == "PARTIALLY_REIMBURSED":
                            disb = round(sanc_amt * 0.5, 2)
                        else:
                            disb = 0.00
                        pend_amt = sanc_amt - disb
                        reimbursements_rows.append((
                            det_uuid(f"reimb.{global_idx}"), st_id, cid, sch_scheme[0], ay_curr,
                            f"GOV-CLM-{c_info['code']}-{global_idx:05d}", sanc_amt, sanc_amt, sanc_amt, disb, pend_amt,
                            cl_status, date(2026, 9, 20), True
                        ))

            # Bulk insert all 14,000 student rows and child tables using fast PostgreSQL COPY
            print("[Seed] Executing high-speed PostgreSQL COPY for 14,000 students and child tables...")
            bulk_insert(
                cur,
                """COPY students (
                    student_id, full_name, normalized_name, date_of_birth, gender, is_minor, blood_group,
                    email, phone, guardian_name, guardian_phone, guardian_email,
                    category, primary_campus_id, current_usn, data_origin
                ) FROM STDIN""",
                students_rows
            )
            bulk_insert(
                cur,
                "COPY student_identifiers (id, student_id, campus_id, id_type, id_value, is_active, notes) FROM STDIN",
                identifiers_rows
            )
            bulk_insert(
                cur,
                "COPY admissions (id, student_id, campus_id, course_id, academic_year_id, admission_number, admission_date, quota, status) FROM STDIN",
                admissions_rows
            )
            bulk_insert(
                cur,
                "COPY campus_enrollments (id, student_id, campus_id, course_id, academic_year_id, usn, year_of_study, section, status, enrolled_at) FROM STDIN",
                enrollments_rows
            )
            bulk_insert(
                cur,
                """COPY student_fee_assessments (
                    id, student_id, campus_id, enrollment_id, academic_year_id, fee_structure_id,
                    assessed_amount, concession_amount, scholarship_amount, adjustments_amount,
                    net_posted_payments, refunded_amount, outstanding_balance, due_date, status
                ) FROM STDIN""",
                assessments_rows
            )
            bulk_insert(
                cur,
                "COPY concessions (id, assessment_id, student_id, campus_id, concession_type, amount, status, reason) FROM STDIN",
                concessions_rows
            )
            bulk_insert(
                cur,
                "COPY scholarships (id, assessment_id, student_id, campus_id, scheme_name, amount, status) FROM STDIN",
                scholarships_rows
            )
            bulk_insert(
                cur,
                """COPY payments (
                    id, assessment_id, student_id, campus_id, transaction_ref, receipt_number,
                    amount, payment_mode, status, posted_at, is_synthetic
                ) FROM STDIN""",
                payments_rows
            )
            bulk_insert(
                cur,
                "COPY refunds (id, payment_id, assessment_id, student_id, campus_id, refund_ref, amount, reason, status) FROM STDIN",
                refunds_rows
            )
            bulk_insert(
                cur,
                """COPY academic_progress_records (
                    id, student_id, campus_id, course_id, academic_year_id,
                    total_classes_held, total_classes_attended, attendance_percentage, applicable_threshold_pct,
                    eligibility_status, cgpa, sgpa_term1, sgpa_term2, backlogs
                ) FROM STDIN""",
                progress_rows
            )
            bulk_insert(
                cur,
                """COPY hostel_allocations (
                    id, bed_id, room_id, building_id, campus_id, student_id, academic_year_id, allocation_status, allocated_by
                ) FROM STDIN""",
                hostel_alloc_rows
            )
            cur.executemany(
                "UPDATE hostel_beds SET status = 'OCCUPIED', current_student_id = %s WHERE id = %s",
                bed_occupy_updates
            )
            bulk_insert(
                cur,
                """COPY government_reimbursement_claims (
                    id, student_id, campus_id, scheme_id, academic_year_id, claim_reference,
                    sanctioned_amount, approved_amount, claimed_amount, disbursed_amount, pending_amount,
                    claim_status, submission_date, is_synthetic
                ) FROM STDIN""",
                reimbursements_rows
            )

            # 9. Link Student & Parent Demo Users (S10001..S10006 and P10001..P10006)
            for c_num, st_meta in first_student_by_campus.items():
                suid = det_uuid(f"user.S1000{c_num}")
                puid = det_uuid(f"user.P1000{c_num}")
                cur.execute(
                    """INSERT INTO users (id, display_user_id, full_name, email, phone, password_hash, role_code, status, primary_campus_id, linked_student_id)
                       VALUES (%s, %s, %s, %s, %s, %s, 'STUDENT', 'ACTIVE', %s, %s)""",
                    (suid, f"S1000{c_num}", st_meta["full_name"], f"student.c{c_num}@vidyavikas.edu.in", f"970001000{c_num}", default_pw_hash, st_meta["campus_id"], st_meta["student_id"])
                )
                cur.execute(
                    """INSERT INTO users (id, display_user_id, full_name, email, phone, password_hash, role_code, status, primary_campus_id, linked_student_id)
                       VALUES (%s, %s, %s, %s, %s, %s, 'PARENT', 'ACTIVE', %s, %s)""",
                    (puid, f"P1000{c_num}", f"Parent of {st_meta['full_name']}", f"parent.c{c_num}@vidyavikas.edu.in", f"960001000{c_num}", default_pw_hash, st_meta["campus_id"], st_meta["student_id"])
                )
                cur.execute(
                    "INSERT INTO parent_student_links (id, parent_user_id, student_id, relationship, is_verified) VALUES (%s, %s, %s, 'Father/Mother', TRUE)",
                    (det_uuid(f"psl.{c_num}"), puid, st_meta["student_id"])
                )

                # Also seed detailed dated attendance sessions & exam results for featured students
                sub_ids = subjects_by_course[st_meta["course_id"]]
                for s_idx, sub_id in enumerate(sub_ids, start=1):
                    for day_offset in range(1, 11):
                        sess_id = det_uuid(f"sess.{c_num}.{s_idx}.{day_offset}")
                        sess_dt = date(2026, 9, day_offset)
                        cur.execute(
                            "INSERT INTO attendance_sessions (id, campus_id, course_id, subject_id, academic_year_id, session_date, classes_conducted, topic) VALUES (%s, %s, %s, %s, %s, %s, 1, %s)",
                            (sess_id, st_meta["campus_id"], st_meta["course_id"], sub_id, ay_curr, sess_dt, f"Lecture Unit {day_offset}")
                        )
                        present = 1 if (day_offset != 5) else 0
                        cur.execute(
                            "INSERT INTO attendance_records (id, session_id, student_id, campus_id, subject_id, classes_attended, classes_eligible, status) VALUES (%s, %s, %s, %s, %s, %s, 1, %s)",
                            (det_uuid(f"attrec.{c_num}.{s_idx}.{day_offset}"), sess_id, st_meta["student_id"], st_meta["campus_id"], sub_id, present, "PRESENT" if present else "ABSENT")
                        )
                    for term_idx, term_name in enumerate(["TERM_1_INTERNAL", "MIDTERM_EXAM", "FINAL_SEM_1"], start=1):
                        marks = 72 + (s_idx * 4) + (term_idx * 3)
                        cur.execute(
                            "INSERT INTO examination_results (id, student_id, campus_id, subject_id, academic_year_id, exam_term, max_marks, marks_obtained, grade, passed, is_synthetic) VALUES (%s, %s, %s, %s, %s, %s, 100, %s, %s, TRUE, TRUE)",
                            (det_uuid(f"exam.{c_num}.{s_idx}.{term_idx}"), st_meta["student_id"], st_meta["campus_id"], sub_id, ay_curr, term_name, marks, "A+" if marks >= 85 else "A")
                        )

            # 10. Advance USN and Receipt sequences past initial allocations so new admissions/transfers/receipts never collide
            for c_num, c_info in campus_map.items():
                next_val = c_info["target_students"] + 50
                cur.execute(f"SELECT setval('seq_usn_c{c_num}', %s, true)", (next_val,))
            cur.execute("SELECT setval('seq_receipt_no', %s, true)", (500000 + total_students + 100,))

            # 11. Seed Historical Completed Transfers (preserving permanent student_id!)
            print("[Seed] Creating sample inter-campus transfers preserving permanent student_id...")
            for t_idx in range(1, 6):
                # Pick a student from Campus 2 transferring to Campus 1
                cur.execute(
                    "SELECT s.student_id, s.current_usn, e.id AS enr_id, e.course_id FROM students s JOIN campus_enrollments e ON e.student_id = s.student_id WHERE s.primary_campus_id = %s AND e.status = 'ACTIVE' ORDER BY s.current_usn LIMIT 1 OFFSET %s",
                    (campus_map[2]["id"], 20 + t_idx)
                )
                row = cur.fetchone()
                if row:
                    st_id = row["student_id"]
                    old_usn = row["current_usn"]
                    old_enr_id = row["enr_id"]
                    dest_course = courses_by_campus[1][0]
                    new_usn = f"1VV26{dest_course['code']}900{t_idx}"

                    # Mark old enrollment as TRANSFERRED and old identifier inactive
                    cur.execute("UPDATE campus_enrollments SET status = 'TRANSFERRED', ended_at = CURRENT_DATE WHERE id = %s", (old_enr_id,))
                    cur.execute("UPDATE student_identifiers SET is_active = FALSE, deactivated_at = NOW() WHERE student_id = %s AND id_value = %s", (st_id, old_usn))

                    # Create new enrollment & identifier at Campus 1 while keeping the exact same `student_id`
                    new_enr_id = det_uuid(f"enr.transfer.{t_idx}")
                    cur.execute(
                        "INSERT INTO campus_enrollments (id, student_id, campus_id, course_id, academic_year_id, usn, year_of_study, section, status, enrolled_at) VALUES (%s, %s, %s, %s, %s, %s, 2, 'A', 'ACTIVE', CURRENT_DATE)",
                        (new_enr_id, st_id, campus_map[1]["id"], dest_course["id"], ay_curr, new_usn)
                    )
                    cur.execute(
                        "INSERT INTO student_identifiers (id, student_id, campus_id, id_type, id_value, is_active, notes) VALUES (%s, %s, %s, 'USN', %s, TRUE, 'Assigned upon inter-campus transfer')",
                        (det_uuid(f"ident.transfer.{t_idx}"), st_id, campus_map[1]["id"], new_usn)
                    )
                    cur.execute("UPDATE students SET primary_campus_id = %s, current_usn = %s WHERE student_id = %s", (campus_map[1]["id"], new_usn, st_id))

                    treq_id = det_uuid(f"treq.{t_idx}")
                    cur.execute(
                        """INSERT INTO transfer_requests (
                            id, student_id, source_campus_id, destination_campus_id, source_course_id, destination_course_id,
                            source_usn, proposed_destination_usn, reason, status, requested_by, approved_by, completed_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'COMPLETED', %s, %s, NOW())""",
                        (treq_id, st_id, campus_map[2]["id"], campus_map[1]["id"], row["course_id"], dest_course["id"], old_usn, new_usn, "Family relocation to Bengaluru", admin_uids[2], mgmt_uid)
                    )
                    cur.execute(
                        """INSERT INTO transfer_history (
                            id, transfer_request_id, student_id, old_campus_id, new_campus_id,
                            old_usn, new_usn, old_enrollment_id, new_enrollment_id, authorized_by
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (det_uuid(f"thist.{t_idx}"), treq_id, st_id, campus_map[2]["id"], campus_map[1]["id"], old_usn, new_usn, old_enr_id, new_enr_id, mgmt_uid)
                    )

            # 12. DPDP Act 2023 Privacy Notices, Consents & Retention Policies
            notice_id = det_uuid("privacy.notice.v2026.1")
            cur.execute(
                """INSERT INTO privacy_notices (id, version, title, framework_reference, content, purposes_json, is_active)
                   VALUES (%s, 'v2026.1', 'TrustOS Institutional Student & Guardian Data Protection Notice',
                   'Digital Personal Data Protection Act, 2023 (India) & DPDP Rules, 2025 — Technical Controls',
                   'This notice sets out how VidyaVikas Educational Trust processes personal data for academic administration, fee reconciliation, hostel allocation, and statutory scholarship reporting.',
                   %s, TRUE)""",
                (notice_id, json.dumps([
                    {"code": "ACADEMIC_ADMIN", "label": "Core Academic & Examination Administration", "basis": "VOLUNTARY_PROVISION"},
                    {"code": "PARENT_PORTAL_ALERTS", "label": "Parent Fee & Attendance Alerts", "basis": "CONSENT"},
                    {"code": "SCHOLARSHIP_EXPORT", "label": "Government Scholarship & Reimbursement Claim Reporting", "basis": "CONSENT"},
                ]))
            )

            cur.executemany(
                "INSERT INTO retention_policies (id, record_category, retention_years, statutory_basis, allow_immediate_erasure, disposal_action) VALUES (%s, %s, %s, %s, %s, %s)",
                [
                    (det_uuid("ret.fin"), "FINANCIAL_LEDGER", 8, "Income Tax Act & Institutional Audit Rules", False, "ARCHIVE_AND_LOCK"),
                    (det_uuid("ret.acad"), "ACADEMIC_TRANSCRIPTS", 50, "University & Board Permanent Verification Mandate", False, "PERMANENT_ARCHIVE"),
                    (det_uuid("ret.hostel"), "HOSTEL_OCCUPANCY_LOGS", 3, "Campus Security & Warden Operational Policy", True, "ANONYMISE_AFTER_RETENTION"),
                    (det_uuid("ret.alerts"), "OPTIONAL_NOTIFICATION_PREFERENCES", 1, "DPDP Consent-based Communications", True, "DELETE_ON_WITHDRAWAL"),
                ]
            )

            for c_num, st_meta in first_student_by_campus.items():
                cur.execute(
                    """INSERT INTO consent_records (id, student_id, notice_id, purpose_code, legal_basis, consent_status, is_minor_student, guardian_verified_consent)
                       VALUES (%s, %s, %s, 'PARENT_PORTAL_ALERTS', 'CONSENT', 'GRANTED', %s, TRUE)""",
                    (det_uuid(f"consent.{c_num}"), st_meta["student_id"], notice_id, c_num in (5, 6))
                )

            # 13. Generate Imperfect Raw Source Files & Ground-Truth Duplicate Candidates
            generate_imperfect_source_files(conn, raw_dir, rng)

            print("[Seed] Complete! 6 Campuses and 14,000 Canonical Students are persisted.")
            return {"status": "seeded", "students": total_students}


def generate_imperfect_source_files(conn, raw_dir: Path, rng: random.Random):
    """
    Creates the 7 deliberately imperfect raw files in `data/raw_sources/` plus `ground_truth_duplicates.csv`
    and seeds `duplicate_match_candidates` with ground-truth labels so the Duplicate Review Queue and
    Precision/Recall/F1 evaluator work out of the box.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT s.student_id, s.full_name, s.date_of_birth, s.gender, s.phone, s.current_usn,
                   s.category, c.campus_number, c.code AS campus_code, c.name AS campus_name
            FROM students s
            JOIN campuses c ON c.id = s.primary_campus_id
            ORDER BY s.current_usn
            LIMIT 120
        """)
        sample_students = cur.fetchall()

        # 1. campus_1_admissions.csv (includes messy column names, date format variations, whitespace, and 15 controlled duplicate/homonym rows)
        c1_path = raw_dir / "campus_1_admissions.csv"
        gt_rows = []
        c1_rows = []

        for idx, st in enumerate(sample_students[:40]):
            dob_str = st["date_of_birth"].strftime("%d/%m/%Y") if idx % 2 == 0 else st["date_of_birth"].strftime("%Y-%m-%d")
            c1_rows.append({
                "Legacy_Row_ID": f"SRC-C1-{idx+1:03d}",
                "Student Name ": f"  {st['full_name']} " if idx % 3 == 0 else st["full_name"],
                "DOB_Text": dob_str,
                "Contact_Mobile": st["phone"],
                "Roll_Or_USN": st["current_usn"],
                "Campus_Label": "VVE Bengaluru" if idx % 2 == 0 else "Campus-1 (BLR)",
                "Category_Code": st["category"],
            })

        # Add 12 True Duplicates (spelling variations, missing USN, formatting differences)
        true_dups = sample_students[:12]
        for idx, st in enumerate(true_dups):
            messy_name = st["full_name"].replace("a", "aa", 1) if idx % 2 == 0 else st["full_name"].upper()
            src_key = f"DUP-TRUE-{idx+1:03d}"
            c1_rows.append({
                "Legacy_Row_ID": src_key,
                "Student Name ": messy_name,
                "DOB_Text": st["date_of_birth"].strftime("%d-%m-%Y"),
                "Contact_Mobile": st["phone"],
                "Roll_Or_USN": st["current_usn"] if idx < 5 else "",
                "Campus_Label": "VidyaVikas Engg BLR",
                "Category_Code": st["category"],
            })
            gt_rows.append({
                "source_record_key": src_key,
                "source_student_name": messy_name,
                "source_dob": str(st["date_of_birth"]),
                "source_phone": st["phone"],
                "source_usn": st["current_usn"] if idx < 5 else "",
                "candidate_student_id": str(st["student_id"]),
                "candidate_student_name": st["full_name"],
                "candidate_usn": st["current_usn"],
                "ground_truth_is_duplicate": True,
                "scenario": "EXACT_USN_MATCH" if idx < 5 else "NAME_SPELLING_AND_DOB_PHONE_MATCH"
            })

        # Add 8 Distinct Students who happen to share similar/identical names (Homonyms - MUST NOT be auto-merged!)
        homonyms = sample_students[12:20]
        for idx, st in enumerate(homonyms):
            src_key = f"DUP-HOMONYM-{idx+1:03d}"
            diff_dob = date(2004, 3, (idx + 10))
            diff_phone = f"911119990{idx}"
            c1_rows.append({
                "Legacy_Row_ID": src_key,
                "Student Name ": st["full_name"],  # Same name!
                "DOB_Text": diff_dob.strftime("%Y-%m-%d"),  # Different DOB!
                "Contact_Mobile": diff_phone,  # Different phone!
                "Roll_Or_USN": "",
                "Campus_Label": "Campus-2 Mysuru",
                "Category_Code": "GENERAL",
            })
            gt_rows.append({
                "source_record_key": src_key,
                "source_student_name": st["full_name"],
                "source_dob": str(diff_dob),
                "source_phone": diff_phone,
                "source_usn": "",
                "candidate_student_id": str(st["student_id"]),
                "candidate_student_name": st["full_name"],
                "candidate_usn": st["current_usn"],
                "ground_truth_is_duplicate": False,
                "scenario": "HOMONYM_DIFFERENT_STUDENT"
            })

        pd.DataFrame(c1_rows).to_csv(c1_path, index=False)
        pd.DataFrame(gt_rows).to_csv(raw_dir / "ground_truth_duplicates.csv", index=False)

        # 2. campus_2_students.csv
        pd.DataFrame([
            {
                "USN_No": s["current_usn"],
                "Candidate_Full_Name": s["full_name"],
                "BirthDate": s["date_of_birth"].strftime("%Y/%m/%d"),
                "Mobile": s["phone"] if i % 5 != 0 else "",  # Missing optional phone
                "Institution": "VVE Mysuru"
            }
            for i, s in enumerate(sample_students[20:50])
        ]).to_csv(raw_dir / "campus_2_students.csv", index=False)

        # 3. campus_3_fee_records.csv
        pd.DataFrame([
            {
                "Student_USN": s["current_usn"],
                "Receipt_Ref": f"EXT-FEE-{i+100}",
                "Paid_Rs": 25000 if i % 2 == 0 else 18000,
                "Payment_Date": "15-10-2026" if i % 3 != 0 else "2026/10/15",
                "Mode": "UPI"
            }
            for i, s in enumerate(sample_students[:25])
        ]).to_csv(raw_dir / "campus_3_fee_records.csv", index=False)

        # 4. campus_4_attendance.xlsx (Excel file)
        att_df = pd.DataFrame([
            {
                "Reg_Number": s["current_usn"],
                "Student_Name": s["full_name"],
                "Classes_Held": 60,
                "Classes_Attended": 42 if i % 4 == 0 else 52,
                "Session_Month": "October-2026"
            }
            for i, s in enumerate(sample_students[:30])
        ])
        att_df.to_excel(raw_dir / "campus_4_attendance.xlsx", index=False)

        # 5. campus_5_hostel_inventory.csv
        pd.DataFrame([
            {"Block_Code": "HB-5A", "Room_No": f"10{i}", "Bed_ID": f"10{i}-A", "Current_Status": "AVAILABLE"}
            for i in range(1, 10)
        ]).to_csv(raw_dir / "campus_5_hostel_inventory.csv", index=False)

        # 6. campus_6_scholarships.csv
        pd.DataFrame([
            {
                "USN": s["current_usn"],
                "Scheme": "SSP_POST_MATRIC",
                "Claimed_INR": 38000,
                "Status_Text": "SUBMITTED_TO_PORTAL"
            }
            for s in sample_students[:20]
        ]).to_csv(raw_dir / "campus_6_scholarships.csv", index=False)

        # 7. campus_transfer_records.csv
        pd.DataFrame([
            {
                "Old_USN": s["current_usn"],
                "Student_Name": s["full_name"],
                "From_Campus": "VVE-MYS",
                "To_Campus": "VVE-BLR",
                "Transfer_Reason": "Inter-campus merit migration"
            }
            for s in sample_students[50:55]
        ]).to_csv(raw_dir / "campus_transfer_records.csv", index=False)

        # Populate `duplicate_match_candidates` table from ground-truth evaluation set if empty
        cur.execute("SELECT COUNT(*) AS cnt FROM duplicate_match_candidates")
        if cur.fetchone()["cnt"] == 0:
            for idx, item in enumerate(gt_rows):
                if item["ground_truth_is_duplicate"]:
                    if item["source_usn"]:
                        conf = 99.0
                        matching = ["current_usn", "normalized_name", "date_of_birth", "phone"]
                        conflicting = []
                        action = "EXACT_LINK"
                        rev_status = "AUTO_LINKED"
                    else:
                        conf = 88.5
                        matching = ["fuzzy_name_similarity", "date_of_birth", "phone"]
                        conflicting = ["missing_usn_in_source"]
                        action = "HUMAN_REVIEW"
                        rev_status = "PENDING_REVIEW"
                else:
                    # Homonym: same name, different DOB and phone!
                    conf = 42.0
                    matching = ["normalized_name"]
                    conflicting = ["date_of_birth", "phone"]
                    action = "KEEP_SEPARATE"
                    rev_status = "PENDING_REVIEW"

                cur.execute(
                    """INSERT INTO duplicate_match_candidates (
                        id, source_file, source_record_key, source_student_name, source_dob, source_phone, source_usn,
                        candidate_student_id, candidate_student_name, candidate_usn, match_confidence,
                        matching_attributes, conflicting_attributes, proposed_action, review_status, ground_truth_is_duplicate
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        det_uuid(f"dupcand.{idx}"), "campus_1_admissions.csv", item["source_record_key"],
                        item["source_student_name"], item["source_dob"], item["source_phone"], item["source_usn"],
                        item["candidate_student_id"], item["candidate_student_name"], item["candidate_usn"],
                        conf, json.dumps(matching), json.dumps(conflicting), action, rev_status, item["ground_truth_is_duplicate"]
                    )
                )


if __name__ == "__main__":
    seed_all(14000)
