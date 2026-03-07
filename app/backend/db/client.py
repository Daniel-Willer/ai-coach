"""
Delta table query client using databricks-sql-connector.
Replaces spark.sql() from the notebook environment.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any

from databricks import sql

CATALOG = "ai_coach"
ATHLETE_ID = "athlete_1"


def _get_connection():
    return sql.connect(
        server_hostname=os.environ["DATABRICKS_HOST"],
        http_path=os.environ["DATABRICKS_SQL_HTTP_PATH"],
        access_token=os.environ["DATABRICKS_TOKEN"],
    )


def query(sql_str: str) -> list[dict[str, Any]]:
    """Execute a SQL query and return rows as list of dicts."""
    with _get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql_str)
            if cursor.description is None:
                return []
            cols = [d[0] for d in cursor.description]
            return [dict(zip(cols, row)) for row in cursor.fetchall()]


def query_one(sql_str: str) -> dict[str, Any] | None:
    """Execute a SQL query and return the first row, or None."""
    rows = query(sql_str)
    return rows[0] if rows else None


def execute(sql_str: str) -> None:
    """Execute a DML statement (INSERT / MERGE / UPDATE / DELETE)."""
    with _get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql_str)
