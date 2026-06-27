"""Schema cache — fetches full DB schema once on startup, provides LLM-friendly text.

Caching rule: schema is fetched ONCE on startup and injected into the system prompt.
It is NEVER re-fetched during conversation unless /refresh-schema is run.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from pgagent.db import execute_sql, SQLSafetyError, SQLExecutionError


@dataclass
class ColumnInfo:
    """A single column in a table."""
    name: str
    data_type: str
    nullable: bool
    default: Optional[str] = None


@dataclass
class TableInfo:
    """Schema and stats for a single table."""
    name: str
    columns: list[ColumnInfo] = field(default_factory=list)
    foreign_keys: list[str] = field(default_factory=list)  # e.g. "orders.user_id → users.id"
    row_count: Optional[int] = None
    size: Optional[str] = None


@dataclass
class SchemaCache:
    """Full database schema snapshot."""
    tables: list[TableInfo] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    db_name: str = ""
    db_version: str = ""

    def to_system_prompt_text(self) -> str:
        """
        Renders the schema as a compact, LLM-friendly text block injected
        into the system prompt for every conversation turn.
        """
        lines = [
            f"DATABASE: {self.db_name} ({self.db_version})",
            f"SCHEMA SNAPSHOT (captured at {self.fetched_at.strftime('%Y-%m-%d %H:%M:%S UTC')}):",
            "",
        ]

        if not self.tables:
            lines.append("(No tables found in public schema)")
        else:
            for table in self.tables:
                header_parts = [f"TABLE: {table.name}"]
                meta = []
                if table.row_count is not None:
                    meta.append(f"{table.row_count:,} rows")
                if table.size:
                    meta.append(table.size)
                if meta:
                    header_parts.append(f"({', '.join(meta)})")
                lines.append("  ".join(header_parts))

                for col in table.columns:
                    null_str = "nullable" if col.nullable else "not null"
                    default_str = f", default={col.default}" if col.default else ""
                    lines.append(f"    - {col.name} ({col.data_type}, {null_str}{default_str})")

                for fk in table.foreign_keys:
                    lines.append(f"    FK: {fk}")

                lines.append("")

        lines.append(
            "Use this schema to answer questions. Do not call list_tables or "
            "get_table_schema unless the user explicitly asks to refresh the schema."
        )
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Serialize schema cache for session JSON storage."""
        return {
            "fetched_at": self.fetched_at.isoformat(),
            "db_name": self.db_name,
            "db_version": self.db_version,
            "tables": [
                {
                    "name": t.name,
                    "columns": [
                        {
                            "name": c.name,
                            "data_type": c.data_type,
                            "nullable": c.nullable,
                            "default": c.default,
                        }
                        for c in t.columns
                    ],
                    "foreign_keys": t.foreign_keys,
                    "row_count": t.row_count,
                    "size": t.size,
                }
                for t in self.tables
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SchemaCache":
        """Reconstruct a SchemaCache from session JSON data."""
        fetched_at_str = data.get("fetched_at", "")
        try:
            fetched_at = datetime.fromisoformat(fetched_at_str)
        except (ValueError, TypeError):
            fetched_at = datetime.now(timezone.utc)

        tables = []
        for t in data.get("tables", []):
            columns = [
                ColumnInfo(
                    name=c["name"],
                    data_type=c["data_type"],
                    nullable=c.get("nullable", True),
                    default=c.get("default"),
                )
                for c in t.get("columns", [])
            ]
            tables.append(TableInfo(
                name=t["name"],
                columns=columns,
                foreign_keys=t.get("foreign_keys", []),
                row_count=t.get("row_count"),
                size=t.get("size"),
            ))

        return cls(
            tables=tables,
            fetched_at=fetched_at,
            db_name=data.get("db_name", ""),
            db_version=data.get("db_version", ""),
        )

    def table_names(self) -> list[str]:
        """Get list of table names in cache."""
        return [t.name for t in self.tables]

    def diff_summary(self, other: "SchemaCache") -> str:
        """Compare with another cache and return a human-readable diff summary."""
        old_names = set(self.table_names())
        new_names = set(other.table_names())
        added = new_names - old_names
        removed = old_names - new_names
        parts = [f"{len(other.tables)} tables"]
        if added:
            parts.append(f"added: {', '.join(sorted(added))}")
        if removed:
            parts.append(f"removed: {', '.join(sorted(removed))}")
        if not added and not removed:
            parts.append("no structural changes")
        return f"was {len(self.tables)}, " + ", ".join(parts)


def build_schema_cache() -> SchemaCache:
    """
    Fetch the full database schema in a single startup pass.
    All queries go through the db.execute_sql() gateway.
    """
    cache = SchemaCache()

    # 1. DB version
    try:
        r = execute_sql("SELECT version()")
        raw_version = r.rows[0][0] if r.rows else ""
        # Extract just "PostgreSQL X.Y" from the full string
        if "PostgreSQL" in raw_version:
            cache.db_version = raw_version.split(",")[0].strip()
        else:
            cache.db_version = raw_version[:60]
    except (SQLSafetyError, SQLExecutionError):
        cache.db_version = "unknown"

    # 2. DB name
    try:
        r = execute_sql("SELECT current_database()")
        cache.db_name = r.rows[0][0] if r.rows else "unknown"
    except (SQLSafetyError, SQLExecutionError):
        cache.db_name = "unknown"

    # 3. All tables in public schema
    try:
        r = execute_sql("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        table_names = [row[0] for row in r.rows]
    except (SQLSafetyError, SQLExecutionError):
        table_names = []

    if not table_names:
        return cache

    # 4. All columns
    try:
        r = execute_sql("""
            SELECT table_name, column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public'
            ORDER BY table_name, ordinal_position
        """)
        columns_by_table: dict[str, list[ColumnInfo]] = {}
        for row in r.rows:
            tname, cname, dtype, nullable, default = row
            col = ColumnInfo(
                name=cname,
                data_type=dtype,
                nullable=(nullable == "YES"),
                default=default,
            )
            columns_by_table.setdefault(tname, []).append(col)
    except (SQLSafetyError, SQLExecutionError):
        columns_by_table = {}

    # 5. All foreign keys
    try:
        r = execute_sql("""
            SELECT
                tc.table_name,
                kcu.column_name,
                ccu.table_name AS foreign_table,
                ccu.column_name AS foreign_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
                AND tc.table_schema = ccu.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = 'public'
            ORDER BY tc.table_name
        """)
        fks_by_table: dict[str, list[str]] = {}
        for row in r.rows:
            tname, col, ftable, fcol = row
            fk_str = f"{tname}.{col} → {ftable}.{fcol}"
            fks_by_table.setdefault(tname, []).append(fk_str)
    except (SQLSafetyError, SQLExecutionError):
        fks_by_table = {}

    # 6. Row counts and sizes
    stats_by_table: dict[str, tuple[Optional[int], Optional[str]]] = {}
    try:
        r = execute_sql("""
            SELECT
                relname,
                n_live_tup::bigint,
                pg_size_pretty(pg_total_relation_size(quote_ident(relname)))
            FROM pg_stat_user_tables
            WHERE schemaname = 'public'
            ORDER BY relname
        """)
        for row in r.rows:
            tname, row_count, size = row
            stats_by_table[tname] = (row_count, size)
    except (SQLSafetyError, SQLExecutionError):
        pass

    # Assemble TableInfo objects
    for tname in table_names:
        row_count, size = stats_by_table.get(tname, (None, None))
        cache.tables.append(TableInfo(
            name=tname,
            columns=columns_by_table.get(tname, []),
            foreign_keys=fks_by_table.get(tname, []),
            row_count=row_count,
            size=size,
        ))

    return cache

