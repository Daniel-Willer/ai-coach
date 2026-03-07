"""
Live Intervals.icu tools — ported from notebooks/lib/tools_intervals_live.py.
"""
from __future__ import annotations

import json
import requests
from datetime import date, timedelta
from langchain.tools import tool
from db.secrets import get_secret


def _today() -> str:
    return str(date.today())

def _n_days_ago(n: int) -> str:
    return str(date.today() - timedelta(days=n))


def _icu_get(path: str, params: dict | None = None) -> dict | list:
    athlete_id = get_secret("intervals", "athlete_id")
    api_key = get_secret("intervals", "api_key")
    resp = requests.get(
        f"https://intervals.icu/api/v1/athlete/{athlete_id}{path}",
        auth=("API_KEY", api_key),
        params=params or {},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


@tool
def intervals_get_fitness() -> str:
    """
    Get the athlete's current CTL, ATL, TSB, and VO2max from Intervals.icu —
    often more current than the Delta pipeline. Use as a fresh cross-check for
    training load when Delta data may be stale.
    """
    try:
        data = _icu_get("/wellness", params={"oldest": _n_days_ago(2), "newest": _today()})
        latest = data[-1] if isinstance(data, list) and data else (data or {})
        return json.dumps({
            "date": latest.get("id"),
            "ctl": latest.get("ctl"), "atl": latest.get("atl"),
            "tsb": round(float(latest.get("ctl") or 0) - float(latest.get("atl") or 0), 1),
            "ramp_rate": latest.get("rampRate"), "vo2max": latest.get("VO2max"),
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def intervals_get_recent_activities(count: int = 10) -> str:
    """
    Get recent activities from Intervals.icu with training load metrics.
    Aggregates from Strava, Garmin, and other platforms.
    Use this for a unified view of recent training across all platforms.
    """
    try:
        count = min(max(1, count), 30)
        activities = _icu_get("/activities", params={"oldest": _n_days_ago(90), "newest": _today()})
        recent = list(reversed((activities or [])[-count:]))
        return json.dumps([{
            "id": a.get("id"), "name": a.get("name"), "type": a.get("type"),
            "date": (a.get("start_date_local") or "")[:10],
            "duration_min": round((a.get("elapsed_time") or 0) / 60, 1),
            "distance_km": round((a.get("distance") or 0) / 1000, 1),
            "avg_power_w": a.get("average_watts"),
            "tss": a.get("icu_training_load"),
            "intensity_factor": a.get("icu_intensity"),
            "avg_hr": a.get("average_heartrate"),
        } for a in recent], indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def intervals_get_wellness(target_date: str = "") -> str:
    """
    Get wellness data from Intervals.icu: HRV, resting HR, sleep, weight, mood,
    fatigue, and soreness. Aggregates from Garmin, Whoop, and manual entries.
    Use this for a comprehensive recovery picture when planning training intensity.
    target_date: YYYY-MM-DD, defaults to today
    """
    target = target_date.strip() or _today()
    try:
        data = _icu_get("/wellness", params={"oldest": target, "newest": target})
        w = (data[0] if isinstance(data, list) else data) or {}
        return json.dumps({
            "date": w.get("id"), "hrv_rmssd": w.get("hrv"),
            "resting_hr": w.get("restingHR"),
            "sleep_min": round((w.get("sleepSecs") or 0) / 60) if w.get("sleepSecs") else None,
            "sleep_score": w.get("sleepScore"), "weight_kg": w.get("weight"),
            "mood": w.get("mood"), "fatigue": w.get("fatigue"),
            "soreness": w.get("soreness"), "ctl": w.get("ctl"), "atl": w.get("atl"),
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def intervals_get_power_curve() -> str:
    """
    Get the athlete's best power curve from Intervals.icu: peak watts at standard
    durations (5s, 1min, 5min, 20min, 60min) for all-time and last 90 days.
    Use this to assess power strengths and weaknesses across time periods.
    """
    try:
        curve = _icu_get("/power-curves", params={"curves": "all-time,last-90-days"})
        def extract(data, label):
            durations = {5: None, 60: None, 300: None, 1200: None, 3600: None}
            for point in (data or []):
                s = point.get("secs")
                if s in durations:
                    durations[s] = {"watts": point.get("watts"), "w_kg": round(float(point.get("wkg") or 0), 2) if point.get("wkg") else None}
            return {"label": label, "5s": durations[5], "1min": durations[60], "5min": durations[300], "20min": durations[1200], "60min": durations[3600]}
        result = {}
        if isinstance(curve, list):
            for c in curve:
                result[c.get("name", "unknown")] = extract(c.get("watts"), c.get("name"))
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


intervals_live_tools = [intervals_get_fitness, intervals_get_recent_activities, intervals_get_wellness, intervals_get_power_curve]
