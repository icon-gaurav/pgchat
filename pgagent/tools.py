"""Database tools for the LangChain agent.

All SQL execution goes through db.execute_sql() — no direct cursor access.
"""

import json

from langchain_core.tools import tool

from pgagent.db import execute_sql, SQLSafetyError, SQLExecutionError


@tool
def list_tables() -> str:
    """List all tables in the public schema of the connected PostgreSQL database."""
    try:
        result = execute_sql("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        tables = [row[0] for row in result.rows]
        if not tables:
            return "No tables found in the public schema."
        return f"Tables ({len(tables)}): {', '.join(tables)}"
    except SQLSafetyError as e:
        return f"Blocked: {e}"
    except SQLExecutionError as e:
        return f"DB Error: {e}"


@tool
def get_table_schema(table_name: str) -> str:
    """Get the schema (columns, types, nullability, defaults) of a specific table."""
    try:
        result = execute_sql(
            """
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position
            """,
            (table_name,),
        )
        if not result.rows:
            return f"Table '{table_name}' not found or has no columns."
        lines = [f"Schema for '{table_name}' ({result.row_count} columns):"]
        for col in result.rows:
            nullable = "NULL" if col[2] == "YES" else "NOT NULL"
            default = f" DEFAULT {col[3]}" if col[3] else ""
            lines.append(f"  {col[0]} {col[1]} {nullable}{default}")
        return "\n".join(lines)
    except SQLSafetyError as e:
        return f"Blocked: {e}"
    except SQLExecutionError as e:
        return f"DB Error: {e}"


@tool
def run_query(query: str) -> str:
    """Execute a read-only SQL query (SELECT/WITH/SHOW/EXPLAIN) and return results."""
    try:
        result = execute_sql(query)
        if not result.columns:
            return f"Query executed. Rows affected: {result.row_count}"
        if not result.rows:
            return "Query returned no results."
        output = " | ".join(result.columns) + "\n"
        output += "-" * len(output) + "\n"
        output += "\n".join(
            [" | ".join(str(v) for v in row) for row in result.rows[:50]]
        )
        if result.row_count > 50:
            output += f"\n... (showing 50 of {result.row_count} total rows)"
        else:
            output += f"\n({result.row_count} row{'s' if result.row_count != 1 else ''})"
        return output
    except SQLSafetyError as e:
        return f"Blocked: {e}"
    except SQLExecutionError as e:
        return f"DB Error: {e}"


@tool
def get_table_sample(table_name: str, limit: int = 5) -> str:
    """Get a sample of rows from a table (SELECT * LIMIT n). Useful for previewing data."""
    # Simple identifier validation
    if not table_name.replace("_", "").replace(".", "").isalnum():
        return "Invalid table name."
    if limit < 1 or limit > 20:
        limit = 5

    try:
        result = execute_sql(
            f'SELECT * FROM "{table_name}" LIMIT %s',
            (limit,),
        )
        if not result.rows:
            return f"Table '{table_name}' is empty."
        output = " | ".join(result.columns) + "\n"
        output += "-" * len(output) + "\n"
        output += "\n".join(
            [" | ".join(str(v) for v in row) for row in result.rows]
        )
        output += f"\n(sample of {result.row_count} row{'s' if result.row_count != 1 else ''})"
        return output
    except SQLSafetyError as e:
        return f"Blocked: {e}"
    except SQLExecutionError as e:
        return f"DB Error: {e}"


@tool
def search_schema(keyword: str) -> str:
    """Search all table and column names matching a keyword (case-insensitive). Useful for finding which table has a specific column."""
    try:
        result = execute_sql(
            """
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND (lower(column_name) LIKE lower(%s) OR lower(table_name) LIKE lower(%s))
            ORDER BY table_name, ordinal_position
            """,
            (f"%{keyword}%", f"%{keyword}%"),
        )
        if not result.rows:
            return f"No tables or columns matching '{keyword}' found."
        lines = [f"Matches for '{keyword}':"]
        for row in result.rows:
            lines.append(f"  {row[0]}.{row[1]} ({row[2]})")
        return "\n".join(lines)
    except SQLSafetyError as e:
        return f"Blocked: {e}"
    except SQLExecutionError as e:
        return f"DB Error: {e}"


@tool
def get_table_stats(table_name: str) -> str:
    """Get statistics for a table: row count (estimated), table size, and index count."""
    if not table_name.replace("_", "").replace(".", "").isalnum():
        return "Invalid table name."

    try:
        # Row count estimate (fast)
        r1 = execute_sql(
            "SELECT reltuples::bigint AS estimate FROM pg_class WHERE relname = %s",
            (table_name,),
        )
        row_count = r1.rows[0][0] if r1.rows else "unknown"

        # Table size
        r2 = execute_sql(
            "SELECT pg_size_pretty(pg_total_relation_size(%s))",
            (table_name,),
        )
        size = r2.rows[0][0] if r2.rows else "unknown"

        # Index count
        r3 = execute_sql(
            "SELECT count(*) FROM pg_indexes WHERE tablename = %s",
            (table_name,),
        )
        index_count = r3.rows[0][0] if r3.rows else 0

        return (
            f"Stats for '{table_name}':\n"
            f"  Estimated rows: {row_count}\n"
            f"  Total size: {size}\n"
            f"  Indexes: {index_count}"
        )
    except SQLSafetyError as e:
        return f"Blocked: {e}"
    except SQLExecutionError as e:
        return f"DB Error: {e}"


@tool
def get_db_info() -> str:
    """Get database info: PostgreSQL version, database name, current user, DB size, and uptime."""
    try:
        r1 = execute_sql("SELECT version()")
        version = r1.rows[0][0] if r1.rows else "N/A"

        r2 = execute_sql("SELECT current_database(), current_user")
        db_name, db_user = r2.rows[0] if r2.rows else ("N/A", "N/A")

        r3 = execute_sql("SELECT pg_size_pretty(pg_database_size(current_database()))")
        db_size = r3.rows[0][0] if r3.rows else "N/A"

        r4 = execute_sql("SELECT now() - pg_postmaster_start_time()")
        uptime = r4.rows[0][0] if r4.rows else "N/A"

        return (
            f"Database Info:\n"
            f"  Version: {version}\n"
            f"  Database: {db_name}\n"
            f"  User: {db_user}\n"
            f"  Size: {db_size}\n"
            f"  Uptime: {uptime}"
        )
    except SQLSafetyError as e:
        return f"Blocked: {e}"
    except SQLExecutionError as e:
        return f"DB Error: {e}"


@tool
def get_foreign_keys(table_name: str) -> str:
    """List all foreign key relationships for a table."""
    try:
        result = execute_sql(
            """
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
            """,
            (table_name,),
        )
        if not result.rows:
            return f"No foreign keys found for table '{table_name}'."
        lines = [f"Foreign keys for '{table_name}':"]
        for row in result.rows:
            lines.append(f"  {row[1]} → {row[2]}.{row[3]} (constraint: {row[0]})")
        return "\n".join(lines)
    except SQLSafetyError as e:
        return f"Blocked: {e}"
    except SQLExecutionError as e:
        return f"DB Error: {e}"


@tool
def explain_query(sql: str) -> str:
    """Run EXPLAIN (FORMAT JSON) on a query and return the execution plan summary."""
    try:
        result = execute_sql(f"EXPLAIN (FORMAT JSON) {sql}")
        plan = result.rows[0][0] if result.rows else None
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
        return json.dumps(plan, indent=2) if plan else "No plan returned."
    except SQLSafetyError as e:
        return f"Blocked: {e}"
    except SQLExecutionError as e:
        return f"DB Error: {e}"


# All tools list for agent registration
ALL_TOOLS = [
    list_tables,
    get_table_schema,
    run_query,
    get_table_sample,
    search_schema,
    get_table_stats,
    get_db_info,
    get_foreign_keys,
    explain_query,
]

