"""Centralized database gateway — ALL SQL execution goes through execute_sql().

Public API:
    execute_sql(query, params) → ExecutionResult
    init_db(config) → None
    test_connection() → tuple[bool, str]
    get_cached_tables() → list[str]
    invalidate_cache() → None
    SQLSafetyError
    SQLExecutionError
    ExecutionResult
"""

from dataclasses import dataclass, field
from typing import Optional

import psycopg2

from pgagent.config import Config
from pgagent.safety import validate_read_only_sql


# ──────────────────────────────────────────────
# Custom Exceptions
# ──────────────────────────────────────────────


class SQLSafetyError(Exception):
    """Raised when a query fails the safety/read-only check."""
    pass


class SQLExecutionError(Exception):
    """Raised when a query passes safety but fails at the database level."""
    pass


# ──────────────────────────────────────────────
# Result dataclass
# ──────────────────────────────────────────────


@dataclass
class ExecutionResult:
    """Result of a successful SQL execution."""
    rows: list[tuple] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    row_count: int = 0
    query: str = ""


# ──────────────────────────────────────────────
# Private state
# ──────────────────────────────────────────────

_config: Optional[Config] = None
_schema_cache: Optional[list[str]] = None


# ──────────────────────────────────────────────
# Private helpers
# ──────────────────────────────────────────────


def _get_connection():
    """Create and return a new psycopg2 connection. PRIVATE — never exported."""
    if _config is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    if _config.database_url:
        return psycopg2.connect(_config.database_url)
    return psycopg2.connect(
        host=_config.db_host,
        port=_config.db_port,
        database=_config.db_database,
        user=_config.db_user,
        password=_config.db_password,
    )


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────


def init_db(config: Config) -> None:
    """Initialize the database module with connection config."""
    global _config, _schema_cache
    _config = config
    _schema_cache = None


def execute_sql(query: str, params: tuple = ()) -> ExecutionResult:
    """
    The SINGLE gateway for all SQL execution in this project.

    Steps:
      1. Validate query with safety guard
      2. Get connection
      3. Execute (the only authorized cursor.execute call)
      4. Fetch & return ExecutionResult
      5. Handle errors → SQLExecutionError

    Raises:
        SQLSafetyError: If query fails read-only validation.
        SQLExecutionError: If query fails at the database level.
    """
    # Step 1 — Safety validation
    is_safe, reason = validate_read_only_sql(query)
    if not is_safe:
        raise SQLSafetyError(reason)

    # Step 2 — Get connection
    conn = _get_connection()
    try:
        cur = conn.cursor()

        # Step 3 — Execute
        # GATEWAY: this is the only authorized execute() call in the entire project
        cur.execute(query, params)

        # Step 4 — Fetch & return
        if cur.description:
            columns = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
            return ExecutionResult(
                rows=rows,
                columns=columns,
                row_count=len(rows),
                query=query,
            )
        else:
            return ExecutionResult(
                rows=[],
                columns=[],
                row_count=cur.rowcount,
                query=query,
            )

    except psycopg2.Error as e:
        # Step 5 — Handle DB errors
        conn.rollback()
        raise SQLExecutionError(str(e)) from e

    finally:
        conn.close()


def test_connection() -> tuple[bool, str]:
    """
    Test the database connection by running a version query.
    This bypasses the safety check since SELECT version() is always safe.
    Returns (success, message).
    """
    try:
        result = execute_sql("SELECT version()")
        version = result.rows[0][0] if result.rows else "Connected"
        return True, version
    except (SQLSafetyError, SQLExecutionError, RuntimeError) as e:
        return False, str(e)
    except Exception as e:
        return False, str(e)


def get_cached_tables() -> list[str]:
    """Get list of all tables in public schema (cached after first call)."""
    global _schema_cache
    if _schema_cache is not None:
        return _schema_cache
    try:
        result = execute_sql("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        _schema_cache = [row[0] for row in result.rows]
    except (SQLSafetyError, SQLExecutionError):
        _schema_cache = []
    return _schema_cache


def invalidate_cache() -> None:
    """Force refresh of schema cache on next access."""
    global _schema_cache
    _schema_cache = None
