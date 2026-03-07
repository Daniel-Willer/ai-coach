"""
Databricks Secrets access via SDK.
Replaces dbutils.secrets.get() from the notebook environment.

In Databricks Apps, DATABRICKS_HOST and DATABRICKS_TOKEN are injected automatically.
Outside Databricks (local dev), set them in .env.
"""
from __future__ import annotations

import base64
import os
from functools import lru_cache

from databricks.sdk import WorkspaceClient


@lru_cache(maxsize=128)
def get_secret(scope: str, key: str) -> str:
    """Fetch a secret from Databricks Secrets. Result is cached in-process."""
    w = WorkspaceClient()
    val = w.secrets.get_secret(scope=scope, key=key).value
    # Databricks SDK returns base64-encoded bytes
    return base64.b64decode(val).decode("utf-8")
