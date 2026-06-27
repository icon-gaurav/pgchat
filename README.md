# PG Agent 🐘🤖

An AI-powered PostgreSQL assistant that lives in your terminal. Ask questions about your database in natural language, explore schemas, run queries, and get intelligent insights — all powered by local LLMs (Ollama) or Anthropic Claude.

<!-- screenshot -->

## ✨ Features

- **Natural language SQL** — Ask questions like "show me the top 10 customers by revenue" and get real results
- **Schema exploration** — Automatically discovers tables, columns, relationships, and statistics
- **Read-only safety** — SQL safety guard blocks any destructive queries (INSERT, UPDATE, DELETE, DROP, etc.)
- **Persistent sessions** — Conversations are saved and can be resumed later
- **Beautiful CLI** — Rich-powered UI with syntax-highlighted SQL, formatted tables, and status spinners
- **Dual LLM backend** — Use local Ollama models or Anthropic Claude
- **Session memory** — Auto-summarizes long conversations to maintain context

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL database
- [Ollama](https://ollama.ai) running locally (or Anthropic API key)

### Install

```bash
git clone https://github.com/gauravbytes/pgagent.git
cd pgagent
pip install .
```

### First Run

```bash
pgagent
```

On first run, PGAgent will launch a configuration wizard asking for your database connection details and LLM preferences. These are saved to a local `.env` file.

Alternatively, configure manually:

```bash
cp .env.example .env
# Edit .env with your settings
pgagent
```

## 🔧 Configuration

### Config Wizard

```bash
pgagent --config
```

This launches an interactive setup wizard that prompts for:
- PostgreSQL host, port, database, user, password
- LLM model name
- Backend choice (ollama/anthropic)

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PGAGENT_DB_HOST` | `localhost` | PostgreSQL host |
| `PGAGENT_DB_PORT` | `5432` | PostgreSQL port |
| `PGAGENT_DB_DATABASE` | `postgres` | Database name |
| `PGAGENT_DB_USER` | `postgres` | Database user |
| `PGAGENT_DB_PASSWORD` | | Database password |
| `DATABASE_URL` | | Full connection URL (overrides individual fields) |
| `PGAGENT_MODEL` | `qwen2.5:7b` | LLM model name |
| `PGAGENT_BACKEND` | `ollama` | LLM backend: `ollama` or `anthropic` |
| `ANTHROPIC_API_KEY` | | Required for Anthropic backend |
| `PGAGENT_SHOW_TOOL_CALLS` | `false` | Show raw tool calls in output |

## 📋 CLI Flags

```
pgagent                              # Start interactive chat
pgagent --config                     # Run connection setup wizard
pgagent --db-url <url>               # Connect using a DATABASE_URL
pgagent --model <name>               # Override LLM model
pgagent --backend ollama|anthropic   # Choose LLM backend
pgagent --session <name>             # Start in a specific session
pgagent --show-tool-calls            # Show raw tool call details
pgagent --version                    # Show version

pgagent sessions list                # List all saved sessions
pgagent sessions delete <name>       # Delete a session
pgagent sessions export <name>       # Export session as markdown
```

## 💬 In-Chat Commands

While chatting with the agent, you can use these commands:

| Command | Description |
|---------|-------------|
| `/sessions` | List all saved sessions with timestamps |
| `/new` | Start a fresh session |
| `/resume <name>` | Switch to a different session |
| `/clear` | Clear current session history |
| `/export` | Export current session as markdown |
| `/history` | Show last 10 turns nicely formatted |
| `/help` | Show available commands |
| `exit` | Quit PGAgent |

## 🧠 LLM Backends

### Ollama (Default — Local)

PGAgent uses Ollama for local LLM inference by default:

1. Install [Ollama](https://ollama.ai)
2. Pull a model: `ollama pull qwen2.5:7b`
3. Run PGAgent — it connects to Ollama automatically

### Anthropic Claude

To use Claude instead:

1. Set `ANTHROPIC_API_KEY` in your `.env`
2. Run with: `pgagent --backend anthropic --model claude-haiku-3`

Or set in `.env`:
```
PGAGENT_BACKEND=anthropic
PGAGENT_MODEL=claude-haiku-3
ANTHROPIC_API_KEY=sk-ant-...
```

## 💾 Sessions & Memory

### How Sessions Work

- Each conversation is a **session** stored as a JSON file in `sessions/`
- Sessions track: name, timestamps, model, database, and full message history
- On startup, you're prompted to create a new session or resume an existing one
- Sessions auto-save after every AI response

### Conversation Summarization

When a session exceeds 20 turns, PGAgent automatically:
1. Asks the LLM to summarize the conversation so far
2. Trims older messages, keeping the summary for context
3. This prevents context window overflow while maintaining conversation history

## 🔒 Safety

PGAgent includes a SQL safety guard that:
- Only allows `SELECT`, `WITH`, `SHOW`, and `EXPLAIN` queries
- Blocks all DML (`INSERT`, `UPDATE`, `DELETE`) and DDL (`CREATE`, `DROP`, `ALTER`)
- Prevents multi-statement injection
- Strips comments and string literals before validation
- Blocks `SELECT INTO` (creates tables)

## 🛠️ Available Tools

The agent has access to these database tools:

| Tool | Description |
|------|-------------|
| `list_tables` | List all tables in the public schema |
| `get_table_schema` | Get columns, types, nullability for a table |
| `execute_sql` | Run read-only SQL queries |
| `get_table_sample` | Preview rows from a table |
| `search_schema` | Find tables/columns matching a keyword |
| `get_table_stats` | Row count, size, index count for a table |
| `get_db_info` | PostgreSQL version, size, uptime |
| `get_foreign_keys` | List FK relationships for a table |
| `explain_query` | Get EXPLAIN plan for a query |

## 🤝 Contributing

Contributions are welcome! Here's how:

1. Fork the repo
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make your changes
4. Run tests (if applicable)
5. Submit a pull request

### Development Setup

```bash
git clone https://github.com/gauravbytes/pgagent.git
cd pgagent
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac
pip install -e .
```

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

Built with ❤️ by [Gaurav](https://gauravbytes.dev)

