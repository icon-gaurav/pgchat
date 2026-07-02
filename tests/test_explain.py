"""Tests for pgchat.explain — explain-before-execute module."""

import pytest
from unittest.mock import patch, MagicMock

from pgchat.explain import explain_query, _EXPLAIN_SYSTEM_PROMPT


class TestExplainQuery:
    """Test the explain_query function."""

    def test_returns_explanation_on_success(self):
        """Should return explanation text when LLM call succeeds."""
        mock_response = MagicMock()
        mock_response.content = "This query fetches all customers ordered by name."

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = mock_response

        with patch("pgchat.explain._get_explain_llm", return_value=mock_llm):
            result = explain_query(
                sql_query="SELECT * FROM customers ORDER BY name",
                user_question="show me all customers",
                schema_context="TABLE: customers\n  - id (integer)\n  - name (varchar)",
            )

        assert result == "This query fetches all customers ordered by name."
        mock_llm.invoke.assert_called_once()

    def test_returns_none_on_empty_query(self):
        """Should return None for empty queries without calling LLM."""
        result = explain_query(sql_query="", user_question="test", schema_context="")
        assert result is None

    def test_returns_none_on_whitespace_query(self):
        """Should return None for whitespace-only queries."""
        result = explain_query(sql_query="   ", user_question="test", schema_context="")
        assert result is None

    def test_returns_none_when_llm_unavailable(self):
        """Should return None gracefully when LLM creation fails."""
        with patch("pgchat.explain._get_explain_llm", return_value=None):
            result = explain_query(
                sql_query="SELECT 1",
                user_question="test",
                schema_context="",
            )
        assert result is None

    def test_returns_none_on_llm_exception(self):
        """Should return None when LLM throws an exception (non-blocking)."""
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = Exception("LLM timeout")

        with patch("pgchat.explain._get_explain_llm", return_value=mock_llm):
            result = explain_query(
                sql_query="SELECT * FROM users",
                user_question="show users",
                schema_context="TABLE: users",
            )
        assert result is None

    def test_returns_none_on_empty_response(self):
        """Should return None when LLM returns empty content."""
        mock_response = MagicMock()
        mock_response.content = ""

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = mock_response

        with patch("pgchat.explain._get_explain_llm", return_value=mock_llm):
            result = explain_query(
                sql_query="SELECT 1",
                user_question="test",
                schema_context="",
            )
        assert result is None

    def test_handles_list_content_response(self):
        """Should handle LLM returning list content format."""
        mock_response = MagicMock()
        mock_response.content = [{"text": "This counts"}, {"text": "all orders."}]

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = mock_response

        with patch("pgchat.explain._get_explain_llm", return_value=mock_llm):
            result = explain_query(
                sql_query="SELECT count(*) FROM orders",
                user_question="how many orders",
                schema_context="TABLE: orders",
            )
        assert result == "This counts all orders."

    def test_truncates_long_schema_context(self):
        """Should truncate schema context to 2000 chars to avoid token bloat."""
        long_schema = "x" * 5000
        mock_response = MagicMock()
        mock_response.content = "Short explanation."

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = mock_response

        with patch("pgchat.explain._get_explain_llm", return_value=mock_llm):
            result = explain_query(
                sql_query="SELECT 1",
                user_question="test",
                schema_context=long_schema,
            )

        # Check that the prompt was called with truncated schema
        call_args = mock_llm.invoke.call_args[0][0]
        user_msg_content = call_args[1].content
        assert "xxxxx" in user_msg_content
        assert len(user_msg_content) < 5000  # Truncated
        assert result == "Short explanation."

    def test_passes_config_to_llm_getter(self):
        """Should pass config through to _get_explain_llm."""
        mock_config = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Explanation."

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = mock_response

        with patch("pgchat.explain._get_explain_llm", return_value=mock_llm) as mock_get:
            explain_query(
                sql_query="SELECT 1",
                user_question="test",
                schema_context="",
                config=mock_config,
            )
        mock_get.assert_called_once_with(mock_config)

    def test_uses_correct_system_prompt(self):
        """Should use the focused explain system prompt."""
        mock_response = MagicMock()
        mock_response.content = "Explanation."

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = mock_response

        with patch("pgchat.explain._get_explain_llm", return_value=mock_llm):
            explain_query(
                sql_query="SELECT * FROM users WHERE active = true",
                user_question="show active users",
                schema_context="TABLE: users",
            )

        call_args = mock_llm.invoke.call_args[0][0]
        system_msg = call_args[0]
        assert "SQL explanation assistant" in system_msg.content
        assert "2-4 sentences" in system_msg.content

    def test_user_prompt_contains_query_and_question(self):
        """Should include the SQL query and user question in the prompt."""
        mock_response = MagicMock()
        mock_response.content = "Explanation."

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = mock_response

        with patch("pgchat.explain._get_explain_llm", return_value=mock_llm):
            explain_query(
                sql_query="SELECT email FROM users WHERE role = 'admin'",
                user_question="find admin emails",
                schema_context="TABLE: users (id, email, role)",
            )

        call_args = mock_llm.invoke.call_args[0][0]
        user_msg = call_args[1].content
        assert "SELECT email FROM users" in user_msg
        assert "find admin emails" in user_msg
        assert "TABLE: users" in user_msg


class TestExplainInRunQuery:
    """Test that explain is wired into run_query correctly."""

    @patch("pgchat.tools.execute_sql")
    @patch("pgchat.tools.logger")
    def test_explain_failure_does_not_block_execution(self, mock_logger, mock_exec):
        """Explain failure must not prevent SQL execution."""
        from pgchat.tools import set_explain_context

        mock_exec.return_value = MagicMock(
            columns=["id"], rows=[(1,)], row_count=1
        )
        set_explain_context(enabled=True, user_question="test", schema_context="")

        # Patch explain_query to raise, patch UI to avoid output
        with patch("pgchat.explain.explain_query", side_effect=Exception("LLM died")):
            with patch("pgchat.ui.print_query_explanation"):
                from pgchat.tools import run_query
                result = run_query.invoke({"query": "SELECT 1"})

        assert "id" in result
        mock_exec.assert_called_once()

    @patch("pgchat.tools.execute_sql")
    def test_explain_disabled_skips_llm_call(self, mock_exec):
        """When explain is disabled, should not call explain_query."""
        from pgchat.tools import set_explain_context

        mock_exec.return_value = MagicMock(
            columns=["n"], rows=[(42,)], row_count=1
        )
        set_explain_context(enabled=False, user_question="test", schema_context="")

        with patch("pgchat.explain.explain_query") as mock_explain:
            with patch("pgchat.ui.print_query_explanation"):
                from pgchat.tools import run_query
                result = run_query.invoke({"query": "SELECT 42"})

        mock_explain.assert_not_called()
        assert "42" in result


