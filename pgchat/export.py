"""Export query results to CSV or JSON files.

Provides a single shared function `export_results()` used by both:
  - The /export slash command (deterministic, user-typed)
  - The export_results_tool LangChain tool (LLM-invoked)
"""

import csv
import json
from datetime import datetime, date, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

from pgchat.db import ExecutionResult


def _make_serializable(value: Any) -> Any:
    """Convert non-JSON-serializable types to strings."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date, time, timedelta, Decimal, UUID)):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, (list, tuple)):
        return [_make_serializable(v) for v in value]
    if isinstance(value, dict):
        return {k: _make_serializable(v) for k, v in value.items()}
    # Fallback: stringify anything else
    return str(value)


def _generate_filepath(fmt: str, filename: Optional[str] = None) -> Path:
    """Generate an export filepath in cwd."""
    if filename:
        return Path.cwd() / filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path.cwd() / f"pgchat_export_{timestamp}.{fmt}"


def export_results(
    result: ExecutionResult,
    format: str,
    filename: Optional[str] = None,
) -> str:
    """
    Export query results to a file in CSV or JSON format.

    This is the SINGLE shared implementation used by both the /export slash
    command and the export_results_tool LangChain tool.

    Args:
        result: The ExecutionResult containing rows and column names.
        format: "csv" or "json".
        filename: Optional custom filename. Auto-generated if not provided.

    Returns:
        A human-readable message describing the outcome (success or error).
        Never raises — all errors are caught and returned as strings.
    """
    fmt = format.lower().strip()
    if fmt not in ("csv", "json"):
        return f"Invalid format '{format}'. Valid options: csv, json"

    if not result.columns:
        return "Cannot export: the last query did not return column data (non-SELECT statement)."

    filepath = _generate_filepath(fmt, filename)

    try:
        if fmt == "csv":
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(result.columns)
                for row in result.rows:
                    writer.writerow([str(v) if v is not None else "" for v in row])
        else:  # json
            records = [
                {col: _make_serializable(val) for col, val in zip(result.columns, row)}
                for row in result.rows
            ]
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(records, f, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"Failed to write export file: {e}"

    # Build success message
    row_count = result.row_count
    abs_path = str(filepath.absolute())
    if row_count == 0:
        return f"Exported (0 rows, headers only) to {abs_path}"
    return f"Exported {row_count} row{'s' if row_count != 1 else ''} to {abs_path}"
