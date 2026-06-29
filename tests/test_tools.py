"""Tests for pgchat.tools — database tool functions.

All tools now go through the db.execute_sql() gateway. We mock that single function.
"""

import pytest
from unittest.mock import patch, MagicMock

from pgchat.db import ExecutionResult, SQLSafetyError, SQLExecutionError
from pgchat.tools import (
    list_tables,
    get_table_schema,
    run_query,
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
def mock_execute():
    """Mock the db.execute_sql gateway function."""
    with patch("pgchat.tools.execute_sql") as mock_fn:
        yield mock_fn


# ──────────────────────────────────────────────
# list_tables
# ──────────────────────────────────────────────


class TestListTables:
    def test_returns_tables(self, mock_execute):
        mock_execute.return_value = ExecutionResult(
            rows=[("users",), ("orders",), ("products",)],
            columns=["table_name"],
            row_count=3,
        )
        result = list_tables.invoke({})
        assert "users" in result
        assert "orders" in result
        assert "products" in result
        assert "3" in result

    def test_no_tables(self, mock_execute):
        mock_execute.return_value = ExecutionResult(rows=[], columns=["table_name"], row_count=0)
        result = list_tables.invoke({})
        assert "No tables" in result

    def test_handles_safety_error(self, mock_execute):
        mock_execute.side_effect = SQLSafetyError("blocked")
        result = list_tables.invoke({})
        assert "Blocked" in result

    def test_handles_execution_error(self, mock_execute):
        mock_execute.side_effect = SQLExecutionError("connection lost")
        result = list_tables.invoke({})
        assert "DB Error" in result


# ──────────────────────────────────────────────
# get_table_schema
# ──────────────────────────────────────────────


class TestGetTableSchema:
    def test_returns_schema(self, mock_execute):
        mock_execute.return_value = ExecutionResult(
            rows=[
                ("id", "integer", "NO", None),
                ("name", "character varying", "YES", None),
                ("email", "character varying", "NO", "'default@test.com'"),
            ],
            columns=["column_name", "data_type", "is_nullable", "column_default"],
            row_count=3,
        )
        result = get_table_schema.invoke({"table_name": "users"})
        assert "users" in result
        assert "id" in result
        assert "integer" in result
        assert "NOT NULL" in result
        assert "name" in result
        assert "NULL" in result
        assert "DEFAULT" in result

    def test_table_not_found(self, mock_execute):
        mock_execute.return_value = ExecutionResult(rows=[], columns=[], row_count=0)
        result = get_table_schema.invoke({"table_name": "nonexistent"})
        assert "not found" in result

    def test_handles_execution_error(self, mock_execute):
        mock_execute.side_effect = SQLExecutionError("table error")
        result = get_table_schema.invoke({"table_name": "t"})
        assert "DB Error" in result


# ──────────────────────────────────────────────
# run_query (previously execute_sql tool)
# ──────────────────────────────────────────────


class TestRunQuery:
    def test_select_returns_results(self, mock_execute):
        mock_execute.return_value = ExecutionResult(
            rows=[(1, "Alice"), (2, "Bob")],
            columns=["id", "name"],
            row_count=2,
        )
        result = run_query.invoke({"query": "SELECT id, name FROM users"})
        assert "id" in result
        assert "name" in result
        assert "Alice" in result
        assert "Bob" in result
        assert "2 rows" in result

    def test_select_no_results(self, mock_execute):
        mock_execute.return_value = ExecutionResult(
            rows=[], columns=["id"], row_count=0
        )
        result = run_query.invoke({"query": "SELECT id FROM users WHERE 1=0"})
        assert "no results" in result

    def test_blocks_insert(self, mock_execute):
        mock_execute.side_effect = SQLSafetyError("Only read-only queries are allowed")
        result = run_query.invoke({"query": "INSERT INTO users (name) VALUES ('x')"})
        assert "Blocked" in result

    def test_blocks_drop(self, mock_execute):
        mock_execute.side_effect = SQLSafetyError("Only read-only queries are allowed")
        result = run_query.invoke({"query": "DROP TABLE users"})
        assert "Blocked" in result

    def test_blocks_delete(self, mock_execute):
        mock_execute.side_effect = SQLSafetyError("Only read-only queries are allowed")
        result = run_query.invoke({"query": "DELETE FROM users"})
        assert "Blocked" in result

    def test_handles_sql_error(self, mock_execute):
        mock_execute.side_effect = SQLExecutionError("relation does not exist")
        result = run_query.invoke({"query": "SELECT * FROM nonexistent"})
        assert "DB Error" in result
        assert "relation does not exist" in result

    def test_truncates_large_result(self, mock_execute):
        mock_execute.return_value = ExecutionResult(
            rows=[(i,) for i in range(100)],
            columns=["id"],
            row_count=100,
        )
        result = run_query.invoke({"query": "SELECT id FROM big_table"})
        assert "showing 50 of 100" in result


# ──────────────────────────────────────────────
# get_table_sample
# ──────────────────────────────────────────────


class TestGetTableSample:
    def test_returns_sample(self, mock_execute):
        mock_execute.return_value = ExecutionResult(
            rows=[(1, "Alice"), (2, "Bob")],
            columns=["id", "name"],
            row_count=2,
        )
        result = get_table_sample.invoke({"table_name": "users", "limit": 2})
        assert "Alice" in result
        assert "Bob" in result
        assert "sample" in result

    def test_empty_table(self, mock_execute):
        mock_execute.return_value = ExecutionResult(rows=[], columns=["id"], row_count=0)
        result = get_table_sample.invoke({"table_name": "users"})
        assert "empty" in result

    def test_invalid_table_name(self, mock_execute):
        result = get_table_sample.invoke({"table_name": "'; DROP TABLE--"})
        assert "Invalid" in result
        mock_execute.assert_not_called()

    def test_limit_clamped(self, mock_execute):
        mock_execute.return_value = ExecutionResult(
            rows=[(1,)], columns=["id"], row_count=1
        )
        # limit > 20 should be clamped to 5
        get_table_sample.invoke({"table_name": "users", "limit": 100})
        call_args = mock_execute.call_args
        assert "LIMIT %s" in call_args[0][0]
        assert call_args[0][1] == (5,)

    def test_handles_execution_error(self, mock_execute):
        mock_execute.side_effect = SQLExecutionError("permission denied")
        result = get_table_sample.invoke({"table_name": "users"})
        assert "DB Error" in result


# ──────────────────────────────────────────────
# search_schema
# ──────────────────────────────────────────────


class TestSearchSchema:
    def test_finds_matches(self, mock_execute):
        mock_execute.return_value = ExecutionResult(
            rows=[
                ("users", "email", "character varying"),
                ("customers", "email_address", "text"),
            ],
            columns=["table_name", "column_name", "data_type"],
            row_count=2,
        )
        result = search_schema.invoke({"keyword": "email"})
        assert "users.email" in result
        assert "customers.email_address" in result

    def test_no_matches(self, mock_execute):
        mock_execute.return_value = ExecutionResult(rows=[], columns=[], row_count=0)
        result = search_schema.invoke({"keyword": "nonexistent"})
        assert "No tables or columns" in result

    def test_handles_execution_error(self, mock_execute):
        mock_execute.side_effect = SQLExecutionError("error")
        result = search_schema.invoke({"keyword": "x"})
        assert "DB Error" in result


# ──────────────────────────────────────────────
# get_table_stats
# ──────────────────────────────────────────────


class TestGetTableStats:
    def test_returns_stats(self, mock_execute):
        mock_execute.side_effect = [
            ExecutionResult(rows=[(1500,)], columns=["estimate"], row_count=1),
            ExecutionResult(rows=[("128 kB",)], columns=["pg_size_pretty"], row_count=1),
            ExecutionResult(rows=[(3,)], columns=["count"], row_count=1),
        ]
        result = get_table_stats.invoke({"table_name": "users"})
        assert "1500" in result
        assert "128 kB" in result
        assert "3" in result
        assert "users" in result

    def test_invalid_table_name(self, mock_execute):
        result = get_table_stats.invoke({"table_name": "'; DROP --"})
        assert "Invalid" in result
        mock_execute.assert_not_called()

    def test_handles_error(self, mock_execute):
        mock_execute.side_effect = SQLExecutionError("relation not found")
        result = get_table_stats.invoke({"table_name": "bad_table"})
        assert "DB Error" in result


# ──────────────────────────────────────────────
# get_db_info
# ──────────────────────────────────────────────


class TestGetDbInfo:
    def test_returns_info(self, mock_execute):
        mock_execute.side_effect = [
            ExecutionResult(rows=[("PostgreSQL 16.2 on x86_64",)], columns=["version"], row_count=1),
            ExecutionResult(rows=[("mydb", "admin")], columns=["current_database", "current_user"], row_count=1),
            ExecutionResult(rows=[("256 MB",)], columns=["pg_size_pretty"], row_count=1),
            ExecutionResult(rows=[("5 days 03:22:11",)], columns=["interval"], row_count=1),
        ]
        result = get_db_info.invoke({})
        assert "PostgreSQL 16.2" in result
        assert "mydb" in result
        assert "admin" in result
        assert "256 MB" in result
        assert "5 days" in result

    def test_handles_error(self, mock_execute):
        mock_execute.side_effect = SQLExecutionError("connection failed")
        result = get_db_info.invoke({})
        assert "DB Error" in result


# ──────────────────────────────────────────────
# get_foreign_keys
# ──────────────────────────────────────────────


class TestGetForeignKeys:
    def test_returns_fks(self, mock_execute):
        mock_execute.return_value = ExecutionResult(
            rows=[
                ("fk_order_user", "user_id", "users", "id"),
                ("fk_order_product", "product_id", "products", "id"),
            ],
            columns=["constraint_name", "column_name", "foreign_table", "foreign_column"],
            row_count=2,
        )
        result = get_foreign_keys.invoke({"table_name": "orders"})
        assert "user_id" in result
        assert "users.id" in result
        assert "product_id" in result
        assert "products.id" in result

    def test_no_fks(self, mock_execute):
        mock_execute.return_value = ExecutionResult(rows=[], columns=[], row_count=0)
        result = get_foreign_keys.invoke({"table_name": "standalone"})
        assert "No foreign keys" in result

    def test_handles_error(self, mock_execute):
        mock_execute.side_effect = SQLExecutionError("table not found")
        result = get_foreign_keys.invoke({"table_name": "bad"})
        assert "DB Error" in result


# ──────────────────────────────────────────────
# explain_query
# ──────────────────────────────────────────────


class TestExplainQuery:
    def test_returns_plan(self, mock_execute):
        plan_data = [{"Plan": {
            "Node Type": "Seq Scan",
            "Startup Cost": 0.0,
            "Total Cost": 35.5,
            "Plan Rows": 1000,
            "Plan Width": 64,
        }}]
        mock_execute.return_value = ExecutionResult(
            rows=[(plan_data,)], columns=["QUERY PLAN"], row_count=1
        )
        result = explain_query.invoke({"sql": "SELECT * FROM users"})
        assert "Seq Scan" in result
        assert "35.5" in result
        assert "1000" in result

    def test_with_sub_plans(self, mock_execute):
        plan_data = [{"Plan": {
            "Node Type": "Hash Join",
            "Startup Cost": 1.0,
            "Total Cost": 100.0,
            "Plan Rows": 500,
            "Plan Width": 128,
            "Plans": [{"Node Type": "Seq Scan"}, {"Node Type": "Hash"}],
        }}]
        mock_execute.return_value = ExecutionResult(
            rows=[(plan_data,)], columns=["QUERY PLAN"], row_count=1
        )
        result = explain_query.invoke({"sql": "SELECT * FROM a JOIN b ON a.id=b.id"})
        assert "Sub-plans: 2" in result

    def test_blocks_unsafe_query(self, mock_execute):
        mock_execute.side_effect = SQLSafetyError("blocked keyword: DROP")
        result = explain_query.invoke({"sql": "DROP TABLE users"})
        assert "Blocked" in result

    def test_handles_error(self, mock_execute):
        mock_execute.side_effect = SQLExecutionError("syntax error")
        result = explain_query.invoke({"sql": "SELECT bad syntax"})
        assert "DB Error" in result
