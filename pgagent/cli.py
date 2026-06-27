"""Click-based CLI entry point for PGAgent."""

import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import click

from pgagent import __version__
from pgagent.config import (
    Config,
    ENV_FILE,
    load_config,
    run_config_wizard,
)
from pgagent.db import init_db, test_connection, get_cached_tables
from pgagent.memory import (
    build_summary_prompt,
    delete_session,
    deserialize_messages,
    export_session_markdown,
    list_sessions,
    load_session,
    save_session,
    should_summarize,
)
from pgagent.ui import (
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

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage


@click.group(invoke_without_command=True)
@click.option("--config", "run_config", is_flag=True, help="Run connection setup wizard.")
@click.option("--db-url", default=None, help="PostgreSQL connection URL.")
@click.option("--model", default=None, help="LLM model name override.")
@click.option("--backend", default=None, type=click.Choice(["ollama", "anthropic"]), help="LLM backend.")
@click.option("--session", "session_name", default=None, help="Start with a named session.")
@click.option("--show-tool-calls", is_flag=True, help="Show raw tool call/response details.")
@click.version_option(__version__, prog_name="pgagent")
@click.pass_context
def main(ctx, run_config, db_url, model, backend, session_name, show_tool_calls):
    """PGAgent - An AI-powered PostgreSQL assistant CLI."""
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
        console.print("[dim]Run pgagent --config to reconfigure.[/dim]")
        sys.exit(1)

    print_success(f"Connected to PostgreSQL")
    console.print(f"  [dim]{msg.split(',')[0] if ',' in msg else msg[:60]}[/dim]")

    # Auto-explore: get table list for context
    with console.status("[cyan]Exploring database schema...[/cyan]"):
        tables = get_cached_tables()
    db_context = ", ".join(tables) if tables else "No tables found"

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
    _chat_loop(cfg, db_context, current_session)


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

    # Interactive session selection
    all_sessions = list_sessions()
    if not all_sessions:
        name = _generate_session_name()
        print_info(f"Starting new session: {name}")
        return name

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


def _chat_loop(cfg: Config, db_context: str, session_name: str) -> None:
    """Main interactive chat loop."""
    from pgagent.agent import (
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

    system_msg = build_system_message(db_context)

    # Load existing session messages or start fresh
    session_data = load_session(session_name)
    if session_data:
        chat_history: list[BaseMessage] = deserialize_messages(session_data)
        summary = session_data.get("summary", "")
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
            save_session(session_name, chat_history, cfg.model, cfg.get_db_label(), summary)
            console.print("\n[dim]Session saved. Goodbye! 👋[/dim]")
            break

        # Handle slash commands
        if user_input.startswith("/"):
            handled = _handle_command(
                user_input, cfg, session_name, chat_history, summary
            )
            if handled == "new_session":
                session_name = _generate_session_name()
                chat_history = []
                summary = ""
                print_info(f"New session: {session_name}")
            elif handled == "exit":
                break
            elif isinstance(handled, tuple) and handled[0] == "resume":
                session_name = handled[1]
                session_data = load_session(session_name)
                if session_data:
                    chat_history = deserialize_messages(session_data)
                    summary = session_data.get("summary", "")
                else:
                    chat_history = []
                    summary = ""
                print_info(f"Resumed session: {session_name}")
            continue

        # Add user message
        chat_history.append(HumanMessage(content=user_input))

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

        # Auto-save
        save_session(session_name, chat_history, cfg.model, cfg.get_db_label(), summary)

        # Check if summarization is needed
        if should_summarize(chat_history):
            _do_summarize(agent, system_msg, chat_history, session_name, cfg, summary)


def _handle_command(
    command: str,
    cfg: Config,
    session_name: str,
    chat_history: list[BaseMessage],
    summary: str,
) -> Optional[str | tuple[str, str]]:
    """Handle slash commands. Returns action string or None."""
    parts = command.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd == "/help":
        print_help()
    elif cmd == "/sessions":
        all_sessions = list_sessions()
        print_sessions_table(all_sessions)
    elif cmd == "/new":
        return "new_session"
    elif cmd == "/resume":
        if not arg:
            console.print("[yellow]Usage: /resume <session_name>[/yellow]")
            return None
        if load_session(arg):
            return ("resume", arg)
        else:
            print_error(f"Session '{arg}' not found.")
    elif cmd == "/clear":
        chat_history.clear()
        print_success("Session history cleared.")
    elif cmd == "/export":
        save_session(session_name, chat_history, cfg.model, cfg.get_db_label(), summary)
        md = export_session_markdown(session_name)
        if md:
            out_path = Path(f"{session_name}_export.md")
            out_path.write_text(md, encoding="utf-8")
            print_success(f"Exported to {out_path.absolute()}")
        else:
            print_error("Failed to export session.")
    elif cmd == "/history":
        from pgagent.memory import _serialize_message
        serialized = [_serialize_message(m) for m in chat_history]
        print_history(serialized)
    else:
        print_warning(f"Unknown command: {cmd}. Type /help for commands.")

    return None


def _do_summarize(
    agent,
    system_msg: SystemMessage,
    chat_history: list[BaseMessage],
    session_name: str,
    cfg: Config,
    existing_summary: str,
) -> None:
    """Summarize conversation when it gets too long."""
    from pgagent.agent import invoke_agent

    prompt = build_summary_prompt(chat_history)
    summary_messages = [HumanMessage(content=prompt)]

    try:
        with console.status("[dim]Summarizing conversation...[/dim]"):
            result = invoke_agent(agent, summary_messages, system_msg)
        from pgagent.agent import extract_response_text
        new_summary = extract_response_text(result)
        if new_summary:
            # Keep only last 10 messages + summary
            trimmed = chat_history[-10:]
            chat_history.clear()
            chat_history.extend(trimmed)
            save_session(session_name, chat_history, cfg.model, cfg.get_db_label(), new_summary)
            console.print("[dim]💾 Conversation summarized to save context.[/dim]")
    except Exception:
        pass  # Non-critical, just skip summarization


if __name__ == "__main__":
    main()




