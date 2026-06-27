"""Database tools for the LangChain agent."""

import json
from typing import Optional

from langchain_core.tools import tool

from pgagent.db import get_db
from pgagent.safety import validate_read_only_sql


@tool
def list_tables() -> str:
    """List all tables in the public schema of the connected PostgreSQL database."""
    db = get_db()
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        tables = [row[0] for row in cur.fetchall()]
        if not tables:
            return "No tables found in the public schema."
        return f"Tables ({len(tables)}): {', '.join(tables)}"
    finally:
        conn.close()


@tool
def get_table_schema(table_name: str) -> str:
    """Get the schema (columns, types, nullability, defaults) of a specific table."""
    db = get_db()
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position
        """, (table_name,))
        columns = cur.fetchall()
        if not columns:
            return f"Table '{table_name}' not found or has no columns."
        lines = [f"Schema for '{table_name}' ({len(columns)} columns):"]
        for col in columns:
            nullable = "NULL" if col[2] == "YES" else "NOT NULL"
            default = f" DEFAULT {col[3]}" if col[3] else ""
            lines.append(f"  {col[0]} {col[1]} {nullable}{default}")
        return "\n".join(lines)
    finally:
        conn.close()


@tool
def execute_sql(query: str) -> str:
    """Execute a read-only SQL query (SELECT/WITH/SHOW/EXPLAIN) and return results."""
    is_safe, reason = validate_read_only_sql(query)
    if not is_safe:
        return f"⚠ Safety Guard: Blocked. {reason}"

    db = get_db()
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        cur.execute(query)
        if cur.description:
            columns = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
            if not rows:
                return "Query returned no results."
            result = " | ".join(columns) + "\n"
            result += "-" * len(result) + "\n"
            result += "\n".join([" | ".join(str(v) for v in row) for row in rows[:50]])
            if len(rows) > 50:
                result += f"\n... (showing 50 of {len(rows)} total rows)"
            else:
                result += f"\n({len(rows)} row{'s' if len(rows) != 1 else ''})"
            return result
        else:
            return f"Query executed. Rows affected: {cur.rowcount}"
    except Exception as e:
        return f"SQL Error: {e}"
    finally:
        conn.close()


@tool
def get_table_sample(table_name: str, limit: int = 5) -> str:
    """Get a sample of rows from a table (SELECT * LIMIT n). Useful for previewing data."""
    # Simple identifier validation
    if not table_name.replace("_", "").replace(".", "").isalnum():
        return "Invalid table name."
    if limit < 1 or limit > 20:
        limit = 5

    db = get_db()
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f'SELECT * FROM "{table_name}" LIMIT %s', (limit,))
        if cur.description:
            columns = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
            if not rows:
                return f"Table '{table_name}' is empty."
            result = " | ".join(columns) + "\n"
            result += "-" * len(result) + "\n"
            result += "\n".join([" | ".join(str(v) for v in row) for row in rows])
            result += f"\n(sample of {len(rows)} row{'s' if len(rows) != 1 else ''})"
            return result
        return "No data returned."
    except Exception as e:
        return f"Error: {e}"
    finally:
        conn.close()


@tool
def search_schema(keyword: str) -> str:
    """Search all table and column names matching a keyword (case-insensitive). Useful for finding which table has a specific column."""
    db = get_db()
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND (lower(column_name) LIKE lower(%s) OR lower(table_name) LIKE lower(%s))
            ORDER BY table_name, ordinal_position
        """, (f"%{keyword}%", f"%{keyword}%"))
        rows = cur.fetchall()
        if not rows:
            return f"No tables or columns matching '{keyword}' found."
        lines = [f"Matches for '{keyword}':"]
        for row in rows:
            lines.append(f"  {row[0]}.{row[1]} ({row[2]})")
        return "\n".join(lines)
    finally:
        conn.close()


