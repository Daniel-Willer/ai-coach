"""
Chat router — SSE streaming endpoint.
POST /api/chat/stream → Server-Sent Events stream of token/tool/done events.
GET  /api/chat/sessions → list past sessions
GET  /api/chat/sessions/{id} → load a past session's messages
"""
from __future__ import annotations

import asyncio
import json
import threading
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent.coach import run_agent_streaming
from agent.memory import create_session, get_sessions, get_session_messages
from db.client import ATHLETE_ID

router = APIRouter(prefix="/api/chat")


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    history: list[dict] = []


@router.post("/stream")
async def chat_stream(req: ChatRequest):
    """Stream coaching agent response as SSE."""
    athlete_id = ATHLETE_ID

    # Create or reuse session
    session_id = req.session_id
    if not session_id:
        session_id = create_session(athlete_id, req.message)

    queue: asyncio.Queue = asyncio.Queue()

    # Run agent in background thread (LangChain is sync)
    def run():
        run_agent_streaming(
            question=req.message,
            session_id=session_id,
            history=req.history,
            queue=queue,
            athlete_id=athlete_id,
        )

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    async def generate():
        # Send session_id first so client can track it
        yield f"data: {json.dumps({'type': 'session', 'session_id': session_id})}\n\n"

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=120.0)
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Agent timed out'})}\n\n"
                break

            yield f"data: {json.dumps(event, default=str)}\n\n"

            if event.get("type") in ("done", "error"):
                break

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/sessions")
async def list_sessions():
    """Return recent conversation sessions for the sidebar."""
    sessions = get_sessions(ATHLETE_ID, limit=30)
    return {"sessions": sessions}


@router.get("/sessions/{session_id}")
async def load_session(session_id: str):
    """Load all messages for a past session."""
    messages = get_session_messages(session_id)
    return {"session_id": session_id, "messages": messages}
