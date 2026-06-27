"""Tests for pgagent.safety — SQL read-only validation."""

import pytest

from pgagent.safety import normalize_sql_for_safety, validate_read_only_sql


# ──────────────────────────────────────────────
# normalize_sql_for_safety
# ──────────────────────────────────────────────


class TestNormalizeSql:
    """Tests for the SQL normalization helper."""

    def test_removes_block_comments(self):
        sql = "SELECT /* this is a comment */ 1"
        result = normalize_sql_for_safety(sql)
        assert "comment" not in result
        assert "SELECT" in result

    def test_removes_multiline_block_comments(self):
        sql = "SELECT /*\n multi\n line\n */ id FROM users"
        result = normalize_sql_for_safety(sql)
        assert "multi" not in result
        assert "SELECT" in result

    def test_removes_line_comments(self):
        sql = "SELECT 1 -- inline comment\nFROM users"
        result = normalize_sql_for_safety(sql)
        assert "inline" not in result
        assert "SELECT" in result
        assert "FROM" in result

    def test_replaces_single_quoted_strings(self):
        sql = "SELECT * FROM users WHERE name = 'DROP TABLE users'"
        result = normalize_sql_for_safety(sql)
        # The dangerous text inside quotes should be neutralized
        assert "DROP TABLE" not in result

    def test_replaces_double_quoted_identifiers(self):
        sql = 'SELECT * FROM "my table" WHERE id = 1'
        result = normalize_sql_for_safety(sql)
        assert "my table" not in result

    def test_collapses_whitespace(self):
        sql = "SELECT   id,\n   name   FROM    users"
        result = normalize_sql_for_safety(sql)
        assert "  " not in result

    def test_handles_escaped_single_quotes(self):
        sql = "SELECT * FROM t WHERE name = 'it''s fine'"
        result = normalize_sql_for_safety(sql)
        # Should not break on escaped quotes
        assert "SELECT" in result

    def test_empty_string(self):
        assert normalize_sql_for_safety("") == ""

    def test_only_whitespace(self):
        assert normalize_sql_for_safety("   \n\t  ") == ""


# ──────────────────────────────────────────────
# validate_read_only_sql — ALLOWED queries
# ──────────────────────────────────────────────


class TestValidateAllowed:
    """Queries that SHOULD pass validation."""

    @pytest.mark.parametrize("query", [
        "SELECT 1",
        "SELECT * FROM users",
        "SELECT id, name FROM customers WHERE active = true",
        "SELECT count(*) FROM orders",
        "select lower(name) from users",  # lowercase
        "WITH cte AS (SELECT 1) SELECT * FROM cte",
        "SHOW server_version",
        "SHOW ALL",
        "EXPLAIN SELECT * FROM users",
        "EXPLAIN (FORMAT JSON) SELECT id FROM t",
        "SELECT * FROM users;",  # trailing semicolon is ok
        "SELECT * FROM users WHERE email LIKE '%@example.com'",
        "SELECT u.id, o.total FROM users u JOIN orders o ON u.id = o.user_id",
    ])
    def test_allowed_queries(self, query):
        is_safe, reason = validate_read_only_sql(query)
        assert is_safe is True, f"Expected safe but got: {reason}"
        assert reason == ""


# ──────────────────────────────────────────────
# validate_read_only_sql — BLOCKED queries
# ──────────────────────────────────────────────


