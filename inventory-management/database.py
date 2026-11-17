import sqlite3
from contextlib import contextmanager
from typing import Any, Iterable, Optional
from config import Config

try:
    from flask import current_app, g
except ImportError:  # Allows running database.py, seed.py, and unittest without Flask installed
    current_app = None  # type: ignore
    g = None  # type: ignore


def _has_flask_app_context() -> bool:
    """Return True if a Flask application context is currently active."""
    try:
        return bool(current_app and current_app.config)
    except RuntimeError:
        return False


def create_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Create a new SQLite connection with Row factory and Foreign Keys enabled."""
    if db_path:
        resolved_path = db_path
    elif _has_flask_app_context():
        resolved_path = current_app.config["DATABASE_PATH"]  # type: ignore
    else:
        resolved_path = Config.DATABASE_PATH

    conn = sqlite3.connect(resolved_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def get_db() -> sqlite3.Connection:
    """Return the request-scoped SQLite connection when inside a Flask context."""
    if _has_flask_app_context() and g is not None:
        if "db" not in g:
            g.db = create_connection(current_app.config["DATABASE_PATH"])  # type: ignore
        return g.db
    return create_connection(Config.DATABASE_PATH)


def close_db(exception: Optional[BaseException] = None) -> None:
    """Close the request-scoped SQLite connection at the end of a request."""
    if _has_flask_app_context() and g is not None:
        db = g.pop("db", None)
        if db is not None:
            db.close()


@contextmanager
def transaction(conn: Optional[sqlite3.Connection] = None):
    """
    Execute a block of SQL operations atomically inside a transaction.
    Automatically commits on success or rolls back on any exception.
    """
    owns_connection = False
    if conn is None:
        if _has_flask_app_context():
            conn = get_db()
        else:
            conn = create_connection()
            owns_connection = True

    try:
        if not conn.in_transaction:
            conn.execute("BEGIN")
        yield conn
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        if owns_connection:
            conn.close()


def query_all(
    sql: str,
    params: Iterable[Any] = (),
    conn: Optional[sqlite3.Connection] = None,
) -> list[sqlite3.Row]:
    """Execute a parameterized SELECT query and return all matching rows."""
    active_conn = conn or get_db()
    cursor = active_conn.execute(sql, tuple(params))
    return cursor.fetchall()


def query_one(
    sql: str,
    params: Iterable[Any] = (),
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[sqlite3.Row]:
    """Execute a parameterized SELECT query and return a single row or None."""
    active_conn = conn or get_db()
    cursor = active_conn.execute(sql, tuple(params))
    return cursor.fetchone()


def init_db(
    db_path: Optional[str] = None, schema_path: Optional[str] = None
) -> None:
    """Initialize the SQLite database tables and constraints from schema.sql."""
    target_db = db_path or Config.DATABASE_PATH
    target_schema = schema_path or Config.SCHEMA_PATH

    with open(target_schema, "r", encoding="utf-8") as schema_file:
        schema_sql = schema_file.read()

    conn = create_connection(target_db)
    try:
        conn.executescript(schema_sql)
        conn.commit()
    finally:
        conn.close()
