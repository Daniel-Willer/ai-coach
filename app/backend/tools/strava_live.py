"""
Live Strava API tools — ported from notebooks/lib/tools_strava_live.py.
Replaces dbutils.secrets.get() with db.secrets.get_secret().
"""
from __future__ import annotations

import json
import time
import requests
from langchain.tools import tool
from db.secrets import get_secret

_strava_access_token: str | None = None
_strava_token_expires_at: float = 0


def _get_strava_token() -> str:
    global _strava_access_token, _strava_token_expires_at
    if _strava_access_token and _strava_token_expires_at > time.time() + 60:
        return _strava_access_token
    resp = requests.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id":     get_secret("strava", "client_id"),
            "client_secret": get_secret("strava", "client_secret"),
            "refresh_token": get_secret("strava", "refresh_token"),
            "grant_type":    "refresh_token",
        },
        timeout=10,
    )
    resp.raise_for_status()
    tokens = resp.json()
    _strava_access_token = tokens["access_token"]
    _strava_token_expires_at = tokens["expires_at"]
    return _strava_access_token


def _strava_get(url: str, params: dict | None = None) -> dict | list:
    for attempt in range(3):
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {_get_strava_token()}"},
            params=params or {},
            timeout=15,
        )
        if resp.status_code == 429:
            time.sleep(60)
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"Strava API failed after retries: {url}")


@tool
def strava_get_recent_activities(count: int = 10) -> str:
    """
    Pull the athlete's most recent activities LIVE from Strava — fresher than
    the Delta pipeline. Use this when the athlete asks about rides from today
    or this week that may not have been ingested yet.
    count: number of activities to return (1-30, default 10)
    """
    try:
        count = min(max(1, count), 30)
        activities = _strava_get(
            "https://www.strava.com/api/v3/athlete/activities",
            params={"per_page": count, "page": 1},
        )
        result = [{
            "activity_id": a.get("id"),
            "name": a.get("name"),
            "type": a.get("sport_type") or a.get("type"),
            "date": (a.get("start_date_local") or "")[:10],
            "duration_min": round((a.get("elapsed_time") or 0) / 60, 1),
            "distance_km": round((a.get("distance") or 0) / 1000, 1),
            "elevation_m": round(a.get("total_elevation_gain") or 0),
            "avg_power_w": a.get("average_watts"),
            "normalized_power_w": a.get("weighted_average_watts"),
            "avg_hr": a.get("average_heartrate"),
            "suffer_score": a.get("suffer_score"),
            "pr_count": a.get("pr_count"),
            "has_power_data": a.get("device_watts", False),
        } for a in activities]
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def strava_get_activity_detail(activity_id: int) -> str:
    """
    Pull full details for a specific Strava activity LIVE: description, gear,
    perceived exertion, best efforts (peak power), and top segment efforts.
    Use this when the athlete asks about a specific ride in detail.
    """
    try:
        a = _strava_get(f"https://www.strava.com/api/v3/activities/{activity_id}")
        best_efforts = {e.get("name", ""): {"elapsed_sec": e.get("elapsed_time"), "pr_rank": e.get("pr_rank")} for e in (a.get("best_efforts") or [])}
        segments = [{"name": se.get("segment", {}).get("name"), "elapsed_sec": se.get("elapsed_time"), "pr_rank": se.get("pr_rank")} for se in (a.get("segment_efforts") or [])[:5]]
        return json.dumps({
            "activity_id": a.get("id"), "name": a.get("name"),
            "date": (a.get("start_date_local") or "")[:10],
            "duration_min": round((a.get("elapsed_time") or 0) / 60, 1),
            "distance_km": round((a.get("distance") or 0) / 1000, 1),
            "elevation_m": round(a.get("total_elevation_gain") or 0),
            "avg_power_w": a.get("average_watts"),
            "normalized_power_w": a.get("weighted_average_watts"),
            "avg_hr": a.get("average_heartrate"),
            "perceived_exertion": a.get("perceived_exertion"),
            "suffer_score": a.get("suffer_score"),
            "pr_count": a.get("pr_count"),
            "best_efforts": best_efforts, "top_segments": segments,
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def strava_get_activity_streams(activity_id: int) -> str:
    """
    Pull raw time-series data LIVE for a specific activity: avg/peak power,
    normalized power, estimated 20-min peak, HR distribution, cadence.
    Use this for deep power analysis of a specific ride.
    """
    try:
        streams = _strava_get(
            f"https://www.strava.com/api/v3/activities/{activity_id}/streams",
            params={"keys": "time,watts,heartrate,cadence", "key_by_type": "true"},
        )
        def safe(key): return [v for v in (streams.get(key, {}).get("data") or []) if v is not None]
        watts, hr, cadence = safe("watts"), safe("heartrate"), safe("cadence")
        times = streams.get("time", {}).get("data") or []

        def best_n(w, n):
            return round(max(sum(w[i:i+n]) / n for i in range(len(w) - n))) if len(w) >= n else None

        def np_calc(w):
            if len(w) < 30: return None
            rolling = [sum(w[i:i+30]) / 30 for i in range(len(w) - 30)]
            return round((sum(x**4 for x in rolling) / len(rolling)) ** 0.25)

        power = None
        if watts:
            p20 = best_n(watts, 1200)
            power = {"avg_w": round(sum(watts) / len(watts)), "max_w": max(watts),
                     "normalized_power_w": np_calc(watts), "peak_20min_w": p20,
                     "estimated_ftp_w": round(p20 * 0.95) if p20 else None,
                     "peak_5min_w": best_n(watts, 300), "peak_1min_w": best_n(watts, 60)}

        return json.dumps({
            "activity_id": activity_id, "duration_sec": max(times) if times else 0,
            "power": power,
            "heart_rate": {"avg_bpm": round(sum(hr)/len(hr)), "max_bpm": max(hr)} if hr else None,
            "cadence": {"avg_rpm": round(sum(cadence)/len(cadence))} if cadence else None,
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def strava_get_athlete_stats() -> str:
    """
    Get the athlete's Strava training volume stats LIVE: ride count, distance,
    elevation, and moving time for recent 4 weeks, year-to-date, and all-time.
    Use this when the athlete asks about volume trends or lifetime totals.
    """
    try:
        profile = _strava_get("https://www.strava.com/api/v3/athlete")
        stats = _strava_get(f"https://www.strava.com/api/v3/athletes/{profile['id']}/stats")
        def fmt(s): return {"ride_count": s.get("count"), "distance_km": round((s.get("distance") or 0) / 1000, 1), "elevation_m": round(s.get("elevation_gain") or 0), "time_hours": round((s.get("moving_time") or 0) / 3600, 1)}
        return json.dumps({"recent_4_weeks": fmt(stats.get("recent_ride_totals", {})), "year_to_date": fmt(stats.get("ytd_ride_totals", {})), "all_time": fmt(stats.get("all_ride_totals", {}))}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


strava_live_tools = [strava_get_recent_activities, strava_get_activity_detail, strava_get_activity_streams, strava_get_athlete_stats]
