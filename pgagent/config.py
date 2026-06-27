"""Configuration management: dataclass, .env loading, interactive wizard."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from dotenv import load_dotenv

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
SESSIONS_DIR = PROJECT_ROOT / "sessions"


@dataclass
class Config:
    """Application configuration."""

    # Database
    db_host: str = "localhost"
    db_port: int = 5432
    db_database: str = "postgres"
    db_user: str = "postgres"
    db_password: str = ""
    database_url: Optional[str] = None

    # LLM
    backend: str = "ollama"  # "ollama" or "anthropic"
    model: str = "qwen2.5:7b"
    anthropic_api_key: Optional[str] = None

    # UI
    show_tool_calls: bool = False

    # Session
    session_name: Optional[str] = None

    def get_dsn(self) -> str:
        """Return a connection DSN string."""
        if self.database_url:
            return self.database_url
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_database}"
        )

    def get_db_label(self) -> str:
        """Friendly label like user@host/database."""
        return f"{self.db_user}@{self.db_host}:{self.db_port}/{self.db_database}"


def load_config(
    db_url: Optional[str] = None,
    model: Optional[str] = None,
    backend: Optional[str] = None,
    show_tool_calls: bool = False,
    session_name: Optional[str] = None,
) -> Config:
    """Load config from .env file and CLI overrides."""
    load_dotenv(ENV_FILE)

    cfg = Config(
        db_host=os.getenv("PGAGENT_DB_HOST", "localhost"),
        db_port=int(os.getenv("PGAGENT_DB_PORT", "5432")),
        db_database=os.getenv("PGAGENT_DB_DATABASE", "postgres"),
        db_user=os.getenv("PGAGENT_DB_USER", "postgres"),
        db_password=os.getenv("PGAGENT_DB_PASSWORD", ""),
        database_url=os.getenv("DATABASE_URL"),
        backend=os.getenv("PGAGENT_BACKEND", "ollama"),
        model=os.getenv("PGAGENT_MODEL", "qwen2.5:7b"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        show_tool_calls=os.getenv("PGAGENT_SHOW_TOOL_CALLS", "").lower() in ("1", "true", "yes"),
    )

    # CLI overrides
    if db_url:
        cfg.database_url = db_url
    if model:
        cfg.model = model
    if backend:
        cfg.backend = backend
    if show_tool_calls:
        cfg.show_tool_calls = True
    if session_name:
        cfg.session_name = session_name

    # If DATABASE_URL is set, parse it into individual fields for labeling
    if cfg.database_url:
        _apply_url_fields(cfg)

    # If anthropic key is set and backend wasn't explicitly specified, auto-detect
    if cfg.anthropic_api_key and not backend and not os.getenv("PGAGENT_BACKEND"):
        cfg.backend = "anthropic"
        if not model and not os.getenv("PGAGENT_MODEL"):
            cfg.model = "claude-haiku-3"

    return cfg


def _apply_url_fields(cfg: Config) -> None:
    """Parse DATABASE_URL into individual config fields."""
    try:
        parsed = urlparse(cfg.database_url)
        if parsed.hostname:
            cfg.db_host = parsed.hostname
        if parsed.port:
            cfg.db_port = parsed.port
        if parsed.path and parsed.path.startswith("/"):
            cfg.db_database = parsed.path.lstrip("/")
        if parsed.username:
            cfg.db_user = parsed.username
        if parsed.password:
            cfg.db_password = parsed.password
    except Exception:
        pass


def run_config_wizard() -> None:
    """Interactive setup wizard that writes a .env file."""
    from rich.console import Console
    from rich.prompt import Prompt, IntPrompt

    console = Console()
    console.print("\n[bold cyan]🔧 PGAgent Configuration Wizard[/bold cyan]\n")

    host = Prompt.ask("PostgreSQL host", default="localhost")
    port = IntPrompt.ask("PostgreSQL port", default=5432)
    database = Prompt.ask("Database name", default="postgres")
    user = Prompt.ask("Database user", default="postgres")
    password = Prompt.ask("Database password (will be saved in .env)", password=True, default="")
    model = Prompt.ask("LLM model name", default="qwen2.5:7b")
    backend = Prompt.ask("Backend (ollama/anthropic)", default="ollama")

    anthropic_key = ""
    if backend == "anthropic":
        anthropic_key = Prompt.ask("Anthropic API Key", password=True, default="")

    env_content = f"""# PGAgent Configuration
PGAGENT_DB_HOST={host}
PGAGENT_DB_PORT={port}
PGAGENT_DB_DATABASE={database}
PGAGENT_DB_USER={user}
PGAGENT_DB_PASSWORD={password}
PGAGENT_MODEL={model}
PGAGENT_BACKEND={backend}
"""
    if anthropic_key:
        env_content += f"ANTHROPIC_API_KEY={anthropic_key}\n"

    ENV_FILE.write_text(env_content, encoding="utf-8")
    console.print(f"\n[green]✓ Configuration saved to {ENV_FILE}[/green]\n")

