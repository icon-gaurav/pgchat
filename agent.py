import warnings
import os
import ctypes
import sys
import threading
import time

from langchain_core._api.deprecation import LangChainPendingDeprecationWarning

warnings.filterwarnings(
    "ignore",
    message=r"The default value of `allowed_objects` will change in a future version\..*",
    category=LangChainPendingDeprecationWarning,
)

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_ollama import ChatOllama
from langchain_core.tools import tool
from typing import Any, cast
import json
import re
import psycopg2

AGENT_NAME = "PostgreSQL Agent"
AGENT_AUTHOR = "Gaurav (https://gauravbytes.hashnode.dev)"
SHOW_TOOL_RESPONSES = False

# PostgreSQL connection config
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "postgres",
    "user": "postgres",
    "password": "root",
}


def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def format_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            else:
                parts.append(json.dumps(item, ensure_ascii=False, default=str))
        return "\n".join(part for part in parts if part)
    if isinstance(content, dict):
        return json.dumps(content, indent=2, ensure_ascii=False, default=str)
    return str(content)


def format_tool_payload(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, ensure_ascii=False, default=str)


def normalize_sql_for_safety(query: str) -> str:
    without_block_comments = re.sub(r"/\*.*?\*/", " ", query, flags=re.S)
    without_line_comments = re.sub(r"--[^\n]*", " ", without_block_comments)
    without_single_quotes = re.sub(r"'([^']|'')*'", "''", without_line_comments)
    without_double_quotes = re.sub(r'"([^"]|"")*"', '""', without_single_quotes)
    return re.sub(r"\s+", " ", without_double_quotes).strip()


def validate_read_only_sql(query: str) -> tuple[bool, str]:
    normalized = normalize_sql_for_safety(query)
    if not normalized:
        return False, "Empty query is not allowed."

    if ";" in normalized.rstrip(";"):
        return False, "Multiple SQL statements are not allowed."

    upper_query = normalized.rstrip(";").strip().upper()
    if not upper_query.startswith(("SELECT", "WITH", "SHOW", "EXPLAIN")):
        return False, "Only read-only queries are allowed (SELECT/WITH/SHOW/EXPLAIN)."

    blocked_keywords = [
        "INSERT", "UPDATE", "DELETE", "UPSERT", "MERGE",
        "ALTER", "DROP", "TRUNCATE", "CREATE", "REPLACE",
        "GRANT", "REVOKE", "COMMENT", "RENAME",
        "VACUUM", "ANALYZE", "CLUSTER", "REINDEX", "REFRESH",
        "CALL", "DO", "COPY", "LOCK", "SET", "RESET", "DISCARD",
        "BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE",
    ]

    for keyword in blocked_keywords:
        if re.search(rf"\b{keyword}\b", upper_query):
            return False, f"Query contains blocked keyword: {keyword}."

    if re.search(r"\bSELECT\b[\s\S]*\bINTO\b", upper_query):
        return False, "SELECT INTO is not allowed because it creates tables."

    return True, ""


def print_turn_details(messages: list[BaseMessage]) -> None:
    final_response = ""
    use_color = enable_windows_ansi()

    for message in messages:
        if isinstance(message, AIMessage):
            for tool_call in message.tool_calls:
                tool_name = tool_call.get("name", "unknown_tool")
                tool_args = format_tool_payload(tool_call.get("args", {}))
                label = style_text("[TOOL CALL]", "1;35", use_color)
                name = style_text(tool_name, "1;36", use_color)
                print(f"\n{label} {name}")
                if tool_args and tool_args != "{}":
                    print(style_text(f"args: {tool_args}", "35", use_color))

            content = format_content(message.content).strip()
            if content:
                final_response = content

        elif isinstance(message, ToolMessage):
            if SHOW_TOOL_RESPONSES:
                tool_name = getattr(message, "name", None) or "tool"
                tool_output = format_content(message.content).strip() or "(no output)"
                label = style_text("[TOOL RESPONSE]", "1;30", use_color)
                name = style_text(tool_name, "1;30", use_color)
                print(f"\n{label} {name}: {tool_output}")

    if final_response:
        stream_text(final_response)
    else:
        print("\nAgent: I couldn't generate a response.")


def stream_text(text: str, delay: float = 0.01) -> None:
    print("\nAgent: ", end="", flush=True)
    for ch in text:
        print(ch, end="", flush=True)
        time.sleep(delay)
    print()


