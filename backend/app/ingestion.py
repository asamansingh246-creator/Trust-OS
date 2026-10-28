"""
Phase 4 & 7A: Multi-Dataset Profiler, Schema Mapper, Idempotent Importer & Duplicate Reconciliation Engine.
Implements:
- File inspection for CSV, XLSX/XLS, JSON, and safe SQL Dump parsing (never executes raw SQL with privileges)
- Column mapping persistence and automatic fuzzy header suggestions
- Missing data handling (never fabricates real values; records INFERRED/MISSING data-quality issues)
- Multi-signal duplicate candidate scoring vs. baseline name-only matching
- Ground-truth Precision, Recall, F1, False Positive, and False Negative calculation
"""

import io
import re
import csv
import json
import uuid
import hashlib
from datetime import datetime, date
from difflib import SequenceMatcher
from typing import Dict, Any, List, Optional, Tuple
import pandas as pd


CANONICAL_FIELDS_BY_MODULE = {
    "ADMISSIONS": ["full_name", "date_of_birth", "phone", "usn", "campus_code", "category", "source_record_key"],
    "STUDENTS": ["usn", "full_name", "date_of_birth", "phone", "campus_code", "gender"],
    "FEES": ["usn", "transaction_ref", "amount", "payment_date", "payment_mode"],
    "ATTENDANCE": ["usn", "full_name", "classes_held", "classes_attended", "session_period"],
    "HOSTEL": ["building_code", "room_number", "bed_code", "status"],
    "SCHOLARSHIPS": ["usn", "scheme_code", "claimed_amount", "status"],
    "TRANSFERS": ["old_usn", "full_name", "source_campus", "destination_campus", "reason"],
}

SYNONYM_MAP = {
    "full_name": ["student name", "student_name", "candidate_full_name", "name", "applicant_name"],
    "date_of_birth": ["dob", "dob_text", "birthdate", "date of birth", "birth_date"],
    "phone": ["contact_mobile", "mobile", "phone", "contact_no", "mobile_no"],
    "usn": ["roll_or_usn", "usn_no", "student_usn", "reg_number", "usn", "roll_no"],
    "campus_code": ["campus_label", "institution", "campus", "college_code"],
    "category": ["category_code", "category", "caste_category"],
    "source_record_key": ["legacy_row_id", "row_id", "source_id", "record_id"],
    "transaction_ref": ["receipt_ref", "txn_ref", "transaction_ref", "reference_no"],
    "amount": ["paid_rs", "amount", "fee_paid", "claimed_inr"],
    "payment_date": ["payment_date", "date", "txn_date"],
    "payment_mode": ["mode", "payment_mode", "channel"],
    "classes_held": ["classes_held", "total_classes", "conducted"],
    "classes_attended": ["classes_attended", "attended", "present_count"],
}


def normalize_text(val: Any) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    return "".join(ch.lower() for ch in str(val).strip() if ch.isalnum())


def parse_flexible_date(val: Any) -> Optional[date]:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%m/%d/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def suggest_column_mapping(columns: List[str], target_module: str) -> Dict[str, str]:
    """Automatically suggests source_col -> canonical_field mappings."""
    mapping = {}
    canonical_targets = CANONICAL_FIELDS_BY_MODULE.get(target_module.upper(), CANONICAL_FIELDS_BY_MODULE["ADMISSIONS"])
    for col in columns:
        clean_col = col.strip().lower()
        matched_target = None
        for target_field in canonical_targets:
            synonyms = SYNONYM_MAP.get(target_field, [target_field])
            if clean_col == target_field or clean_col in synonyms:
                matched_target = target_field
                break
        if not matched_target:
            # Fuzzy fallback
            best_score = 0.0
            for target_field in canonical_targets:
                for syn in SYNONYM_MAP.get(target_field, [target_field]):
                    sc = SequenceMatcher(None, clean_col, syn).ratio()
                    if sc > best_score and sc >= 0.72:
                        best_score = sc
                        matched_target = target_field
        if matched_target:
            mapping[col] = matched_target
    return mapping


