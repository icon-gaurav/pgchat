"""SQL safety validation — blocks non-read-only queries."""

import re


def normalize_sql_for_safety(query: str) -> str:
    """Remove comments and string literals, collapse whitespace."""
    without_block_comments = re.sub(r"/\*.*?\*/", " ", query, flags=re.S)
    without_line_comments = re.sub(r"--[^\n]*", " ", without_block_comments)
    without_single_quotes = re.sub(r"'([^']|'')*'", "''", without_line_comments)
    without_double_quotes = re.sub(r'"([^"]|"")*"', '""', without_single_quotes)
    return re.sub(r"\s+", " ", without_double_quotes).strip()


def validate_read_only_sql(query: str) -> tuple[bool, str]:
    """
    Validate that a SQL query is read-only.
    Returns (is_safe, reason) where reason is empty if safe.
    """
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

