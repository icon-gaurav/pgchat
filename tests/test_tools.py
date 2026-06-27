"""Tests for pgagent.tools — database tool functions."""

import pytest
from unittest.mock import patch, MagicMock

from pgagent.tools import (
    list_tables,
    get_table_schema,
    execute_sql,
    get_table_sample,
    search_schema,
    get_table_stats,
    get_db_info,
    get_foreign_keys,
    explain_query,
)


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────


@pytest.fixture
def mock_db():
    """Mock the get_db() function to return a mock DatabaseManager."""
    with patch("pgagent.tools.get_db") as mock_get_db:
        db_instance = MagicMock()
        mock_get_db.return_value = db_instance
        conn = MagicMock()
        db_instance.get_connection.return_value = conn
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        yield {
            "db": db_instance,
            "conn": conn,
            "cursor": cursor,
        }


# ──────────────────────────────────────────────
# list_tables
# ──────────────────────────────────────────────


class TestListTables:
    def test_returns_tables(self, mock_db):
        mock_db["cursor"].fetchall.return_value = [
            ("users",), ("orders",), ("products",)
        ]
        result = list_tables.invoke({})
        assert "users" in result
        assert "orders" in result
        assert "products" in result
        assert "3" in result  # count

    def test_no_tables(self, mock_db):
        mock_db["cursor"].fetchall.return_value = []
        result = list_tables.invoke({})
        assert "No tables" in result

    def test_connection_closed(self, mock_db):
        mock_db["cursor"].fetchall.return_value = [("t1",)]
        list_tables.invoke({})
        mock_db["conn"].close.assert_called_once()


# ──────────────────────────────────────────────
# get_table_schema
# ──────────────────────────────────────────────


class TestGetTableSchema:
    def test_returns_schema(self, mock_db):
        mock_db["cursor"].fetchall.return_value = [
            ("id", "integer", "NO", None),
            ("name", "character varying", "YES", None),
            ("email", "character varying", "NO", "'default@test.com'"),
        ]
        result = get_table_schema.invoke({"table_name": "users"})
        assert "users" in result
        assert "id" in result
        assert "integer" in result
        assert "NOT NULL" in result
        assert "name" in result
        assert "NULL" in result
        assert "DEFAULT" in result

    def test_table_not_found(self, mock_db):
        mock_db["cursor"].fetchall.return_value = []
        result = get_table_schema.invoke({"table_name": "nonexistent"})
        assert "not found" in result

    def test_connection_closed(self, mock_db):
        mock_db["cursor"].fetchall.return_value = []
        get_table_schema.invoke({"table_name": "t"})
        mock_db["conn"].close.assert_called_once()


# ──────────────────────────────────────────────
# execute_sql
# ──────────────────────────────────────────────


class TestExecuteSql:
    def test_select_returns_results(self, mock_db):
        mock_db["cursor"].description = [("id",), ("name",)]
        mock_db["cursor"].fetchall.return_value = [(1, "Alice"), (2, "Bob")]
        result = execute_sql.invoke({"query": "SELECT id, name FROM users"})
        assert "id" in result
        assert "name" in result
        assert "Alice" in result
        assert "Bob" in result
        assert "2 rows" in result

    def test_select_no_results(self, mock_db):
        mock_db["cursor"].description = [("id",)]
        mock_db["cursor"].fetchall.return_value = []
        result = execute_sql.invoke({"query": "SELECT id FROM users WHERE 1=0"})
        assert "no results" in result

    def test_blocks_insert(self, mock_db):
        result = execute_sql.invoke({"query": "INSERT INTO users (name) VALUES ('x')"})
        assert "Safety Guard" in result
        assert "Blocked" in result
        # Should NOT have called execute
        mock_db["cursor"].execute.assert_not_called()

    def test_blocks_drop(self, mock_db):
        result = execute_sql.invoke({"query": "DROP TABLE users"})
        assert "Safety Guard" in result
        mock_db["cursor"].execute.assert_not_called()

    def test_blocks_delete(self, mock_db):
        result = execute_sql.invoke({"query": "DELETE FROM users"})
        assert "Safety Guard" in result
        mock_db["cursor"].execute.assert_not_called()

    def test_handles_sql_error(self, mock_db):
        mock_db["cursor"].execute.side_effect = Exception("relation does not exist")
        result = execute_sql.invoke({"query": "SELECT * FROM nonexistent"})
        assert "SQL Error" in result
        assert "relation does not exist" in result

    def test_truncates_large_result(self, mock_db):
        mock_db["cursor"].description = [("id",)]
        mock_db["cursor"].fetchall.return_value = [(i,) for i in range(100)]
        result = execute_sql.invoke({"query": "SELECT id FROM big_table"})
        assert "showing 50 of 100" in result

    def test_connection_closed_on_success(self, mock_db):
        mock_db["cursor"].description = [("x",)]
        mock_db["cursor"].fetchall.return_value = [(1,)]
        execute_sql.invoke({"query": "SELECT 1"})
        mock_db["conn"].close.assert_called_once()

    def test_connection_closed_on_error(self, mock_db):
        mock_db["cursor"].execute.side_effect = Exception("boom")
        execute_sql.invoke({"query": "SELECT 1"})
        mock_db["conn"].close.assert_called_once()


