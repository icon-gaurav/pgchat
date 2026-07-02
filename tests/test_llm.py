"""Tests for LLM connection testing in pgchat.agent.check_llm_connection."""

import pytest
from unittest.mock import patch, MagicMock

from pgchat.agent import check_llm_connection
from pgchat.config import Config


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────


@pytest.fixture
def ollama_config():
    """Config pointing at a local Ollama backend."""
    return Config(backend="ollama", model="qwen2.5:7b")


@pytest.fixture
def anthropic_config():
    """Config pointing at the Anthropic backend."""
    return Config(
        backend="anthropic",
        model="claude-haiku-3",
        anthropic_api_key="sk-ant-test-key",
    )


# ──────────────────────────────────────────────
# Successful connection
# ──────────────────────────────────────────────


class TestLLMConnectionSuccess:
    def test_ollama_success(self, ollama_config):
        mock_response = MagicMock()
        mock_response.content = "OK"
        with patch("pgchat.agent.create_llm") as mock_create:
            mock_create.return_value.invoke.return_value = mock_response
            success, msg = check_llm_connection(ollama_config)
        assert success is True
        assert "ollama" in msg
        assert "qwen2.5:7b" in msg

    def test_anthropic_success(self, anthropic_config):
        mock_response = MagicMock()
        mock_response.content = "OK"
        with patch("pgchat.agent.create_llm") as mock_create:
            mock_create.return_value.invoke.return_value = mock_response
            success, msg = check_llm_connection(anthropic_config)
        assert success is True
        assert "anthropic" in msg
        assert "claude-haiku-3" in msg

    def test_response_with_whitespace(self, ollama_config):
        mock_response = MagicMock()
        mock_response.content = "  OK  \n"
        with patch("pgchat.agent.create_llm") as mock_create:
            mock_create.return_value.invoke.return_value = mock_response
            success, msg = check_llm_connection(ollama_config)
        assert success is True


# ──────────────────────────────────────────────
# Empty response
# ──────────────────────────────────────────────


class TestLLMConnectionEmptyResponse:
    def test_empty_content(self, ollama_config):
        mock_response = MagicMock()
        mock_response.content = ""
        with patch("pgchat.agent.create_llm") as mock_create:
            mock_create.return_value.invoke.return_value = mock_response
            success, msg = check_llm_connection(ollama_config)
        assert success is False
        assert "empty response" in msg

    def test_whitespace_only_content(self, ollama_config):
        mock_response = MagicMock()
        mock_response.content = "   \n\t  "
        with patch("pgchat.agent.create_llm") as mock_create:
            mock_create.return_value.invoke.return_value = mock_response
            success, msg = check_llm_connection(ollama_config)
        assert success is False
        assert "empty response" in msg

    def test_none_content(self, ollama_config):
        mock_response = MagicMock()
        mock_response.content = None
        with patch("pgchat.agent.create_llm") as mock_create:
            mock_create.return_value.invoke.return_value = mock_response
            success, msg = check_llm_connection(ollama_config)
        assert success is False


# ──────────────────────────────────────────────
# Ollama-specific failures
# ──────────────────────────────────────────────


class TestOllamaConnectionErrors:
    def test_ollama_not_running(self, ollama_config):
        with patch("pgchat.agent.create_llm") as mock_create:
            mock_create.return_value.invoke.side_effect = Exception(
                "Connection refused: Ollama server not running"
            )
            success, msg = check_llm_connection(ollama_config)
        assert success is False
        assert "Cannot connect to Ollama" in msg
        assert "ollama serve" in msg

    def test_ollama_connect_error(self, ollama_config):
        with patch("pgchat.agent.create_llm") as mock_create:
            mock_create.return_value.invoke.side_effect = Exception(
                "ConnectError: Failed to connect to localhost:11434"
            )
            success, msg = check_llm_connection(ollama_config)
        assert success is False
        assert "Cannot connect to Ollama" in msg
        assert "ollama serve" in msg

    def test_ollama_model_not_found(self, ollama_config):
        with patch("pgchat.agent.create_llm") as mock_create:
            mock_create.return_value.invoke.side_effect = Exception(
                "model 'qwen2.5:7b' not found, try pulling it first"
            )
            success, msg = check_llm_connection(ollama_config)
        assert success is False
        assert "not found" in msg
        assert "ollama pull" in msg

    def test_ollama_generic_error(self, ollama_config):
        with patch("pgchat.agent.create_llm") as mock_create:
            mock_create.return_value.invoke.side_effect = Exception("timeout")
            success, msg = check_llm_connection(ollama_config)
        assert success is False
        assert "LLM connection failed" in msg
        assert "timeout" in msg


# ──────────────────────────────────────────────
# Anthropic-specific failures
# ──────────────────────────────────────────────


class TestAnthropicConnectionErrors:
    def test_anthropic_auth_failure_401(self, anthropic_config):
        with patch("pgchat.agent.create_llm") as mock_create:
            mock_create.return_value.invoke.side_effect = Exception(
                "Error code: 401 - Invalid API key"
            )
            success, msg = check_llm_connection(anthropic_config)
        assert success is False
        assert "authentication failed" in msg
        assert "ANTHROPIC_API_KEY" in msg

    def test_anthropic_api_key_error(self, anthropic_config):
        with patch("pgchat.agent.create_llm") as mock_create:
            mock_create.return_value.invoke.side_effect = Exception(
                "api_key is required but was not provided"
            )
            success, msg = check_llm_connection(anthropic_config)
        assert success is False
        assert "authentication failed" in msg

    def test_anthropic_generic_error(self, anthropic_config):
        with patch("pgchat.agent.create_llm") as mock_create:
            mock_create.return_value.invoke.side_effect = Exception("rate limit exceeded")
            success, msg = check_llm_connection(anthropic_config)
        assert success is False
        assert "LLM connection failed" in msg
        assert "rate limit exceeded" in msg


# ──────────────────────────────────────────────
# Import errors
# ──────────────────────────────────────────────


class TestLLMImportErrors:
    def test_missing_dependency(self, anthropic_config):
        with patch("pgchat.agent.create_llm") as mock_create:
            mock_create.side_effect = ImportError(
                "No module named 'langchain_anthropic'"
            )
            success, msg = check_llm_connection(anthropic_config)
        assert success is False
        assert "Missing dependency" in msg
        assert "langchain_anthropic" in msg


# ──────────────────────────────────────────────
# Edge cases
# ──────────────────────────────────────────────


class TestLLMConnectionEdgeCases:
    def test_response_without_content_attr(self, ollama_config):
        """If response doesn't have .content, falls back to str()."""

        class FakeResponse:
            def __str__(self):
                return "OK response"

        with patch("pgchat.agent.create_llm") as mock_create:
            mock_create.return_value.invoke.return_value = FakeResponse()
            success, msg = check_llm_connection(ollama_config)
        assert success is True

    def test_create_llm_raises_runtime_error(self, anthropic_config):
        with patch("pgchat.agent.create_llm") as mock_create:
            mock_create.side_effect = RuntimeError(
                "langchain-anthropic not installed. Run: pip install langchain-anthropic"
            )
            success, msg = check_llm_connection(anthropic_config)
        assert success is False
        assert "LLM connection failed" in msg
