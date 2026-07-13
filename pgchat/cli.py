"""Click-based CLI entry point for PGChat."""

import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import click

from pgchat import __version__
from pgchat.config import (
    Config,
    ENV_FILE,
    load_config,
    run_config_wizard,
)
from pgchat.db import init_db, test_connection
from pgchat.schema_cache import SchemaCache, build_schema_cache
from pgchat.memory import (
    build_summary_prompt,
    delete_session,
    deserialize_messages,
    export_session_markdown,
    list_sessions,
    load_session,
    save_session,
    should_summarize,
)
from pgchat.ui import (
    console,
    get_user_input,
    print_agent_response,
    print_banner,
    print_error,
    print_help,
    print_history,
    print_info,
    print_sessions_table,
    print_success,
    print_tool_call,
    print_tool_response,
    print_warning,
)
from pgchat.tools import set_explain_context

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage


@click.group(invoke_without_command=True)
@click.option("--config", "run_config", is_flag=True, help="Run connection setup wizard.")
@click.option("--db-url", default=None, help="PostgreSQL connection URL.")
@click.option("--model", default=None, help="LLM model name override.")
@click.option("--backend", default=None, type=click.Choice(["ollama", "anthropic"]), help="LLM backend.")
@click.option("--session", "session_name", default=None, help="Start with a named session.")
@click.option("--show-tool-calls", is_flag=True, help="Show raw tool call/response details.")
@click.version_option(__version__, prog_name="pgchat")
@click.pass_context
def main(ctx, run_config, db_url, model, backend, session_name, show_tool_calls):
    """PGChat - Chat with your PostgreSQL database using natural language."""
    ctx.ensure_object(dict)

    if run_config:
        run_config_wizard()
        if not ctx.invoked_subcommand:
            return

    if ctx.invoked_subcommand:
        ctx.obj["db_url"] = db_url
        ctx.obj["model"] = model
        ctx.obj["backend"] = backend
        return

    # Main interactive mode
    cfg = load_config(
        db_url=db_url,
        model=model,
        backend=backend,
        show_tool_calls=show_tool_calls,
        session_name=session_name,
    )

    # Check if config exists, if not run wizard
    if not ENV_FILE.exists() and not db_url:
        console.print("[yellow]No configuration found. Starting setup wizard...[/yellow]\n")
        run_config_wizard()
        cfg = load_config(
            db_url=db_url,
            model=model,
            backend=backend,
            show_tool_calls=show_tool_calls,
            session_name=session_name,
        )

    # Initialize database
    init_db(cfg)

    # Test connection
    with console.status("[cyan]Testing database connection...[/cyan]"):
        success, msg = test_connection()

    if not success:
        print_error(f"Connection failed: {msg}")
        console.print("[dim]Run pgchat --config to reconfigure.[/dim]")
        sys.exit(1)

    print_success(f"Connected to PostgreSQL")
    console.print(f"  [dim]{msg.split(',')[0] if ',' in msg else msg[:60]}[/dim]")

    # Load schema cache — fetched ONCE on startup
    schema_cache: Optional[SchemaCache] = None
    with console.status("[cyan]📦 Loading schema...[/cyan]"):
        try:
            schema_cache = build_schema_cache()
        except Exception as e:
            schema_cache = None

    if schema_cache and schema_cache.tables:
        print_success(f"Schema loaded — {len(schema_cache.tables)} tables found")
    elif schema_cache:
        print_warning("Schema loaded but no tables found in public schema")
    else:
        print_warning("Could not load schema — agent will discover tables via tools")

    # Session setup
    current_session = _resolve_session(cfg, session_name)

    # Print banner
    print_banner(
        db_label=cfg.get_db_label(),
        model=cfg.model,
        session_name=current_session,
        backend=cfg.backend,
    )

    # Start the chat loop
    _chat_loop(cfg, schema_cache, current_session)


@main.group()
@click.pass_context
def sessions(ctx):
    """Manage saved sessions."""
    pass


@sessions.command("list")
def sessions_list():
    """List all saved sessions."""
    all_sessions = list_sessions()
    print_sessions_table(all_sessions)