# ──────────────────────────────────────────────
# get_table_sample
# ──────────────────────────────────────────────


class TestGetTableSample:
    def test_returns_sample(self, mock_db):
        mock_db["cursor"].description = [("id",), ("name",)]
        mock_db["cursor"].fetchall.return_value = [(1, "Alice"), (2, "Bob")]
        result = get_table_sample.invoke({"table_name": "users", "limit": 2})
        assert "Alice" in result
        assert "Bob" in result
        assert "sample" in result

    def test_empty_table(self, mock_db):
        mock_db["cursor"].description = [("id",)]
        mock_db["cursor"].fetchall.return_value = []
        result = get_table_sample.invoke({"table_name": "users"})
        assert "empty" in result

    def test_invalid_table_name(self, mock_db):
        result = get_table_sample.invoke({"table_name": "'; DROP TABLE--"})
        assert "Invalid" in result
        mock_db["cursor"].execute.assert_not_called()

    def test_limit_clamped(self, mock_db):
        mock_db["cursor"].description = [("id",)]
        mock_db["cursor"].fetchall.return_value = [(1,)]
        # limit > 20 should be clamped to 5
        get_table_sample.invoke({"table_name": "users", "limit": 100})
        call_args = mock_db["cursor"].execute.call_args
        assert call_args[0][1] == (5,)

    def test_connection_closed(self, mock_db):
        mock_db["cursor"].description = [("id",)]
        mock_db["cursor"].fetchall.return_value = [(1,)]
        get_table_sample.invoke({"table_name": "users"})
        mock_db["conn"].close.assert_called_once()


# ──────────────────────────────────────────────
# search_schema
# ──────────────────────────────────────────────


class TestSearchSchema:
    def test_finds_matches(self, mock_db):
        mock_db["cursor"].fetchall.return_value = [
            ("users", "email", "character varying"),
            ("customers", "email_address", "text"),
        ]
        result = search_schema.invoke({"keyword": "email"})
        assert "users.email" in result
        assert "customers.email_address" in result
        assert "email" in result

    def test_no_matches(self, mock_db):
        mock_db["cursor"].fetchall.return_value = []
        result = search_schema.invoke({"keyword": "nonexistent"})
        assert "No tables or columns" in result

    def test_connection_closed(self, mock_db):
        mock_db["cursor"].fetchall.return_value = []
        search_schema.invoke({"keyword": "x"})
        mock_db["conn"].close.assert_called_once()


# ──────────────────────────────────────────────
# get_table_stats
# ──────────────────────────────────────────────


class TestGetTableStats:
    def test_returns_stats(self, mock_db):
        mock_db["cursor"].fetchone.side_effect = [
            (1500,),       # row count estimate
            ("128 kB",),   # table size
            (3,),          # index count
        ]
        result = get_table_stats.invoke({"table_name": "users"})
        assert "1500" in result
        assert "128 kB" in result
        assert "3" in result
        assert "users" in result

    def test_invalid_table_name(self, mock_db):
        result = get_table_stats.invoke({"table_name": "'; DROP --"})
        assert "Invalid" in result
        mock_db["cursor"].execute.assert_not_called()

    def test_handles_error(self, mock_db):
        mock_db["cursor"].execute.side_effect = Exception("relation not found")
        result = get_table_stats.invoke({"table_name": "bad_table"})
        assert "Error" in result

    def test_connection_closed(self, mock_db):
        mock_db["cursor"].fetchone.side_effect = [(100,), ("8 kB",), (1,)]
        get_table_stats.invoke({"table_name": "t"})
        mock_db["conn"].close.assert_called_once()


