"""
Authentication, Role-Based Access Control (RBAC), Rate Limiting & Audit Logging.
Never trusts client-supplied roles or campus IDs; always derives identity from signed JWT and server DB state.
"""

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
import jwt
import bcrypt
from fastapi import Depends, HTTPException, Header, Request, status
from app.db import get_owner_conn

JWT_SECRET = os.getenv("TRUSTOS_JWT_SECRET", "trustos-local-dev-jwt-secret-key-change-in-prod-2026")
JWT_ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 12

# In-memory rate-limiting and revoked token blacklist
LOGIN_RATE_LIMIT: Dict[str, List[float]] = {}
REVOKED_TOKENS: set = set()


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def check_rate_limit(key: str, max_attempts: int = 12, window_seconds: int = 60):
    now = time.time()
    attempts = [t for t in LOGIN_RATE_LIMIT.get(key, []) if now - t < window_seconds]
    if len(attempts) >= max_attempts:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many authentication attempts. Please wait before retrying."
        )
    attempts.append(now)
    LOGIN_RATE_LIMIT[key] = attempts


def create_access_token(user_row: Dict[str, Any]) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_row["id"]),
        "display_user_id": user_row["display_user_id"],
        "role_code": user_row["role_code"],
        "primary_campus_id": str(user_row["primary_campus_id"]) if user_row.get("primary_campus_id") else None,
        "linked_student_id": str(user_row["linked_student_id"]) if user_row.get("linked_student_id") else None,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=TOKEN_EXPIRE_HOURS)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def record_audit_log(
    conn,
    actor_user_id: Optional[str],
    actor_role: Optional[str],
    campus_id: Optional[str],
    action: str,
    entity_type: str,
    entity_id: Optional[str],
    summary: str,
    metadata: Optional[Dict[str, Any]] = None,
    ip_address: str = "127.0.0.1",
):
    import json
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO audit_logs (
                actor_user_id, actor_role, campus_id, action, entity_type, entity_id, summary, metadata_json, ip_address
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                actor_user_id, actor_role, campus_id, action, entity_type,
                str(entity_id) if entity_id else None, summary,
                json.dumps(metadata or {}), ip_address
            )
        )


def get_current_user(
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """
    Validates Bearer token and refreshes authoritative role, status, campus, and linked_student_id
    from the database so suspended/pending accounts or client-supplied headers can NEVER bypass security.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid authentication token")

    token = authorization.split(" ", 1)[1].strip()
    if token in REVOKED_TOKENS:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session has been logged out")

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired. Please sign in again")
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication credentials")

    user_id = payload.get("sub")
    with get_owner_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT u.id, u.display_user_id, u.full_name, u.email, u.phone,
                          u.role_code, u.status, u.primary_campus_id, u.linked_student_id,
                          c.name AS campus_name, c.code AS campus_code, c.campus_number
                   FROM users u
                   LEFT JOIN campuses c ON c.id = u.primary_campus_id
                   WHERE u.id = %s""",
                (user_id,)
            )
            user = cur.fetchone()

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication credentials")

    if user["status"] != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Account status is {user['status']}. Access to protected operations is denied."
        )

    user["token"] = token
    return user


def require_roles(*allowed_roles: str):
    def dependency(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
        if user["role_code"] not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user['role_code']}' is not authorized for this operation. Allowed: {', '.join(allowed_roles)}"
            )
        return user
    return dependency