@sessions.command("delete")
@click.argument("name")
def sessions_delete(name):
    """Delete a saved session."""
    if delete_session(name):
        print_success(f"Session '{name}' deleted.")
    else:
        print_error(f"Session '{name}' not found.")


@sessions.command("export")
@click.argument("name")
def sessions_export(name):
    """Export a session as markdown."""
    md = export_session_markdown(name)
    if md:
        out_path = Path(f"{name}_export.md")
        out_path.write_text(md, encoding="utf-8")
        print_success(f"Exported to {out_path.absolute()}")
    else:
        print_error(f"Session '{name}' not found.")


def _resolve_session(cfg: Config, session_name: Optional[str]) -> str:
    """Determine which session to use."""
    if session_name:
        return session_name

    all_sessions = list_sessions()
    if not all_sessions:
        name = _generate_session_name()
        print_info(f"Starting new session: {name}")
        return name

    # Try interactive picker, fall back to text-based selection
    if sys.stdin.isatty():
        try:
            return _pick_session_interactive(all_sessions)
        except Exception:
            pass  # Fall through to text-based fallback

    return _pick_session_text(all_sessions)


def _format_session_choice(session: dict) -> str:
    """Build a human-readable label for a session in the picker."""
    name = session.get("name", "unknown")

    # Timestamp
    updated = session.get("updated_at", "")
    time_label = ""
    if updated:
        try:
            dt = datetime.fromisoformat(updated)
            time_label = dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            time_label = updated[:16]

    # Description: prefer summary, then first question, then nothing
    desc = ""
    summary = session.get("summary", "")
    first_q = session.get("first_question", "")
    if summary:
        desc = summary[:60] + ("…" if len(summary) > 60 else "")
    elif first_q:
        desc = first_q[:60] + ("…" if len(first_q) > 60 else "")

    turns = session.get("turn_count", 0)
    parts = [name]
    if time_label:
        parts.append(time_label)
    if desc:
        parts.append(f"'{desc}'")
    parts.append(f"{turns} turn{'s' if turns != 1 else ''}")
    return "  —  ".join(parts)


def _pick_session_interactive(all_sessions: list[dict]) -> str:
    """Arrow-key navigable session picker using questionary."""
    import questionary

    NEW_SESSION_LABEL = "✨ Start new session"
    choices = [NEW_SESSION_LABEL]
    label_to_name: dict[str, str] = {}

    for s in all_sessions:
        label = _format_session_choice(s)
        choices.append(label)
        label_to_name[label] = s["name"]

    console.print()
    answer = questionary.select(
        "Select a session:",
        choices=choices,
        use_arrow_keys=True,
        use_jk_keys=False,
    ).ask()

    if answer is None:
        # User pressed Ctrl+C / Esc
        console.print("\n[dim]Cancelled. Goodbye! 👋[/dim]")
        sys.exit(0)

    if answer == NEW_SESSION_LABEL:
        name = _generate_session_name()
        print_info(f"Starting new session: {name}")
        return name

    session_name = label_to_name[answer]
    print_info(f"Resuming session: {session_name}")
    return session_name


def _pick_session_text(all_sessions: list[dict]) -> str:
    """Text-based fallback for non-interactive terminals."""
    console.print("\n[bold]Session Options:[/bold]")
    console.print("  [cyan][N][/cyan] New session")
    console.print("  [cyan][L][/cyan] List & resume a session")
    console.print("  [cyan]Or type a session name to resume[/cyan]\n")

    choice = console.input("[bold]Choose: [/bold]").strip()

    if choice.upper() == "N" or choice == "":
        name = _generate_session_name()
        print_info(f"Starting new session: {name}")
        return name
    elif choice.upper() == "L":
        print_sessions_table(all_sessions)
        name = console.input("\n[bold]Session name to resume: [/bold]").strip()
        if name and load_session(name):
            print_info(f"Resuming session: {name}")
            return name
        else:
            name = _generate_session_name()
            print_info(f"Session not found. Starting new: {name}")
            return name
    else:
        if load_session(choice):
            print_info(f"Resuming session: {choice}")
            return choice
        name = choice
        print_info(f"Starting new session: {name}")
        return name


