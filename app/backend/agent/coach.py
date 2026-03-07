"""
Coaching agent — multi-turn, streaming, tool-calling.
Ported and upgraded from notebooks/06_coaching_agent.py.

Key changes from notebook version:
- ChatDatabricks → works the same in SDK context (uses DATABRICKS_HOST env var)
- Streaming via asyncio.Queue fed by LangChain callbacks
- Multi-turn via full message history passed on each request
- Session persistence via agent.memory module
"""
from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

from databricks_langchain import ChatDatabricks
from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from db.client import ATHLETE_ID
from agent.memory import append_message, create_session, get_session_messages
from tools.data import data_tools
from tools.analysis import analysis_tools
from tools.planning import planning_tools
from tools.strava_live import strava_live_tools
from tools.garmin_live import garmin_live_tools
from tools.intervals_live import intervals_live_tools
from tools.weather_live import weather_live_tools
from tools.rwgps_live import rwgps_live_tools

# All 34 tools
ALL_TOOLS = (
    data_tools + analysis_tools + planning_tools +
    strava_live_tools + garmin_live_tools + intervals_live_tools +
    weather_live_tools + rwgps_live_tools
)
TOOL_REGISTRY = {t.name: t for t in ALL_TOOLS}

LLM_ENDPOINT = "databricks-meta-llama-3-3-70b-instruct"

SYSTEM_PROMPT = f"""You are an expert AI cycling coach with deep knowledge of training science, physiology, and competitive cycling. You are coaching athlete_id='{ATHLETE_ID}'.

Your coaching philosophy:
- Data-driven: always look at the numbers before giving advice
- Holistic: consider sleep, stress, and recovery — not just ride data
- Honest: tell the athlete what they need to hear, not just what they want to hear
- Specific: give concrete, actionable guidance — not vague platitudes

How you work:
- Use tools to fetch real data before answering any question about training, fitness, or rides
- Always call get_athlete_profile first in a new conversation to understand who you're coaching
- When analyzing rides, call analyze_last_ride or analyze_activity to get actual metrics
- For planning questions, call suggest_todays_workout or generate_weekly_plan
- For trend questions, call get_power_curve_trend or detect_training_imbalance
- Back every recommendation with data you've fetched

Tool selection guide:
- Fitness/fatigue/form → get_training_load, get_fitness_snapshot
- Recent rides → get_recent_activities
- Last ride feedback → analyze_last_ride
- Specific ride → analyze_activity (needs activity_id)
- Power curve / strengths → get_power_curve, get_power_curve_trend
- Weekly review → get_weekly_summary
- Training balance → detect_training_imbalance
- Repeated route progress → compare_route_performances
- Today's workout → suggest_todays_workout
- Weekly plan → generate_weekly_plan
- Saved plan → get_saved_training_plan
- Route suggestion → suggest_route
- TSS estimation → estimate_ride_tss
- Pacing for target TSS → plan_ride_pacing
- Live Strava data → strava_get_recent_activities, strava_get_activity_detail
- Live Garmin → garmin_get_sleep, garmin_get_daily_stats, garmin_get_hrv_status, garmin_get_body_battery_today
- Live Intervals.icu → intervals_get_fitness, intervals_get_wellness
- Weather → weather_get_current, weather_get_forecast, weather_get_best_riding_window
- Routes → rwgps_search_routes, rwgps_get_route

Format:
- Be concise but specific — a good coach doesn't ramble
- Lead with the key insight, then support it with the numbers
- Use plain language, explain W/kg, TSS etc if the athlete seems unfamiliar
- End actionable responses with a clear "Next:" recommendation
"""