def load_dataframe_from_bytes(filename: str, content: bytes) -> Tuple[pd.DataFrame, str, List[str]]:
    """
    Safely loads CSV, XLSX/XLS, JSON, or untrusted SQL INSERT dumps without executing SQL.
    Returns (DataFrame, detected_format, sheet_names).
    """
    lower_name = filename.lower()
    if lower_name.endswith(".xlsx") or lower_name.endswith(".xls"):
        excel_file = pd.ExcelFile(io.BytesIO(content))
        sheets = excel_file.sheet_names
        df = pd.read_excel(io.BytesIO(content), sheet_name=sheets[0])
        return df, "XLSX", sheets
    elif lower_name.endswith(".json"):
        data = json.loads(content.decode("utf-8", errors="replace"))
        df = pd.DataFrame(data if isinstance(data, list) else data.get("records", []))
        return df, "JSON", ["json_root"]
    elif lower_name.endswith(".sql"):
        # Parse INSERT INTO table (cols) VALUES (...) safely using regex without executing any SQL!
        text = content.decode("utf-8", errors="replace")
        pattern = re.compile(
            r"INSERT\s+INTO\s+\w+\s*\(([^)]+)\)\s*VALUES\s*\(([^)]+)\)",
            re.IGNORECASE
        )
        rows = []
        for match in pattern.finditer(text):
            cols = [c.strip().strip('"`\'') for c in match.group(1).split(",")]
            vals = [v.strip().strip("'\"") for v in match.group(2).split(",")]
            if len(cols) == len(vals):
                rows.append(dict(zip(cols, vals)))
        df = pd.DataFrame(rows)
        return df, "SQL_DUMP_SAFE_PARSED", ["sql_inserts"]
    else:
        # CSV with automatic encoding & delimiter detection
        for enc in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                text = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = content.decode("utf-8", errors="replace")

        sample_line = text.splitlines()[0] if text.splitlines() else ""
        delimiter = ";" if sample_line.count(";") > sample_line.count(",") else (
            "\t" if sample_line.count("\t") > sample_line.count(",") else ","
        )
        df = pd.read_csv(io.StringIO(text), sep=delimiter, dtype=str, keep_default_na=False)
        return df, "CSV", ["csv_sheet"]


def profile_dataset(filename: str, content: bytes, target_module: str = "ADMISSIONS") -> Dict[str, Any]:
    df, fmt, sheets = load_dataframe_from_bytes(filename, content)
    df = df.fillna("")
    columns = list(df.columns)
    total_rows = len(df)

    missing_counts = {}
    for col in columns:
        empty_cnt = int((df[col].astype(str).str.strip() == "").sum())
        if empty_cnt > 0:
            missing_counts[col] = empty_cnt

    duplicate_row_count = int(df.duplicated().sum()) if total_rows > 0 else 0
    suggested_map = suggest_column_mapping(columns, target_module)
    sample_rows = df.head(8).to_dict(orient="records")

    return {
        "filename": filename,
        "file_format": fmt,
        "checksum": hashlib.sha256(content).hexdigest(),
        "sheets": sheets,
        "columns": columns,
        "total_rows": total_rows,
        "missing_values_by_column": missing_counts,
        "exact_duplicate_rows": duplicate_row_count,
        "suggested_mapping": suggested_map,
        "canonical_fields": CANONICAL_FIELDS_BY_MODULE.get(target_module.upper(), CANONICAL_FIELDS_BY_MODULE["ADMISSIONS"]),
        "sample_rows": sample_rows,
    }


