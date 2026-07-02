# Changelog

## [1.1.0] - 2026

### Added

- **Explain-before-execute**: Before running any SQL query, the agent generates a plain-English explanation of what the query does (tables involved, filters, expected result shape)
- New config flag `PGCHAT_EXPLAIN_QUERIES` (default: `true`) to toggle explanations on/off
- New module `pgchat/explain.py` with focused LLM call for query explanations
- 13 new tests covering the explain feature

## [1.0.0] - 2025

### Added

- Initial public release
- Natural language to SQL via Ollama and Anthropic Claude
- Persistent JSON-based session memory with auto-summarization
- Schema cache injected at startup as system context
- Single SQL execution gateway with read-only safety enforcement
- Rich terminal UI with syntax-highlighted SQL and table output
- Named sessions with /resume, /export, /history commands
- /refresh-schema command for live schema updates
- pip installable as `pgchat`

