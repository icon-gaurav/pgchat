"""Session memory: persistent conversations, load/save, summarization."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from pgagent.config import SESSIONS_DIR


def _ensure_sessions_dir() -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def _session_path(name: str) -> Path:
    return SESSIONS_DIR / f"{name}.json"


def list_sessions() -> list[dict[str, Any]]:
    """List all saved sessions with metadata."""
    _ensure_sessions_dir()
    sessions = []
    for f in sorted(SESSIONS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            sessions.append({
                "name": data.get("name", f.stem),
                "created_at": data.get("created_at", ""),
                "updated_at": data.get("updated_at", ""),
                "model": data.get("model", ""),
                "db_label": data.get("db_label", ""),
                "turn_count": len([
                    m for m in data.get("messages", [])
                    if m.get("role") == "human"
                ]),
            })
        except (json.JSONDecodeError, OSError):
            continue
    return sessions


def load_session(name: str) -> Optional[dict[str, Any]]:
    """Load a session file. Returns None if not found."""
    path = _session_path(name)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_session(
    name: str,
    messages: list[BaseMessage],
    model: str = "",
    db_label: str = "",
    summary: str = "",
) -> None:
    """Save session to disk."""
    _ensure_sessions_dir()
    path = _session_path(name)

    # Load existing to preserve created_at
    existing = load_session(name)
    created_at = existing.get("created_at", "") if existing else ""
    if not created_at:
        created_at = datetime.now(timezone.utc).isoformat()

    data = {
        "name": name,
        "created_at": created_at,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "db_label": db_label,
        "summary": summary,
        "messages": [_serialize_message(m) for m in messages],
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def delete_session(name: str) -> bool:
    """Delete a session file. Returns True if deleted."""
    path = _session_path(name)
    if path.exists():
        path.unlink()
        return True
    return False


def export_session_markdown(name: str) -> Optional[str]:
    """Export a session as a markdown string."""
    session = load_session(name)
    if not session:
        return None

    lines = [
        f"# Session: {session['name']}",
        f"",
        f"- **Created:** {session.get('created_at', 'N/A')}",
        f"- **Model:** {session.get('model', 'N/A')}",
        f"- **Database:** {session.get('db_label', 'N/A')}",
        f"",
        f"---",
        f"",
    ]

    for msg in session.get("messages", []):
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if role == "human":
            lines.append(f"## 🧑 You\n\n{content}\n")
        elif role == "ai":
            if content:
                lines.append(f"## 🤖 Agent\n\n{content}\n")
        elif role == "tool":
            tool_name = msg.get("name", "tool")
            lines.append(f"*Tool `{tool_name}`:*\n```\n{content}\n```\n")

    return "\n".join(lines)


def deserialize_messages(session_data: dict[str, Any]) -> list[BaseMessage]:
    """Convert session JSON messages back to LangChain message objects."""
    messages: list[BaseMessage] = []
    for msg in session_data.get("messages", []):
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "system":
            messages.append(SystemMessage(content=content))
        elif role == "human":
            messages.append(HumanMessage(content=content))
        elif role == "ai":
            tool_calls = msg.get("tool_calls", [])
            messages.append(AIMessage(content=content, tool_calls=tool_calls))
        elif role == "tool":
            messages.append(ToolMessage(
                content=content,
                tool_call_id=msg.get("tool_call_id", ""),
                name=msg.get("name", ""),
            ))
    return messages


def _serialize_message(msg: BaseMessage) -> dict[str, Any]:
    """Convert a LangChain message to a JSON-serializable dict."""
    if isinstance(msg, SystemMessage):
        return {"role": "system", "content": _content_to_str(msg.content)}
    elif isinstance(msg, HumanMessage):
        return {"role": "human", "content": _content_to_str(msg.content)}
    elif isinstance(msg, AIMessage):
        data: dict[str, Any] = {"role": "ai", "content": _content_to_str(msg.content)}
        if msg.tool_calls:
            data["tool_calls"] = msg.tool_calls
        return data
    elif isinstance(msg, ToolMessage):
        return {
            "role": "tool",
            "content": _content_to_str(msg.content),
            "tool_call_id": getattr(msg, "tool_call_id", ""),
            "name": getattr(msg, "name", ""),
        }
    return {"role": "unknown", "content": str(msg.content)}


def _content_to_str(content: Any) -> str:
    """Normalize message content to a string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            else:
                parts.append(json.dumps(item, ensure_ascii=False, default=str))
        return "\n".join(parts)
    if content is None:
        return ""
    return str(content)


def should_summarize(messages: list[BaseMessage], max_turns: int = 20) -> bool:
    """Check if the conversation is long enough to warrant summarization."""
    human_count = sum(1 for m in messages if isinstance(m, HumanMessage))
    return human_count > max_turns


def build_summary_prompt(messages: list[BaseMessage]) -> str:
    """Build a prompt asking the LLM to summarize the conversation so far."""
    conversation = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            conversation.append(f"User: {_content_to_str(msg.content)}")
        elif isinstance(msg, AIMessage):
            content = _content_to_str(msg.content)
            if content:
                conversation.append(f"Assistant: {content}")

    convo_text = "\n".join(conversation[-40:])  # Last 40 messages max
    return (
        "Summarize the following conversation concisely. "
        "Capture the key questions asked, answers given, tables/data discussed, "
        "and any important findings. Keep it under 300 words.\n\n"
        f"{convo_text}"
    )

