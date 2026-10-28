import os
from contextlib import contextmanager
from typing import Optional, Dict, Any
import psycopg
from psycopg.rows import dict_row

PG_HOST = os.getenv("TRUSTOS_PG_HOST", "127.0.0.1")
PG_PORT = int(os.getenv("TRUSTOS_PG_PORT", "5433"))
PG_DB = os.getenv("TRUSTOS_PG_DB", "trustos_db")

# Admin / Migration connection (Database Owner - used ONLY for schema setup, seeding, and login lookup)
OWNER_DSN = os.getenv(
    "TRUSTOS_OWNER_DSN",
    f"host={PG_HOST} port={PG_PORT} dbname={PG_DB} user=postgres connect_timeout=5"
)

# Restricted Application Role (NOSUPERUSER, NOBYPASSRLS - used for all user-scoped operations)
APP_DSN = os.getenv(
    "TRUSTOS_APP_DSN",
    f"host={PG_HOST} port={PG_PORT} dbname={PG_DB} user=trustos_app password=trustos_app_local_dev_pw connect_timeout=5"
)


@contextmanager
def get_owner_conn():
    """Connection using owner privileges strictly for migrations, seed scripts, and initial auth lookup."""
    conn = psycopg.connect(OWNER_DSN, row_factory=dict_row)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def get_rls_conn(user_context: Optional[Dict[str, Any]] = None):
    """
    Connection using restricted application role `trustos_app` (NOBYPASSRLS).
    Sets transaction-local identity variables (`SET LOCAL app.current_*`) so that
    PostgreSQL Row-Level Security (RLS) policies strictly enforce campus and role isolation
    and connection pooling can never leak context across transactions.
    """
    conn = psycopg.connect(APP_DSN, row_factory=dict_row)
    try:
        with conn.cursor() as cur:
            role = (user_context or {}).get("role_code", "ANONYMOUS")
            user_id = str((user_context or {}).get("id") or "")
            campus_id = str((user_context or {}).get("primary_campus_id") or "")
            student_id = str((user_context or {}).get("linked_student_id") or "")

            cur.execute("SELECT set_config('app.current_role', %s, true)", (role,))
            cur.execute("SELECT set_config('app.current_user_id', %s, true)", (user_id,))
            cur.execute("SELECT set_config('app.current_campus_id', %s, true)", (campus_id,))
            cur.execute("SELECT set_config('app.current_student_id', %s, true)", (student_id,))
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