def _generate_session_name() -> str:
    """Generate a timestamped session name."""
    return datetime.now().strftime("session_%Y%m%d_%H%M%S")


def _chat_loop(cfg: Config, schema_cache: Optional[SchemaCache], session_name: str) -> None:
    """Main interactive chat loop."""
    from pgchat.agent import (
        build_system_message,
        create_pg_agent,
        extract_response_text,
        extract_tool_calls,
        extract_tool_responses,
        invoke_agent,
    )

    # Create agent
    with console.status("[cyan]Initializing AI agent...[/cyan]"):
        agent = create_pg_agent(cfg)

    # Build system message with schema cache injected
    system_msg = build_system_message(schema_cache)

    # Load existing session messages or start fresh
    session_data = load_session(session_name)
    if session_data:
        chat_history: list[BaseMessage] = deserialize_messages(session_data)
        summary = session_data.get("summary", "")
        # If session has a cached schema and we didn't load one fresh, use it
        if not schema_cache and "schema_cache" in session_data:
            schema_cache = SchemaCache.from_dict(session_data["schema_cache"])
            system_msg = build_system_message(schema_cache)
            console.print(f"[dim]Loaded schema from session cache.[/dim]")
        if summary:
            console.print(f"[dim]Session has a summary from previous turns.[/dim]")
    else:
        chat_history = []
        summary = ""

    while True:
        user_input = get_user_input()

        if not user_input:
            continue

        # Handle exit
        if user_input.lower() in ("exit", "quit"):
            save_session(
                session_name, chat_history, cfg.model, cfg.get_db_label(),
                summary, schema_cache,
            )
            console.print("\n[dim]Session saved. Goodbye! 👋[/dim]")
            break

        # Handle slash commands
        if user_input.startswith("/"):
            result = _handle_command(
                user_input, cfg, session_name, chat_history, summary, schema_cache
            )
            if isinstance(result, dict):
                # Command returned updated state
                if "session_name" in result:
                    session_name = result["session_name"]
                if "chat_history" in result:
                    chat_history = result["chat_history"]
                if "summary" in result:
                    summary = result["summary"]
                if "schema_cache" in result:
                    schema_cache = result["schema_cache"]
                    system_msg = build_system_message(schema_cache)
                if result.get("break"):
                    break
            continue

        # Add user message
        chat_history.append(HumanMessage(content=user_input))

        # Set explain context for this turn (used by run_query tool)
        schema_text = schema_cache.to_system_prompt_text() if schema_cache else ""
        set_explain_context(
            enabled=cfg.explain_queries,
            user_question=user_input,
            schema_context=schema_text,
            config=cfg,
        )

        # Invoke agent with spinner
        try:
            with console.status("[cyan]Thinking...[/cyan]", spinner="dots"):
                new_messages = invoke_agent(agent, chat_history, system_msg)
        except Exception as e:
            print_error(f"Agent error: {e}")
            chat_history.pop()  # Remove failed user message
            continue

        # Display tool calls
        tool_calls = extract_tool_calls(new_messages)
        for tc in tool_calls:
            print_tool_call(tc["name"], tc["args"])

        # Display tool responses if verbose
        if cfg.show_tool_calls:
            tool_responses = extract_tool_responses(new_messages)
            for tr in tool_responses:
                print_tool_response(tr["name"], tr["content"])

        # Display final response
        response_text = extract_response_text(new_messages)
        if response_text:
            print_agent_response(response_text)
        else:
            console.print("[dim]Agent completed without a text response.[/dim]")

        # Append new messages to history
        chat_history.extend(new_messages)

        # Auto-save (includes schema cache)
        save_session(
            session_name, chat_history, cfg.model, cfg.get_db_label(),
            summary, schema_cache,
        )

        # Check if summarization is needed
        if should_summarize(chat_history):
            _do_summarize(agent, system_msg, chat_history, session_name, cfg, summary, schema_cache)


