"""
Conversation memory — persists sessions and messages to Delta via sql connector.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from db.client import query, query_one, execute, CATALOG


def create_session(athlete_id: str, first_message: str) -> str:
    """Create a new conversation session and return the session_id."""
    session_id = str(uuid.uuid4())
    title = first_message[:60] + ("..." if len(first_message) > 60 else "")
    now = datetime.utcnow().isoformat()
    execute(f"""
        INSERT INTO {CATALOG}.coach.conversation_sessions
        (session_id, athlete_id, title, started_at, updated_at, message_count, summary)
        VALUES ('{session_id}', '{athlete_id}', '{title.replace("'", "''")}', '{now}', '{now}', 0, NULL)
    """)
    return session_id


def append_message(session_id: str, athlete_id: str, seq: int, role: str,
                   content: str, tool_calls: list | None = None) -> None:
    """Append a message to the conversation."""
    msg_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    tool_json = json.dumps(tool_calls, default=str) if tool_calls else "NULL"
    content_escaped = content.replace("'", "''")
    tool_escaped = tool_json.replace("'", "''") if tool_json != "NULL" else "NULL"
    execute(f"""
        INSERT INTO {CATALOG}.coach.conversation_messages
        (msg_id, session_id, athlete_id, seq, role, content, tool_calls_json, ts)
        VALUES ('{msg_id}', '{session_id}', '{athlete_id}', {seq}, '{role}',
                '{content_escaped}', {'NULL' if tool_json == 'NULL' else f"'{tool_escaped}'"}, '{now}')
    """)
    execute(f"""
        UPDATE {CATALOG}.coach.conversation_sessions
        SET message_count = message_count + 1, updated_at = '{now}'
        WHERE session_id = '{session_id}'
    """)


def get_sessions(athlete_id: str, limit: int = 20) -> list[dict]:
    """Return recent sessions for the sidebar."""
    return query(f"""
        SELECT session_id, title, started_at, updated_at, message_count
        FROM {CATALOG}.coach.conversation_sessions
        WHERE athlete_id = '{athlete_id}'
        ORDER BY updated_at DESC
        LIMIT {limit}
    """)


def get_session_messages(session_id: str) -> list[dict]:
    """Return all messages for a session, ordered by seq."""
    return query(f"""
        SELECT seq, role, content, tool_calls_json, ts
        FROM {CATALOG}.coach.conversation_messages
        WHERE session_id = '{session_id}'
        ORDER BY seq ASC
    """)
