"""Generate interactive charts from query results using Plotly.

Provides a single shared function `generate_chart()` used by:
  - The generate_chart_tool LangChain tool (LLM-invoked)
"""

import webbrowser
from datetime import datetime, date, time as dt_time
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from pgchat.db import ExecutionResult

# Supported chart types the user/LLM can request
VALID_CHART_TYPES = {"auto", "bar", "line", "scatter", "pie"}

# Types we consider "numeric" when inspecting Python values from psycopg2
_NUMERIC_TYPES = (int, float, Decimal)

# Types we consider "date/time-like"
_DATE_TYPES = (datetime, date, dt_time)


def _is_numeric_column(values: list[Any]) -> bool:
    """Check if a column's non-None values are predominantly numeric."""
    non_null = [v for v in values if v is not None]
    if not non_null:
        return False
    numeric_count = sum(1 for v in non_null if isinstance(v, _NUMERIC_TYPES))
    return numeric_count / len(non_null) >= 0.8


def _is_date_column(values: list[Any]) -> bool:
    """Check if a column's non-None values are predominantly date/time-like."""
    non_null = [v for v in values if v is not None]
    if not non_null:
        return False
    date_count = sum(1 for v in non_null if isinstance(v, _DATE_TYPES))
    return date_count / len(non_null) >= 0.8


def _classify_columns(
    result: ExecutionResult,
) -> tuple[list[int], list[int], list[int]]:
    """Classify columns into numeric, date, and categorical index lists."""
    numeric_idxs: list[int] = []
    date_idxs: list[int] = []
    cat_idxs: list[int] = []

    for col_idx in range(len(result.columns)):
        col_values = [row[col_idx] for row in result.rows]
        if _is_numeric_column(col_values):
            numeric_idxs.append(col_idx)
        elif _is_date_column(col_values):
            date_idxs.append(col_idx)
        else:
            cat_idxs.append(col_idx)

    return numeric_idxs, date_idxs, cat_idxs


def _generate_filepath() -> Path:
    """Generate a chart filepath in cwd with a timestamp."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path.cwd() / f"pgchat_chart_{timestamp}.html"


def _not_a_good_fit() -> str:
    return (
        "This result isn't a good fit for charting — it needs at least one "
        "numeric column and one category or date column."
    )


def generate_chart(
    result: ExecutionResult,
    chart_type: str = "auto",
) -> str:
    """
    Generate an interactive Plotly chart from query results and open it
    in the user's default browser.

    Args:
        result: The ExecutionResult containing rows and column names.
        chart_type: "auto", "bar", "line", "scatter", or "pie".

    Returns:
        A human-readable message describing the outcome (success or error).
        Never raises — all errors are caught and returned as strings.
    """
    try:
        import plotly.graph_objects as go
    except ImportError:
        return "Plotly is not installed. Run: pip install plotly"

    chart_type = chart_type.lower().strip()
    if chart_type not in VALID_CHART_TYPES:
        return (
            f"Invalid chart type '{chart_type}'. "
            f"Valid options: {', '.join(sorted(VALID_CHART_TYPES))}"
        )

    # --- Pre-checks ---
    if not result.columns:
        return "Cannot chart: the last query did not return column data (non-SELECT statement)."

    if not result.rows:
        return "Cannot chart: the query returned no rows."

    if len(result.columns) < 2:
        return _not_a_good_fit()

    try:
        # --- Classify columns ---
        numeric_idxs, date_idxs, cat_idxs = _classify_columns(result)

        if not numeric_idxs:
            return _not_a_good_fit()

        # --- Determine chart type & axis mapping ---
        resolved_type: Optional[str] = None
        x_idx: Optional[int] = None
        y_idx: Optional[int] = None

        # Case 1: one numeric + one categorical/date  (2-column result or pick first of each)
        if len(numeric_idxs) >= 1 and (cat_idxs or date_idxs):
            y_idx = numeric_idxs[0]
            if date_idxs:
                x_idx = date_idxs[0]
                resolved_type = "line"  # default for date x-axis
            else:
                x_idx = cat_idxs[0]
                resolved_type = "bar"  # default for categorical x-axis
        # Case 2: two numeric columns (scatter)
        elif len(numeric_idxs) >= 2:
            x_idx = numeric_idxs[0]
            y_idx = numeric_idxs[1]
            resolved_type = "scatter"
        else:
            return _not_a_good_fit()

        # Apply user override if specified
        if chart_type != "auto":
            # Validate compatibility
            if chart_type == "scatter" and len(numeric_idxs) < 2 and not (date_idxs or cat_idxs):
                return _not_a_good_fit()
            if chart_type == "pie" and not (cat_idxs or date_idxs):
                return _not_a_good_fit()
            resolved_type = chart_type

        x_col = result.columns[x_idx]
        y_col = result.columns[y_idx]
        x_data = [row[x_idx] for row in result.rows]
        y_data = [row[y_idx] for row in result.rows]

        # Convert Decimal to float for Plotly
        y_data = [float(v) if isinstance(v, Decimal) else v for v in y_data]
        x_data = [float(v) if isinstance(v, Decimal) else v for v in x_data]
        # Stringify categoricals for Plotly
        if x_idx in cat_idxs:
            x_data = [str(v) for v in x_data]

        # --- Build chart ---
        fig = go.Figure()
        title = f"{y_col} by {x_col}"

        if resolved_type == "bar":
            fig.add_trace(go.Bar(x=x_data, y=y_data, name=y_col))
        elif resolved_type == "line":
            fig.add_trace(go.Scatter(x=x_data, y=y_data, mode="lines+markers", name=y_col))
        elif resolved_type == "scatter":
            fig.add_trace(go.Scatter(x=x_data, y=y_data, mode="markers", name=y_col))
            title = f"{y_col} vs {x_col}"
        elif resolved_type == "pie":
            fig = go.Figure(data=[go.Pie(labels=x_data, values=y_data)])
            title = f"{y_col} by {x_col}"
        else:
            return _not_a_good_fit()

        fig.update_layout(
            title=title,
            xaxis_title=x_col if resolved_type != "pie" else None,
            yaxis_title=y_col if resolved_type != "pie" else None,
            template="plotly_white",
        )

        # --- Save & open ---
        filepath = _generate_filepath()
        fig.write_html(str(filepath), include_plotlyjs=True, full_html=True)
        webbrowser.open(filepath.as_uri())

        row_count = result.row_count
        filename = filepath.name
        return (
            f"Generated a {resolved_type} chart from {row_count} "
            f"row{'s' if row_count != 1 else ''} and opened it in your "
            f"browser: {filename}"
        )

    except Exception as e:
        return f"Failed to generate chart: {e}"