# ──────────────────────────────────────────────
# get_db_info
# ──────────────────────────────────────────────


class TestGetDbInfo:
    def test_returns_info(self, mock_db):
        mock_db["cursor"].fetchone.side_effect = [
            ("PostgreSQL 16.2 on x86_64",),
            ("mydb", "admin"),
            ("256 MB",),
            ("5 days 03:22:11",),
        ]
        result = get_db_info.invoke({})
        assert "PostgreSQL 16.2" in result
        assert "mydb" in result
        assert "admin" in result
        assert "256 MB" in result
        assert "5 days" in result

    def test_handles_error(self, mock_db):
        mock_db["cursor"].execute.side_effect = Exception("connection failed")
        result = get_db_info.invoke({})
        assert "Error" in result

    def test_connection_closed(self, mock_db):
        mock_db["cursor"].fetchone.side_effect = [
            ("PG 16",), ("db", "user"), ("1 MB",), ("1 day",)
        ]
        get_db_info.invoke({})
        mock_db["conn"].close.assert_called_once()


# ──────────────────────────────────────────────
# get_foreign_keys
# ──────────────────────────────────────────────


class TestGetForeignKeys:
    def test_returns_fks(self, mock_db):
        mock_db["cursor"].fetchall.return_value = [
            ("fk_order_user", "user_id", "users", "id"),
            ("fk_order_product", "product_id", "products", "id"),
        ]
        result = get_foreign_keys.invoke({"table_name": "orders"})
        assert "user_id" in result
        assert "users.id" in result
        assert "product_id" in result
        assert "products.id" in result
        assert "orders" in result

    def test_no_fks(self, mock_db):
        mock_db["cursor"].fetchall.return_value = []
        result = get_foreign_keys.invoke({"table_name": "standalone"})
        assert "No foreign keys" in result

    def test_handles_error(self, mock_db):
        mock_db["cursor"].execute.side_effect = Exception("table not found")
        result = get_foreign_keys.invoke({"table_name": "bad"})
        assert "Error" in result

    def test_connection_closed(self, mock_db):
        mock_db["cursor"].fetchall.return_value = []
        get_foreign_keys.invoke({"table_name": "t"})
        mock_db["conn"].close.assert_called_once()


# ──────────────────────────────────────────────
# explain_query
# ──────────────────────────────────────────────


class TestExplainQuery:
    def test_returns_plan(self, mock_db):
        plan_data = [{"Plan": {
            "Node Type": "Seq Scan",
            "Startup Cost": 0.0,
            "Total Cost": 35.5,
            "Plan Rows": 1000,
            "Plan Width": 64,
        }}]
        mock_db["cursor"].fetchone.return_value = (plan_data,)
        result = explain_query.invoke({"sql": "SELECT * FROM users"})
        assert "Seq Scan" in result
        assert "35.5" in result
        assert "1000" in result

    def test_with_sub_plans(self, mock_db):
        plan_data = [{"Plan": {
            "Node Type": "Hash Join",
            "Startup Cost": 1.0,
            "Total Cost": 100.0,
            "Plan Rows": 500,
            "Plan Width": 128,
            "Plans": [{"Node Type": "Seq Scan"}, {"Node Type": "Hash"}],
        }}]
        mock_db["cursor"].fetchone.return_value = (plan_data,)
        result = explain_query.invoke({"sql": "SELECT * FROM a JOIN b ON a.id=b.id"})
        assert "Sub-plans: 2" in result

    def test_blocks_unsafe_query(self, mock_db):
        result = explain_query.invoke({"sql": "DROP TABLE users"})
        assert "Safety Guard" in result
        mock_db["cursor"].execute.assert_not_called()

    def test_handles_error(self, mock_db):
        mock_db["cursor"].execute.side_effect = Exception("syntax error")
        result = explain_query.invoke({"sql": "SELECT bad syntax"})
        assert "Error" in result

    def test_connection_closed(self, mock_db):
        mock_db["cursor"].fetchone.return_value = ([{"Plan": {}}],)
        explain_query.invoke({"sql": "SELECT 1"})
        mock_db["conn"].close.assert_called_once()

