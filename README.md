# PGChat 🐘

> Chat with your PostgreSQL database using natural language. Powered by local LLMs via Ollama or Claude by Anthropic.

<!-- Add a demo GIF here -->

## Features

- **Natural language to SQL** — just ask questions about your data
- **Beautiful terminal UI** built with Rich
- **Persistent named sessions** with conversation memory
- **Schema cached at startup** — no redundant fetches mid-conversation
- **Single SQL execution gateway** with read-only safety enforcement
- **Supports Ollama** (local, private) **and Anthropic Claude** as backends
- **pip installable** — one command to get started

## Quick Start

```bash
pip install pgchat
pgchat
```

On first run, a setup wizard asks for your DB connection and preferred model.

## Installation

### From PyPI

```bash
pip install pgchat
```

### From source

```bash
git clone https://github.com/icon-gaurav/pgchat.git
cd pgchat
pip install -e .
```

## Backends

### Ollama (default — local and private)

Install Ollama from [ollama.com](https://ollama.com), pull a model, then run pgchat.

Recommended models: `qwen2.5:7b`, `llama3.1:8b`, `mistral:7b`

```bash
ollama pull qwen2.5:7b
pgchat --model qwen2.5:7b
```

### Anthropic Claude

```bash
export ANTHROPIC_API_KEY=your_key
pgchat --backend anthropic --model claude-haiku-3
```

Or set in your `.env`:

```
PGCHAT_BACKEND=anthropic
PGCHAT_MODEL=claude-haiku-3
ANTHROPIC_API_KEY=sk-ant-...
```

## CLI Reference

```
pgchat                              Start interactive chat (default session)
pgchat --config                     Re-run connection setup wizard
pgchat --db-url <url>               Connect via DATABASE_URL
pgchat --model <name>               Override LLM model
pgchat --backend ollama|anthropic   Choose LLM backend
pgchat --session <name>             Open a named session
pgchat --show-tool-calls            Show raw tool call/response blocks
pgchat --version                    Show version

pgchat sessions list                List all saved sessions
pgchat sessions delete <name>       Delete a session
pgchat sessions export <name>       Export session as markdown
```

## In-Chat Commands

| Command | Description |
|---------|-------------|
| `/sessions` | List all saved sessions |
| `/new` | Start a fresh session |
| `/resume <name>` | Switch to a different session |
| `/clear` | Clear current session history |
| `/history` | Show last 10 turns |
| `/export` | Export session as markdown |
| `/refresh-schema` | Re-fetch schema from the database |
| `/help` | Show available commands |
| `exit` | Quit PGChat |

## How Memory Works

Sessions are saved as JSON files in `sessions/`.

Schema is fetched once at startup and injected as context — the agent knows your full database structure before you ask your first question.

When a session exceeds 20 turns, older messages are summarized automatically to keep context tight.

## Safety

All SQL runs through a single gateway function with a read-only safety check. Only `SELECT`, `WITH`, `SHOW`, and `EXPLAIN` queries are allowed.

`cursor.execute()` exists exactly once in the codebase — inside `db.py`.

## Explain-Before-Execute

When `PGCHAT_EXPLAIN_QUERIES=true` (the default), PGChat generates a plain-English explanation of each SQL query before executing it. This helps you understand what the agent is doing without reading raw SQL.

**Example interaction:**

```
You » show me top 5 customers by total order amount

  ⚙  Calling run_query...

╭─── 💡 Query Explanation ────────────────────────────────────────────────╮
│ This query joins the customers and orders tables on customer_id,        │
│ groups results by customer name, sums the order amounts per customer,   │
│ and returns the top 5 customers with the highest total spend in         │
│ descending order.                                                       │
╰─────────────────────────────────────────────────────────────────────────╯

╭─── 🤖 Agent ──────────────────────────────────── 14:32:07 ──╮
│ Here are the top 5 customers by total order amount:          │
│                                                              │
│ | customer   | total_amount |                                │
│ |------------|--------------|                                 │
│ | Acme Corp  | $142,500     |                                │
│ | Wayne Ent  | $98,200      |                                │
│ | ...        | ...          |                                │
╰──────────────────────────────────────────────────────────────╯
```

**Configuration:**
- Set `PGCHAT_EXPLAIN_QUERIES=false` in `.env` to disable explanations
- Explanations are non-blocking: if the LLM call fails, queries still execute normally

## Contributing

PRs welcome. Before submitting, verify the single-gateway constraint:

```bash
grep -rn "cursor\.execute\|conn\.execute" . --include="*.py"
```

Must return exactly one result: inside `db.py`.

### Development Setup

```bash
git clone https://github.com/icon-gaurav/pgchat.git
cd pgchat
python -m venv .venv
.venv\Scripts\activate    # Windows
# source .venv/bin/activate  # Linux/Mac
pip install -e .
pytest
```

## License

MIT — see [LICENSE](LICENSE) for details.

---

Built with ❤️ by [Gaurav](https://gauravbytes.dev)