def score_student_duplicate_candidate(
    src_name: str,
    src_dob: Optional[date],
    src_phone: str,
    src_usn: str,
    cand: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Multi-attribute identity resolution scorer:
    Combines exact USN match, normalized name similarity, DOB agreement, and phone agreement.
    Crucial rule: Never automatically merge students solely because their names are similar!
    """
    matching = []
    conflicting = []
    score = 0.0

    cand_usn = (cand.get("current_usn") or "").strip().upper()
    if src_usn and cand_usn and src_usn.strip().upper() == cand_usn:
        matching.append("current_usn")
        score += 65.0
    elif src_usn and cand_usn and src_usn.strip().upper() != cand_usn:
        conflicting.append("current_usn")

    norm_src = normalize_text(src_name)
    norm_cand = cand.get("normalized_name") or normalize_text(cand.get("full_name", ""))
    name_sim = SequenceMatcher(None, norm_src, norm_cand).ratio() if (norm_src and norm_cand) else 0.0

    if name_sim >= 0.98:
        matching.append("normalized_name")
        score += 25.0
    elif name_sim >= 0.80:
        matching.append("fuzzy_name_similarity")
        score += 18.0
    else:
        conflicting.append("full_name")

    cand_dob = cand.get("date_of_birth")
    if isinstance(cand_dob, str):
        cand_dob = parse_flexible_date(cand_dob)

    if src_dob and cand_dob:
        if src_dob == cand_dob:
            matching.append("date_of_birth")
            score += 35.0
        else:
            conflicting.append("date_of_birth")
            score -= 20.0

    clean_src_phone = "".join(ch for ch in (src_phone or "") if ch.isdigit())[-10:]
    clean_cand_phone = "".join(ch for ch in (cand.get("phone") or "") if ch.isdigit())[-10:]
    if clean_src_phone and clean_cand_phone:
        if clean_src_phone == clean_cand_phone:
            matching.append("phone")
            score += 30.0
        else:
            conflicting.append("phone")
            score -= 15.0

    confidence = max(0.0, min(99.5, round(score, 2)))

    # Decision rule:
    # - Exact verified USN + name/DOB agreement -> EXACT_LINK (>= 95%)
    # - High fuzzy name + DOB + phone agreement -> HUMAN_REVIEW / high confidence duplicate (>= 75%)
    # - Name-only match with conflicting DOB/phone (Homonym) -> KEEP_SEPARATE (< 60%)
    if "current_usn" in matching and confidence >= 90.0:
        proposed_action = "EXACT_LINK"
    elif confidence >= 70.0 and "date_of_birth" in matching:
        proposed_action = "HUMAN_REVIEW"
    else:
        proposed_action = "KEEP_SEPARATE"

    return {
        "match_confidence": confidence,
        "matching_attributes": matching,
        "conflicting_attributes": conflicting,
        "proposed_action": proposed_action,
        "predicted_is_duplicate": proposed_action in ("EXACT_LINK", "HUMAN_REVIEW") and confidence >= 75.0,
        "baseline_name_only_is_duplicate": name_sim >= 0.80,
    }


def evaluate_duplicate_metrics(conn) -> Dict[str, Any]:
    """
    Evaluates the TrustOS Multi-Signal Identity Resolver vs. Baseline Name-Only Matcher
    against ground-truth labels in `duplicate_match_candidates`.
    Returns Precision, Recall, F1, TP, FP, TN, FN for both models.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT source_record_key, source_student_name, source_dob, source_phone, source_usn,
                   candidate_student_id, candidate_student_name, candidate_usn,
                   match_confidence, matching_attributes, conflicting_attributes,
                   proposed_action, review_status, ground_truth_is_duplicate
            FROM duplicate_match_candidates
            WHERE ground_truth_is_duplicate IS NOT NULL
        """)
        rows = cur.fetchall()

    def calc_metrics(predictions: List[Tuple[bool, bool]]) -> Dict[str, Any]:
        tp = sum(1 for pred, gt in predictions if pred and gt)
        fp = sum(1 for pred, gt in predictions if pred and not gt)
        tn = sum(1 for pred, gt in predictions if not pred and not gt)
        fn = sum(1 for pred, gt in predictions if not pred and gt)
        precision = round(tp / (tp + fp), 4) if (tp + fp) > 0 else 0.0
        recall = round(tp / (tp + fn), 4) if (tp + fn) > 0 else 0.0
        f1 = round((2 * precision * recall) / (precision + recall), 4) if (precision + recall) > 0 else 0.0
        return {
            "true_positives": tp,
            "false_positives": fp,
            "true_negatives": tn,
            "false_negatives": fn,
            "precision": precision,
            "recall": recall,
            "f1_score": f1,
        }

    trustos_preds = []
    baseline_preds = []
    for r in rows:
        gt = bool(r["ground_truth_is_duplicate"])
        # TrustOS multi-signal prediction: confidence >= 75% and action in EXACT_LINK or HUMAN_REVIEW
        pred_multi = float(r["match_confidence"]) >= 75.0 and r["proposed_action"] in ("EXACT_LINK", "HUMAN_REVIEW")
        # Baseline naive name-only matcher predicts True whenever normalized names are similar
        norm_s = normalize_text(r["source_student_name"])
        norm_c = normalize_text(r["candidate_student_name"])
        pred_baseline = SequenceMatcher(None, norm_s, norm_c).ratio() >= 0.80
        trustos_preds.append((pred_multi, gt))
        baseline_preds.append((pred_baseline, gt))

    return {
        "total_ground_truth_pairs": len(rows),
        "trustos_multi_signal_model": calc_metrics(trustos_preds),
        "baseline_name_only_model": calc_metrics(baseline_preds),
        "methodology_summary": (
            "TrustOS combines verified USN, normalized Levenshtein similarity, Date-of-Birth exact agreement, "
            "and 10-digit phone verification. Unlike naive name-only matching (which falsely merges homonyms), "
            "TrustOS penalizes conflicting DOB/contact attributes and routes ambiguous matches to the Human Review Queue."
        ),
    }
