"""Database connection manager and schema cache."""

from typing import Optional

import psycopg2

from pgagent.config import Config


class DatabaseManager:
    """Manages PostgreSQL connections and caches schema info."""

    def __init__(self, config: Config):
        self.config = config
        self._schema_cache: Optional[list[str]] = None

    def get_connection(self):
        """Create and return a new psycopg2 connection."""
        if self.config.database_url:
            return psycopg2.connect(self.config.database_url)
        return psycopg2.connect(
            host=self.config.db_host,
            port=self.config.db_port,
            database=self.config.db_database,
            user=self.config.db_user,
            password=self.config.db_password,
        )

    def test_connection(self) -> tuple[bool, str]:
        """Test the database connection. Returns (success, message)."""
        try:
            conn = self.get_connection()
            cur = conn.cursor()
            cur.execute("SELECT version()")
            version = cur.fetchone()[0]
            conn.close()
            return True, version
        except Exception as e:
            return False, str(e)

    def get_tables(self) -> list[str]:
        """Get list of all tables in public schema (cached)."""
        if self._schema_cache is not None:
            return self._schema_cache
        self._schema_cache = self._fetch_tables()
        return self._schema_cache

    def invalidate_cache(self) -> None:
        """Force refresh of schema cache on next access."""
        self._schema_cache = None

    def _fetch_tables(self) -> list[str]:
        """Fetch table names from the database."""
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name
            """)
            return [row[0] for row in cur.fetchall()]
        finally:
            conn.close()


# Module-level instance, initialized by the CLI
_db: Optional[DatabaseManager] = None


def init_db(config: Config) -> DatabaseManager:
    """Initialize the global database manager."""
    global _db
    _db = DatabaseManager(config)
    return _db


def get_db() -> DatabaseManager:
    """Get the global database manager instance."""
    if _db is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _db

