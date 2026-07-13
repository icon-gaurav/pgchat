"""Rich-based CLI UI: banners, panels, tables, spinners."""

from datetime import datetime
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from pgchat import __version__, __author__

# Custom theme
THEME = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green",
    "tool": "italic yellow",
    "dim": "dim",
})

console = Console(theme=THEME)


def print_banner(
    db_label: str = "",
    model: str = "",
    session_name: str = "",
    backend: str = "ollama",
) -> None:
    """Print the startup banner."""
    title_art = Text()
    title_art.append("╔═══════════════════════════════════════════╗\n", style="bold cyan")
    title_art.append("║               ", style="bold cyan")
    title_art.append("P G   C H A T", style="bold white")
    title_art.append("               ║\n", style="bold cyan")
    title_art.append("║          ", style="bold cyan")
    title_art.append("PostgreSQL AI Assistant", style="cyan")
    title_art.append("          ║\n", style="bold cyan")
    title_art.append("╚═══════════════════════════════════════════╝", style="bold cyan")

    info_lines = Text()
    info_lines.append(f"  Version: ", style="dim")
    info_lines.append(f"{__version__}\n", style="white")
    info_lines.append(f"  Author:  ", style="dim")
    info_lines.append(f"{__author__}\n", style="white")
    info_lines.append(f"  Backend: ", style="dim")
    info_lines.append(f"{backend} ", style="white")
    info_lines.append(f"({model})\n", style="cyan")
    if db_label:
        info_lines.append(f"  DB:      ", style="dim")
        info_lines.append(f"{db_label}\n", style="green")
    if session_name:
        info_lines.append(f"  Session: ", style="dim")
        info_lines.append(f"{session_name}\n", style="yellow")
    info_lines.append(f"\n  Type ", style="dim")
    info_lines.append("/help", style="bold white")
    info_lines.append(" for commands, ", style="dim")
    info_lines.append("exit", style="bold white")
    info_lines.append(" to quit", style="dim")

    console.print()
    console.print(title_art)
    console.print(info_lines)
    console.print()


def print_agent_response(content: str) -> None:
    """Render agent response in a styled panel."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    panel = Panel(
        Markdown(content),
        title="🤖 Agent",
        subtitle=f"[dim]{timestamp}[/dim]",
        border_style="blue",
        padding=(0, 1),
    )
    console.print(panel)


def print_tool_call(tool_name: str, args: dict[str, Any] | None = None) -> None:
    """Show a tool invocation line."""
    args_str = ""
    if args:
        # Show key args concisely
        parts = []
        for k, v in args.items():
            val = str(v)
            if len(val) > 80:
                val = val[:77] + "..."
            parts.append(f"{k}={val}")
        args_str = f" ({', '.join(parts)})"
    console.print(f"  [tool]⚙  Calling {tool_name}...[/tool]{args_str}")


def print_tool_response(tool_name: str, content: str) -> None:
    """Show tool response (when verbose mode is on)."""
    if len(content) > 500:
        content = content[:497] + "..."
    console.print(f"  [dim]↳ {tool_name}: {content}[/dim]")


def print_sql(sql: str) -> None:
    """Syntax-highlight a SQL query."""
    syntax = Syntax(sql.strip(), "sql", theme="monokai", line_numbers=False, word_wrap=True)
    console.print(Panel(syntax, title="SQL", border_style="dim", padding=(0, 1)))


def print_query_explanation(explanation: str) -> None:
    """Display a plain-English explanation of a SQL query."""
    console.print(Panel(
        f"[italic]{explanation}[/italic]",
        title="💡 Query Explanation",
        border_style="green",
        padding=(0, 1),
    ))


def print_query_results(columns: list[str], rows: list[tuple], total: int) -> None:
    """Render query results as a Rich table."""
    table = Table(show_header=True, header_style="bold magenta", row_styles=["", "dim"])
    for col in columns:
        table.add_column(col)
    for row in rows[:50]:
        table.add_row(*[str(v) for v in row])
    console.print(table)
    if total > 50:
        console.print(f"  [dim]Showing 50 of {total} rows[/dim]")
    else:
        console.print(f"  [dim]{total} row{'s' if total != 1 else ''}[/dim]")


def print_error(message: str) -> None:
    """Display an error panel."""
    console.print(Panel(
        f"[error]✗ {message}[/error]",
        border_style="red",
        padding=(0, 1),
    ))


def print_success(message: str) -> None:
    """Display a success message."""
    console.print(f"[success]✓ {message}[/success]")


def print_info(message: str) -> None:
    """Display an info message."""
    console.print(f"[info]{message}[/info]")


def print_warning(message: str) -> None:
    """Display a warning."""
    console.print(f"[warning]⚠ {message}[/warning]")


def print_sessions_table(sessions: list[dict[str, Any]]) -> None:
    """Render sessions list as a Rich table."""
    if not sessions:
        console.print("[dim]No saved sessions found.[/dim]")
        return

    table = Table(title="Saved Sessions", show_header=True, header_style="bold cyan")
    table.add_column("Name", style="bold")
    table.add_column("Database", style="green")
    table.add_column("Model", style="cyan")
    table.add_column("Turns", justify="right")
    table.add_column("Last Updated", style="dim")

    for s in sessions:
        updated = s.get("updated_at", "")
        if updated:
            try:
                dt = datetime.fromisoformat(updated)
                updated = dt.strftime("%Y-%m-%d %H:%M")
            except ValueError:
                pass
        table.add_row(
            s.get("name", ""),
            s.get("db_label", ""),
            s.get("model", ""),
            str(s.get("turn_count", 0)),
            updated,
        )
    console.print(table)


def print_history(messages: list[dict[str, Any]], last_n: int = 10) -> None:
    """Render recent chat history."""
    # Filter to human/ai messages
    relevant = [m for m in messages if m.get("role") in ("human", "ai") and m.get("content")]
    recent = relevant[-last_n * 2:]  # human+ai pairs

    if not recent:
        console.print("[dim]No history yet.[/dim]")
        return

    table = Table(title="Recent History", show_header=True, header_style="bold")
    table.add_column("Role", style="bold", width=8)
    table.add_column("Message")

    for msg in recent:
        role = msg["role"]
        content = msg["content"]
        if len(content) > 200:
            content = content[:197] + "..."
        if role == "human":
            table.add_row("[cyan]You[/cyan]", content)
        elif role == "ai":
            table.add_row("[blue]Agent[/blue]", content)

    console.print(table)


def get_user_input() -> str:
    """Get user input with a styled prompt."""
    try:
        return console.input("\n[bold cyan]You »[/bold cyan] ").strip()
    except (EOFError, KeyboardInterrupt):
        return "exit"


def print_help() -> None:
    """Print available in-chat commands."""
    help_text = """
[bold]In-Chat Commands:[/bold]

  [cyan]/sessions[/cyan]        — List all saved sessions
  [cyan]/new[/cyan]             — Start a fresh session
  [cyan]/resume <name>[/cyan]   — Switch to a different session
  [cyan]/clear[/cyan]           — Clear current session history
  [cyan]/export <fmt>[/cyan]    — Export last query result (csv or json)
  [cyan]/export-session[/cyan]  — Export current session as markdown
  [cyan]/history[/cyan]         — Show last 10 turns
  [cyan]/refresh-schema[/cyan]  — Re-fetch database schema from server
  [cyan]/help[/cyan]            — Show this help
  [cyan]exit[/cyan]             — Quit PGChat
"""
    console.print(Panel(help_text.strip(), title="Help", border_style="cyan"))

