"""Agent setup: LLM initialization, tool registration, invocation."""

import warnings
from typing import Any, Optional, cast

from langchain_core._api.deprecation import LangChainPendingDeprecationWarning

warnings.filterwarnings(
    "ignore",
    message=r"The default value of `allowed_objects` will change in a future version\..*",
    category=LangChainPendingDeprecationWarning,
)

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage

from pgagent.config import Config
from pgagent.tools import ALL_TOOLS

SYSTEM_PROMPT = """You are PGAgent, an expert PostgreSQL database assistant. You have access to tools to inspect and query the connected database.

Guidelines:
- Always explore the schema before writing queries. Use list_tables and get_table_schema to understand the structure first.
- Prefer short, precise answers. When showing data, summarize it unless the user asks for raw output.
- Never guess table or column names — always verify with tools first.
- When you write SQL, explain what it does briefly.
- If a query fails, analyze the error and suggest fixes.
- Use get_table_sample to preview data when helpful.
- Use search_schema when the user asks "which table has X column?"

{db_context}"""


def build_system_message(db_context: str = "") -> SystemMessage:
    """Build the system message with optional database context."""
    context_section = ""
    if db_context:
        context_section = f"\nKnown tables in this database: {db_context}"
    return SystemMessage(content=SYSTEM_PROMPT.format(db_context=context_section))


def create_llm(config: Config):
    """Create the appropriate LLM based on config."""
    if config.backend == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(
                model=config.model,
                api_key=config.anthropic_api_key,
                temperature=0,
                max_tokens=4096,
            )
        except ImportError:
            raise RuntimeError(
                "langchain-anthropic not installed. Run: pip install langchain-anthropic"
            )
    else:
        from langchain_ollama import ChatOllama
        return ChatOllama(model=config.model, temperature=0)


def create_pg_agent(config: Config):
    """Create and return the LangChain agent."""
    llm = create_llm(config)
    return create_agent(llm, ALL_TOOLS)


def invoke_agent(
    agent: Any,
    messages: list[BaseMessage],
    system_message: SystemMessage,
) -> list[BaseMessage]:
    """Invoke the agent and return the new messages from this turn."""
    # Prepend system message
    full_messages = [system_message] + messages
    response = agent.invoke(cast(Any, {"messages": full_messages}))
    response_messages = response.get("messages", [])

    # Extract only the new messages (after what we sent)
    if len(response_messages) > len(full_messages):
        return response_messages[len(full_messages):]
    return response_messages


def extract_response_text(messages: list[BaseMessage]) -> str:
    """Extract the final text response from agent messages."""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            content = msg.content
            if isinstance(content, str) and content.strip():
                return content.strip()
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict) and "text" in item:
                        parts.append(str(item["text"]))
                    elif isinstance(item, str):
                        parts.append(item)
                text = "\n".join(parts).strip()
                if text:
                    return text
    return ""


def extract_tool_calls(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    """Extract tool call info from messages for display."""
    calls = []
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                calls.append({
                    "name": tc.get("name", "unknown"),
                    "args": tc.get("args", {}),
                })
    return calls


def extract_tool_responses(messages: list[BaseMessage]) -> list[dict[str, str]]:
    """Extract tool responses from messages."""
    responses = []
    for msg in messages:
        if isinstance(msg, ToolMessage):
            responses.append({
                "name": getattr(msg, "name", "tool"),
                "content": msg.content if isinstance(msg.content, str) else str(msg.content),
            })
    return responses