def _handle_command(
    command: str,
    cfg: Config,
    session_name: str,
    chat_history: list[BaseMessage],
    summary: str,
    schema_cache: Optional[SchemaCache],
) -> Optional[dict]:
    """Handle slash commands. Returns dict with state changes or None."""
    parts = command.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd == "/help":
        print_help()
    elif cmd == "/sessions":
        all_sessions = list_sessions()
        print_sessions_table(all_sessions)
    elif cmd == "/new":
        return {
            "session_name": _generate_session_name(),
            "chat_history": [],
            "summary": "",
        }
    elif cmd == "/resume":
        if not arg:
            # Interactive session picker
            resume_sessions = list_sessions()
            if not resume_sessions:
                console.print("[yellow]No saved sessions to resume.[/yellow]")
                return None
            try:
                if sys.stdin.isatty():
                    picked = _pick_session_interactive(resume_sessions)
                else:
                    console.print("[yellow]Usage: /resume <session_name>[/yellow]")
                    return None
            except SystemExit:
                return None
            except Exception:
                console.print("[yellow]Usage: /resume <session_name>[/yellow]")
                return None
            arg = picked
        session_data = load_session(arg)
        if session_data:
            new_history = deserialize_messages(session_data)
            new_summary = session_data.get("summary", "")
            result: dict = {
                "session_name": arg,
                "chat_history": new_history,
                "summary": new_summary,
            }
            # Load schema from resumed session if available
            if "schema_cache" in session_data:
                result["schema_cache"] = SchemaCache.from_dict(session_data["schema_cache"])
            print_info(f"Resumed session: {arg}")
            return result
        else:
            print_error(f"Session '{arg}' not found.")
    elif cmd == "/clear":
        chat_history.clear()
        print_success("Session history cleared.")
    elif cmd == "/export":
        save_session(session_name, chat_history, cfg.model, cfg.get_db_label(), summary, schema_cache)
        md = export_session_markdown(session_name)
        if md:
            out_path = Path(f"{session_name}_export.md")
            out_path.write_text(md, encoding="utf-8")
            print_success(f"Exported to {out_path.absolute()}")
        else:
            print_error("Failed to export session.")
    elif cmd == "/history":
        from pgchat.memory import _serialize_message
        serialized = [_serialize_message(m) for m in chat_history]
        print_history(serialized)
    elif cmd == "/refresh-schema":
        return _do_refresh_schema(schema_cache, session_name, chat_history, cfg, summary)
    else:
        print_warning(f"Unknown command: {cmd}. Type /help for commands.")

    return None


def _do_refresh_schema(
    old_cache: Optional[SchemaCache],
    session_name: str,
    chat_history: list[BaseMessage],
    cfg: Config,
    summary: str,
) -> Optional[dict]:
    """Handle /refresh-schema command."""
    with console.status("[cyan]🔄 Refreshing schema...[/cyan]"):
        try:
            new_cache = build_schema_cache()
        except Exception as e:
            print_error(f"Failed to refresh schema: {e}")
            return None

    if old_cache:
        diff = old_cache.diff_summary(new_cache)
        print_success(f"Schema refreshed — {diff}")
    else:
        print_success(f"Schema refreshed — {len(new_cache.tables)} tables loaded")

    # Save updated session
    save_session(session_name, chat_history, cfg.model, cfg.get_db_label(), summary, new_cache)

    return {"schema_cache": new_cache}


def _do_summarize(
    agent,
    system_msg: SystemMessage,
    chat_history: list[BaseMessage],
    session_name: str,
    cfg: Config,
    existing_summary: str,
    schema_cache: Optional[SchemaCache],
) -> None:
    """Summarize conversation when it gets too long."""
    from pgchat.agent import invoke_agent, extract_response_text

    prompt = build_summary_prompt(chat_history)
    summary_messages = [HumanMessage(content=prompt)]

    try:
        with console.status("[dim]Summarizing conversation...[/dim]"):
            result = invoke_agent(agent, summary_messages, system_msg)
        new_summary = extract_response_text(result)
        if new_summary:
            # Keep only last 10 messages + summary
            trimmed = chat_history[-10:]
            chat_history.clear()
            chat_history.extend(trimmed)
            save_session(session_name, chat_history, cfg.model, cfg.get_db_label(), new_summary, schema_cache)
            console.print("[dim]💾 Conversation summarized to save context.[/dim]")
    except Exception:
        pass  # Non-critical, just skip summarization


if __name__ == "__main__":
    main()