class StreamingCallback(BaseCallbackHandler):
    """Puts streaming events onto an asyncio queue for SSE."""

    def __init__(self, queue: asyncio.Queue):
        self.queue = queue
        self._loop = asyncio.get_event_loop()

    def _put(self, event: dict):
        try:
            self._loop.call_soon_threadsafe(self.queue.put_nowait, event)
        except Exception:
            pass

    def on_llm_new_token(self, token: str, **kwargs):
        self._put({"type": "token", "content": token})

    def on_tool_start(self, serialized: dict, input_str: str, **kwargs):
        self._put({"type": "tool_start", "tool": serialized.get("name", "tool")})

    def on_tool_end(self, output: str, **kwargs):
        # Send a brief summary (first 200 chars) so the UI can show what was found
        self._put({"type": "tool_end", "summary": str(output)[:200]})


def _build_llm(queue: asyncio.Queue | None = None):
    callbacks = [StreamingCallback(queue)] if queue else []
    return ChatDatabricks(
        endpoint=LLM_ENDPOINT,
        temperature=0.3,
        max_tokens=2000,
        streaming=True,
        callbacks=callbacks,
    )


def _messages_from_history(history: list[dict]) -> list:
    """Convert frontend message history (role/content dicts) to LangChain messages."""
    lc_messages = []
    for msg in history:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "user":
            lc_messages.append(HumanMessage(content=content))
        elif role == "assistant":
            lc_messages.append(AIMessage(content=content))
    return lc_messages


def run_agent_streaming(
    question: str,
    session_id: str,
    history: list[dict],
    queue: asyncio.Queue,
    athlete_id: str = ATHLETE_ID,
) -> None:
    """
    Run the coaching agent in a thread, feeding SSE events to queue.
    Call from a background thread — not async.
    """
    llm = _build_llm(queue)
    llm_with_tools = llm.bind_tools(ALL_TOOLS)

    messages = (
        [SystemMessage(content=SYSTEM_PROMPT)]
        + _messages_from_history(history)
        + [HumanMessage(content=question)]
    )

    tool_calls_this_turn: list[dict] = []
    seq = len(history)

    try:
        for iteration in range(10):
            response = llm_with_tools.invoke(messages)
            messages.append(response)

            if not response.tool_calls:
                # Final answer — persist to Delta
                final_text = response.content
                append_message(session_id, athlete_id, seq, "user", question)
                append_message(session_id, athlete_id, seq + 1, "assistant", final_text, tool_calls_this_turn)
                queue.put_nowait({"type": "done", "session_id": session_id})
                return

            # Execute tool calls
            for tc in response.tool_calls:
                tool_name = tc["name"]
                tool_args = tc["args"]
                queue.put_nowait({"type": "tool_start", "tool": tool_name, "args": str(tool_args)[:100]})

                if tool_name in TOOL_REGISTRY:
                    result = TOOL_REGISTRY[tool_name].invoke(tool_args)
                else:
                    result = f"Tool '{tool_name}' not found."

                tool_calls_this_turn.append({"tool": tool_name, "args": tool_args, "result_preview": str(result)[:200]})
                queue.put_nowait({"type": "tool_end", "tool": tool_name, "summary": str(result)[:200]})
                messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))

        queue.put_nowait({"type": "error", "message": "Agent reached max iterations."})
    except Exception as e:
        queue.put_nowait({"type": "error", "message": str(e)})


def run_agent_sync(
    question: str,
    history: list[dict] | None = None,
    athlete_id: str = ATHLETE_ID,
    verbose: bool = False,
) -> str:
    """Synchronous agent for testing and scripted use."""
    llm = _build_llm()
    llm_with_tools = llm.bind_tools(ALL_TOOLS)
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + _messages_from_history(history or []) + [HumanMessage(content=question)]

    for _ in range(10):
        response = llm_with_tools.invoke(messages)
        messages.append(response)
        if not response.tool_calls:
            return response.content
        for tc in response.tool_calls:
            if verbose:
                print(f"  → {tc['name']}({tc['args']})")
            result = TOOL_REGISTRY[tc["name"]].invoke(tc["args"]) if tc["name"] in TOOL_REGISTRY else f"Tool not found: {tc['name']}"
            messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))

    return "Agent reached max iterations."