def waiting_animation(stop_event: threading.Event, message: str = "Agent is thinking") -> None:
    frames = ["|", "/", "-", "\\"]
    idx = 0
    while not stop_event.is_set():
        frame = frames[idx % len(frames)]
        sys.stdout.write(f"\r{message} {frame}")
        sys.stdout.flush()
        idx += 1
        time.sleep(0.1)
    sys.stdout.write("\r" + " " * (len(message) + 4) + "\r")
    sys.stdout.flush()


def enable_windows_ansi() -> bool:
    if os.name != "nt":
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        get_std_handle = getattr(kernel32, "GetStdHandle")
        get_console_mode = getattr(kernel32, "GetConsoleMode")
        set_console_mode = getattr(kernel32, "SetConsoleMode")

        handle = get_std_handle(-11)
        mode = ctypes.c_uint32()
        if get_console_mode(handle, ctypes.byref(mode)) == 0:
            return False
        if set_console_mode(handle, mode.value | 0x0004) == 0:
            return False
        return True
    except Exception:
        return False


def style_text(text: str, color_code: str, use_color: bool) -> str:
    if not use_color:
        return text
    return f"\033[{color_code}m{text}\033[0m"


def print_startup_banner() -> None:
    use_color = enable_windows_ansi()
    width = 50
    border = "=" * width
    title = f" {AGENT_NAME} "
    title_line = title.center(width, "=")

    print(style_text(border, "36", use_color))
    print(style_text(title_line, "1;36", use_color))
    print(style_text(f"Author: {AGENT_AUTHOR}", "33", use_color))
    print(style_text("Type 'exit' to quit", "90", use_color))
    print(style_text(border, "36", use_color))


@tool
def list_tables() -> str:
    """List all tables in the database."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
        """)
        tables = [row[0] for row in cur.fetchall()]
        return f"Tables: {', '.join(tables)}" if tables else "No tables found."
    finally:
        conn.close()


@tool
def get_table_schema(table_name: str) -> str:
    """Get the schema (columns and types) of a specific table."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position
        """, (table_name,))
        columns = cur.fetchall()
        if not columns:
            return f"Table '{table_name}' not found."
        schema = "\n".join([f"  {col[0]} ({col[1]}, nullable={col[2]})" for col in columns])
        return f"Schema for '{table_name}':\n{schema}"
    finally:
        conn.close()


@tool
def execute_sql(query: str) -> str:
    """Execute a SQL query against the PostgreSQL database and return results. Use this for SELECT queries."""
    is_safe, reason = validate_read_only_sql(query)
    if not is_safe:
        return f"Safety Guard: Blocked query. {reason}"

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(query)
        if cur.description:
            columns = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
            if not rows:
                return "Query returned no results."
            result = " | ".join(columns) + "\n"
            result += "\n".join([" | ".join(str(v) for v in row) for row in rows[:50]])
            if len(rows) > 50:
                result += f"\n... ({len(rows)} total rows)"
            return result
        else:
            conn.commit()
            return f"Query executed successfully. Rows affected: {cur.rowcount}"
    except Exception as e:
        conn.rollback()
        return f"SQL Error: {e}"
    finally:
        conn.close()


# Initialize the LLM using Ollama
llm = ChatOllama(model="qwen2.5:7b", temperature=0)

# Create the agent with database tools
tools = [list_tables, get_table_schema, execute_sql]
agent = create_agent(llm, tools)

# Interactive loop
print_startup_banner()

chat_history: list[BaseMessage] = []

while True:
    user_input = input("\nYou: ").strip()
    if user_input.lower() in ("exit", "quit"):
        print("Goodbye!")
        break
    if not user_input:
        continue

    pending_messages = [*chat_history, HumanMessage(content=user_input)]

    wait_stop = threading.Event()
    spinner_thread = threading.Thread(target=waiting_animation, args=(wait_stop,), daemon=True)
    spinner_thread.start()
    try:
        response = agent.invoke(cast(Any, {"messages": pending_messages}))
    finally:
        wait_stop.set()
        spinner_thread.join(timeout=1)

    response_messages = response.get("messages", [])

    if not response_messages:
        print("\nAgent: I couldn't generate a response.")
        continue

    new_messages = response_messages[len(pending_messages):] if len(response_messages) >= len(pending_messages) else response_messages
    chat_history = list(response_messages)
    print_turn_details(new_messages)
