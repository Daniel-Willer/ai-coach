"""
Intervals.icu MCP Server
------------------------
Exposes Intervals.icu training analytics as tools: CTL/ATL/TSB, power curves,
wellness, and recent activities aggregated from all connected platforms.

Setup:
  cd mcp/intervals
  pip install -r requirements.txt
  cp .env.example .env
  python server.py

Get API key: intervals.icu → Settings → API key
Athlete ID: from your profile URL intervals.icu/athletes/iXXXXXX
"""

import json
import os
from datetime import date, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv(Path(__file__).parent / ".env")

mcp = FastMCP("intervals-coach")


def _get(path: str, params: dict | None = None) -> dict | list:
    athlete_id = os.environ["INTERVALS_ATHLETE_ID"]
    api_key    = os.environ["INTERVALS_API_KEY"]
    resp = requests.get(
        f"https://intervals.icu/api/v1/athlete/{athlete_id}{path}",
        auth=("API_KEY", api_key),
        params=params or {},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _today() -> str:
    return str(date.today())

def _n_ago(n: int) -> str:
    return str(date.today() - timedelta(days=n))


@mcp.tool()
def intervals_get_fitness() -> str:
    """
    Get current CTL (fitness), ATL (fatigue), TSB (form), ramp rate,
    and VO2max estimate from Intervals.icu.
    """
    try:
        data = _get("/wellness", params={"oldest": _n_ago(2), "newest": _today()})
    except Exception as e:
        return json.dumps({"error": str(e)})

    if not data:
        return json.dumps({"error": "No data returned"})

    w = data[-1] if isinstance(data, list) else data
    return json.dumps({
        "date":      w.get("id"),
        "ctl":       w.get("ctl"),
        "atl":       w.get("atl"),
        "tsb":       round(float(w.get("ctl") or 0) - float(w.get("atl") or 0), 1),
        "ramp_rate": w.get("rampRate"),
        "vo2max":    w.get("VO2max"),
    }, indent=2, default=str)


@mcp.tool()
def intervals_get_recent_activities(count: int = 10) -> str:
    """
    Get recent activities from Intervals.icu with TSS, intensity factor,
    and power metrics. Aggregates data from Strava, Garmin, and other sources.
    count: number of activities (1-30, default 10)
    """
    count = min(max(1, count), 30)
    try:
        activities = _get("/activities", params={"oldest": _n_ago(90), "newest": _today()})
    except Exception as e:
        return json.dumps({"error": str(e)})

    recent = (activities[-count:] if len(activities) > count else activities)
    result = []
    for a in reversed(recent):
        result.append({
            "id":               a.get("id"),
            "name":             a.get("name"),
            "type":             a.get("type"),
            "date":             a.get("start_date_local", "")[:10],
            "duration_min":     round((a.get("elapsed_time") or 0) / 60, 1),
            "distance_km":      round((a.get("distance") or 0) / 1000, 1),
            "tss":              a.get("icu_training_load"),
            "intensity_factor": a.get("icu_intensity"),
            "avg_power_w":      a.get("average_watts"),
            "normalized_power_w": a.get("weighted_average_watts"),
        })
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def intervals_get_wellness(target_date: str = "") -> str:
    """
    Get wellness data for a date from Intervals.icu: HRV, resting HR, sleep,
    weight, mood, fatigue, soreness, and stress (1-5 scales).
    target_date: YYYY-MM-DD, defaults to today
    """
    target = target_date.strip() or _today()
    try:
        data = _get("/wellness", params={"oldest": target, "newest": target})
    except Exception as e:
        return json.dumps({"error": str(e)})

    if not data:
        return json.dumps({"date": target, "note": "No data for this date"})

    w = data[0] if isinstance(data, list) else data
    return json.dumps({
        "date":       w.get("id"),
        "hrv":        w.get("hrv"),
        "resting_hr": w.get("restingHR"),
        "sleep_min":  round((w.get("sleepSecs") or 0) / 60) if w.get("sleepSecs") else None,
        "weight_kg":  w.get("weight"),
        "mood":       w.get("mood"),
        "fatigue":    w.get("fatigue"),
        "soreness":   w.get("soreness"),
        "ctl":        w.get("ctl"),
        "atl":        w.get("atl"),
    }, indent=2, default=str)


@mcp.tool()
def intervals_get_power_curve() -> str:
    """
    Get best power curve from Intervals.icu: peak watts at 5s, 1min, 5min,
    20min, 60min for all-time and last 90 days.
    """
    try:
        data = _get("/power-curves", params={"curves": "all-time,last-90-days"})
    except Exception as e:
        return json.dumps({"error": str(e)})

    def extract(points, label):
        durations = {5: None, 60: None, 300: None, 1200: None, 3600: None}
        for p in (points or []):
            if p.get("secs") in durations:
                durations[p["secs"]] = {"watts": p.get("watts"), "w_kg": p.get("wkg")}
        return {"label": label, "5s": durations[5], "1min": durations[60],
                "5min": durations[300], "20min": durations[1200], "60min": durations[3600]}

    result = {}
    for c in (data if isinstance(data, list) else [data]):
        name = c.get("name", "curve")
        result[name] = extract(c.get("watts"), name)

    return json.dumps(result, indent=2, default=str)


if __name__ == "__main__":
    missing = [k for k in ("INTERVALS_ATHLETE_ID", "INTERVALS_API_KEY") if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"Missing env vars: {missing}. Copy .env.example to .env.")
    mcp.run()
