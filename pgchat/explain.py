"""Explain-before-execute: generates plain-English explanations of SQL queries.

This module provides a lightweight LLM call that produces a 2-4 sentence
explanation of what a SQL query does, intended for a developer audience.
The explanation is passive (no confirmation gate) and failure-tolerant.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Focused system prompt — kept short to minimize token usage
_EXPLAIN_SYSTEM_PROMPT = """You are a SQL explanation assistant. Given a SQL query, the user's original question, and the database schema, produce a concise plain-English explanation (2-4 sentences) of what the query does.

Rules:
- Describe what tables and columns are involved, what filtering/joining/aggregation is happening, and what kind of result to expect.
- Write for a developer audience.
- Do NOT restate SQL syntax. Describe intent and effect.
- Be concise: max 4 sentences."""

_EXPLAIN_USER_TEMPLATE = """User's question: {user_question}

SQL query:
{sql_query}

Schema context:
{schema_context}

Explain what this query does in plain English (2-4 sentences):"""


def explain_query(
    sql_query: str,
    user_question: str,
    schema_context: str,
    config: Optional[object] = None,
) -> Optional[str]:
    """
    Generate a plain-English explanation of a SQL query using the LLM.

    Args:
        sql_query: The SQL query to explain.
        user_question: The original user question that led to this query.
        schema_context: The cached schema text (from SchemaCache.to_system_prompt_text()).
        config: The Config object for LLM initialization.

    Returns:
        A short explanation string, or None if the call fails.
        Failures are logged but never raised — this is a non-blocking step.
    """
    if not sql_query or not sql_query.strip():
        return None

    try:
        llm = _get_explain_llm(config)
        if llm is None:
            return None

        user_prompt = _EXPLAIN_USER_TEMPLATE.format(
            user_question=user_question or "(no specific question)",
            sql_query=sql_query.strip(),
            schema_context=schema_context[:2000] if schema_context else "(schema not available)",
        )

        from langchain_core.messages import SystemMessage, HumanMessage

        messages = [
            SystemMessage(content=_EXPLAIN_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]

        # Invoke with low max_tokens to keep it fast
        response = llm.invoke(messages)

        if response and hasattr(response, "content"):
            content = response.content
            if isinstance(content, str) and content.strip():
                return content.strip()
            if isinstance(content, list):
                parts = [
                    item.get("text", "") if isinstance(item, dict) else str(item)
                    for item in content
                ]
                text = " ".join(parts).strip()
                if text:
                    return text

        return None

    except Exception as e:
        logger.warning(f"explain_query failed (non-blocking): {e}")
        return None


def _get_explain_llm(config: Optional[object]):
    """
    Create a lightweight LLM instance for explanations.
    Uses the same backend/model as the main agent but with capped tokens.
    """
    try:
        if config is None:
            from pgchat.config import load_config
            config = load_config()

        # Access config attributes
        backend = getattr(config, "backend", "ollama")
        model = getattr(config, "model", "qwen2.5:7b")
        api_key = getattr(config, "anthropic_api_key", None)

        if backend == "anthropic":
            try:
                from langchain_anthropic import ChatAnthropic
                return ChatAnthropic(
                    model=model,
                    api_key=api_key,
                    temperature=0,
                    max_tokens=200,  # Capped for speed
                )
            except ImportError:
                logger.warning("langchain-anthropic not available for explain step")
                return None
        else:
            from langchain_ollama import ChatOllama
            return ChatOllama(
                model=model,
                temperature=0,
                num_predict=200,  # Ollama's equivalent of max_tokens
            )

    except Exception as e:
        logger.warning(f"Failed to create explain LLM: {e}")
        return None