class TestValidateBlocked:
    """Queries that MUST be blocked."""

    def test_empty_query(self):
        is_safe, reason = validate_read_only_sql("")
        assert is_safe is False
        assert "Empty" in reason

    def test_whitespace_only(self):
        is_safe, reason = validate_read_only_sql("   ")
        assert is_safe is False
        assert "Empty" in reason

    def test_multiple_statements(self):
        is_safe, reason = validate_read_only_sql("SELECT 1; DROP TABLE users")
        assert is_safe is False
        assert "Multiple" in reason

    def test_insert(self):
        is_safe, reason = validate_read_only_sql("INSERT INTO users (name) VALUES ('x')")
        assert is_safe is False
        assert "read-only" in reason.lower() or "INSERT" in reason

    def test_update(self):
        is_safe, reason = validate_read_only_sql("UPDATE users SET name = 'x'")
        assert is_safe is False

    def test_delete(self):
        is_safe, reason = validate_read_only_sql("DELETE FROM users WHERE id = 1")
        assert is_safe is False

    def test_drop_table(self):
        is_safe, reason = validate_read_only_sql("DROP TABLE users")
        assert is_safe is False

    def test_truncate(self):
        is_safe, reason = validate_read_only_sql("TRUNCATE users")
        assert is_safe is False

    def test_alter_table(self):
        is_safe, reason = validate_read_only_sql("ALTER TABLE users ADD COLUMN age INT")
        assert is_safe is False

    def test_create_table(self):
        is_safe, reason = validate_read_only_sql("CREATE TABLE evil (id INT)")
        assert is_safe is False

    def test_grant(self):
        is_safe, reason = validate_read_only_sql("GRANT ALL ON users TO public")
        assert is_safe is False

    def test_revoke(self):
        is_safe, reason = validate_read_only_sql("REVOKE ALL ON users FROM public")
        assert is_safe is False

    def test_vacuum(self):
        is_safe, reason = validate_read_only_sql("VACUUM users")
        assert is_safe is False

    def test_copy(self):
        is_safe, reason = validate_read_only_sql("COPY users TO '/tmp/out.csv'")
        assert is_safe is False

    def test_begin_transaction(self):
        is_safe, reason = validate_read_only_sql("BEGIN")
        assert is_safe is False

    def test_commit(self):
        is_safe, reason = validate_read_only_sql("COMMIT")
        assert is_safe is False

    def test_select_into(self):
        is_safe, reason = validate_read_only_sql("SELECT * INTO new_table FROM users")
        assert is_safe is False
        assert "SELECT INTO" in reason

    @pytest.mark.parametrize("keyword", [
        "INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE",
        "CREATE", "ALTER", "GRANT", "REVOKE",
        "CALL", "DO", "LOCK", "SET", "RESET",
    ])
    def test_blocked_keywords_in_select(self, keyword):
        """Even if wrapped in a SELECT, blocked keywords in the body should fail."""
        # This simulates an injection-style query
        query = f"SELECT 1; {keyword} something"
        is_safe, _ = validate_read_only_sql(query)
        assert is_safe is False


# ──────────────────────────────────────────────
# Edge cases / bypass attempts
# ──────────────────────────────────────────────


class TestValidateEdgeCases:
    """Edge cases and bypass attempts."""

    def test_comment_hiding_drop(self):
        """DROP hidden in a block comment should be stripped."""
        query = "SELECT /* DROP TABLE users */ 1"
        is_safe, _ = validate_read_only_sql(query)
        assert is_safe is True

    def test_line_comment_hiding_drop(self):
        """DROP in a line comment should be stripped."""
        query = "SELECT 1 -- DROP TABLE users"
        is_safe, _ = validate_read_only_sql(query)
        assert is_safe is True

    def test_drop_inside_string_literal(self):
        """DROP inside a quoted string should not trigger block."""
        query = "SELECT * FROM users WHERE name = 'DROP TABLE'"
        is_safe, _ = validate_read_only_sql(query)
        assert is_safe is True

    def test_case_insensitive_blocking(self):
        """Keywords should be blocked regardless of case."""
        is_safe, _ = validate_read_only_sql("select * from users; delete from users")
        assert is_safe is False

    def test_with_recursive(self):
        """WITH RECURSIVE should be allowed."""
        query = "WITH RECURSIVE cte AS (SELECT 1 UNION ALL SELECT n+1 FROM cte WHERE n < 10) SELECT * FROM cte"
        is_safe, _ = validate_read_only_sql(query)
        assert is_safe is True

    def test_explain_analyze_blocked(self):
        """EXPLAIN ANALYZE contains ANALYZE which is blocked."""
        is_safe, reason = validate_read_only_sql("EXPLAIN ANALYZE SELECT 1")
        assert is_safe is False
        assert "ANALYZE" in reason