@tool
def get_table_stats(table_name: str) -> str:
    """Get statistics for a table: row count (estimated), table size, and index count."""
    if not table_name.replace("_", "").replace(".", "").isalnum():
        return "Invalid table name."

    db = get_db()
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        # Row count estimate (fast)
        cur.execute("""
            SELECT reltuples::bigint AS estimate
            FROM pg_class
            WHERE relname = %s
        """, (table_name,))
        row_est = cur.fetchone()
        row_count = row_est[0] if row_est else "unknown"

        # Table size
        cur.execute("SELECT pg_size_pretty(pg_total_relation_size(%s))", (table_name,))
        size = cur.fetchone()[0]

        # Index count
        cur.execute("""
            SELECT count(*) FROM pg_indexes
            WHERE tablename = %s
        """, (table_name,))
        index_count = cur.fetchone()[0]

        return (
            f"Stats for '{table_name}':\n"
            f"  Estimated rows: {row_count}\n"
            f"  Total size: {size}\n"
            f"  Indexes: {index_count}"
        )
    except Exception as e:
        return f"Error: {e}"
    finally:
        conn.close()


@tool
def get_db_info() -> str:
    """Get database info: PostgreSQL version, database name, current user, DB size, and uptime."""
    db = get_db()
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT version()")
        version = cur.fetchone()[0]

        cur.execute("SELECT current_database(), current_user")
        db_name, db_user = cur.fetchone()

        cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
        db_size = cur.fetchone()[0]

        cur.execute("SELECT now() - pg_postmaster_start_time()")
        uptime = cur.fetchone()[0]

        return (
            f"Database Info:\n"
            f"  Version: {version}\n"
            f"  Database: {db_name}\n"
            f"  User: {db_user}\n"
            f"  Size: {db_size}\n"
            f"  Uptime: {uptime}"
        )
    except Exception as e:
        return f"Error: {e}"
    finally:
        conn.close()


@tool
def get_foreign_keys(table_name: str) -> str:
    """List all foreign key relationships for a table."""
    db = get_db()
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                tc.constraint_name,
                kcu.column_name,
                ccu.table_name AS foreign_table,
                ccu.column_name AS foreign_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_name = %s
            ORDER BY tc.constraint_name
        """, (table_name,))
        rows = cur.fetchall()
        if not rows:
            return f"No foreign keys found for table '{table_name}'."
        lines = [f"Foreign keys for '{table_name}':"]
        for row in rows:
            lines.append(f"  {row[1]} → {row[2]}.{row[3]} (constraint: {row[0]})")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"
    finally:
        conn.close()


@tool
def explain_query(sql: str) -> str:
    """Run EXPLAIN (FORMAT JSON) on a query and return the execution plan summary."""
    is_safe, reason = validate_read_only_sql(sql)
    if not is_safe:
        return f"⚠ Safety Guard: Blocked. {reason}"

    db = get_db()
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"EXPLAIN (FORMAT JSON) {sql}")
        plan = cur.fetchone()[0]
        if isinstance(plan, list) and plan:
            plan_data = plan[0].get("Plan", {})
            lines = ["Query Plan Summary:"]
            lines.append(f"  Node Type: {plan_data.get('Node Type', 'N/A')}")
            lines.append(f"  Startup Cost: {plan_data.get('Startup Cost', 'N/A')}")
            lines.append(f"  Total Cost: {plan_data.get('Total Cost', 'N/A')}")
            lines.append(f"  Plan Rows: {plan_data.get('Plan Rows', 'N/A')}")
            lines.append(f"  Plan Width: {plan_data.get('Plan Width', 'N/A')}")
            if "Plans" in plan_data:
                lines.append(f"  Sub-plans: {len(plan_data['Plans'])}")
            lines.append(f"\nFull plan:\n{json.dumps(plan, indent=2)}")
            return "\n".join(lines)
        return json.dumps(plan, indent=2)
    except Exception as e:
        return f"Error: {e}"
    finally:
        conn.close()


# All tools list for agent registration
ALL_TOOLS = [
    list_tables,
    get_table_schema,
    execute_sql,
    get_table_sample,
    search_schema,
    get_table_stats,
    get_db_info,
    get_foreign_keys,
    explain_query,
]

