# Databricks notebook source
# MAGIC %md
# MAGIC # lib/tools_strava_live — Live Strava API Tools
# MAGIC
# MAGIC Gives the coaching agent direct access to fresh Strava data without
# MAGIC waiting for the ETL pipeline to run. Uses Databricks secrets (same
# MAGIC credentials as 01_strava_bronze.py).
# MAGIC
# MAGIC %run'd by 06_coaching_agent.py — do not run standalone.

# COMMAND ----------

import json
import time
import requests
from langchain.tools import tool

# Module-level token cache — survives across tool calls within a session
_strava_access_token: str | None = None
_strava_token_expires_at: float = 0


def _get_strava_token() -> str:
    global _strava_access_token, _strava_token_expires_at

    if _strava_access_token and _strava_token_expires_at > time.time() + 60:
        return _strava_access_token

    resp = requests.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id":     dbutils.secrets.get(scope="strava", key="client_id"),
            "client_secret": dbutils.secrets.get(scope="strava", key="client_secret"),
            "refresh_token": dbutils.secrets.get(scope="strava", key="refresh_token"),
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


# ── Tools ────────────────────────────────────────────────────────────────────

@tool
def strava_get_recent_activities(count: int = 10) -> str:
    """
    Pull the athlete's most recent activities LIVE from Strava — fresher than
    the Delta pipeline. Returns name, type, date, duration, distance, power,
    HR, elevation, suffer score, and whether power data exists.
    Use this when the athlete asks about rides from today or this week that
    may not have been ingested yet, or when you need the very latest data.
    count: number of activities to return (1-30, default 10)
    """
    count = min(max(1, count), 30)
    activities = _strava_get(
        "https://www.strava.com/api/v3/athlete/activities",
        params={"per_page": count, "page": 1},
    )

    result = []
    for a in activities:
        result.append({
            "activity_id":        a.get("id"),
            "name":               a.get("name"),
            "type":               a.get("sport_type") or a.get("type"),
            "date":               (a.get("start_date_local") or "")[:10],
            "duration_min":       round((a.get("elapsed_time") or 0) / 60, 1),
            "distance_km":        round((a.get("distance") or 0) / 1000, 1),
            "elevation_m":        round(a.get("total_elevation_gain") or 0),
            "avg_power_w":        a.get("average_watts"),
            "normalized_power_w": a.get("weighted_average_watts"),
            "avg_hr":             a.get("average_heartrate"),
            "max_hr":             a.get("max_heartrate"),
            "calories":           a.get("calories"),
            "suffer_score":       a.get("suffer_score"),
            "pr_count":           a.get("pr_count"),
            "has_power_data":     a.get("device_watts", False),
        })

    return json.dumps(result, indent=2)


@tool
def strava_get_activity_detail(activity_id: int) -> str:
    """
    Pull full details for a specific Strava activity LIVE: description, gear,
    perceived exertion, best efforts (peak power at 5s/1min/5min/20min),
    and top segment efforts with PR ranks.
    Use this when the athlete asks about a specific ride and you need more
    detail than get_recent_activities provides. You need the activity_id —
    call strava_get_recent_activities first to find it if needed.
    """
    a = _strava_get(f"https://www.strava.com/api/v3/activities/{activity_id}")

    best_efforts = {}
    for effort in (a.get("best_efforts") or []):
        best_efforts[effort.get("name", "")] = {
            "elapsed_sec": effort.get("elapsed_time"),
            "pr_rank":     effort.get("pr_rank"),
        }

    segments = []
    for se in (a.get("segment_efforts") or [])[:5]:
        seg = se.get("segment", {})
        segments.append({
            "name":        seg.get("name"),
            "elapsed_sec": se.get("elapsed_time"),
            "pr_rank":     se.get("pr_rank"),
            "kom_rank":    se.get("kom_rank"),
        })

    return json.dumps({
        "activity_id":        a.get("id"),
        "name":               a.get("name"),
        "description":        a.get("description"),
        "type":               a.get("sport_type") or a.get("type"),
        "date":               (a.get("start_date_local") or "")[:10],
        "duration_min":       round((a.get("elapsed_time") or 0) / 60, 1),
        "moving_time_min":    round((a.get("moving_time") or 0) / 60, 1),
        "distance_km":        round((a.get("distance") or 0) / 1000, 1),
        "elevation_m":        round(a.get("total_elevation_gain") or 0),
        "avg_power_w":        a.get("average_watts"),
        "normalized_power_w": a.get("weighted_average_watts"),
        "max_power_w":        a.get("max_watts"),
        "avg_hr":             a.get("average_heartrate"),
        "max_hr":             a.get("max_heartrate"),
        "avg_cadence":        a.get("average_cadence"),
        "calories":           a.get("calories"),
        "suffer_score":       a.get("suffer_score"),
        "perceived_exertion": a.get("perceived_exertion"),
        "gear":               (a.get("gear") or {}).get("name"),
        "pr_count":           a.get("pr_count"),
        "best_efforts":       best_efforts,
        "top_segments":       segments,
    }, indent=2, default=str)


@tool
def strava_get_activity_streams(activity_id: int) -> str:
    """
    Pull raw time-series data LIVE for a specific activity and return summary
    stats: average and peak power, normalized power, estimated 20-min peak,
    heart rate distribution, cadence. Useful for rides not yet in the Delta
    pipeline or when you need power analysis the ETL hasn't computed yet.
    Use this for deep physiological analysis of a specific ride.
    """
    streams = _strava_get(
        f"https://www.strava.com/api/v3/activities/{activity_id}/streams",
        params={
            "keys": "time,watts,heartrate,cadence,velocity_smooth",
            "key_by_type": "true",
        },
    )

    def safe(key) -> list:
        return [v for v in (streams.get(key, {}).get("data") or []) if v is not None]

    watts   = safe("watts")
    hr      = safe("heartrate")
    cadence = safe("cadence")
    times   = streams.get("time", {}).get("data") or []

    def pct(data, p):
        if not data:
            return None
        s = sorted(data)
        return s[int(len(s) * p / 100)]

    def best_n_min_avg(w, n_sec):
        if len(w) < n_sec:
            return None
        return round(max(sum(w[i:i+n_sec]) / n_sec for i in range(len(w) - n_sec)))

    def normalized_power(w):
        if len(w) < 30:
            return None
        rolling = [sum(w[i:i+30]) / 30 for i in range(len(w) - 30)]
        return round((sum(x**4 for x in rolling) / len(rolling)) ** 0.25)

    power_result = None
    if watts:
        peak_20m = best_n_min_avg(watts, 1200)
        power_result = {
            "avg_w":              round(sum(watts) / len(watts)),
            "max_w":              max(watts),
            "normalized_power_w": normalized_power(watts),
            "peak_20min_w":       peak_20m,
            "estimated_ftp_w":    round(peak_20m * 0.95) if peak_20m else None,
            "peak_5min_w":        best_n_min_avg(watts, 300),
            "peak_1min_w":        best_n_min_avg(watts, 60),
            "p90_w":              pct(watts, 90),
        }

    return json.dumps({
        "activity_id":  activity_id,
        "duration_sec": max(times) if times else 0,
        "power": power_result,
        "heart_rate": {
            "avg_bpm":          round(sum(hr) / len(hr)),
            "max_bpm":          max(hr),
            "p90_bpm":          pct(hr, 90),
            "sec_above_160bpm": sum(1 for h in hr if h > 160),
            "sec_above_170bpm": sum(1 for h in hr if h > 170),
        } if hr else None,
        "cadence": {
            "avg_rpm": round(sum(cadence) / len(cadence)),
            "max_rpm": max(cadence),
        } if cadence else None,
    }, indent=2)


@tool
def strava_get_athlete_stats() -> str:
    """
    Get the athlete's Strava training volume stats LIVE: ride count, distance,
    elevation, and moving time for the last 4 weeks, year-to-date, and all-time.
    Use this when the athlete asks about volume trends or lifetime totals.
    """
    profile = _strava_get("https://www.strava.com/api/v3/athlete")
    stats = _strava_get(f"https://www.strava.com/api/v3/athletes/{profile['id']}/stats")

    def fmt(s: dict) -> dict:
        return {
            "ride_count":  s.get("count"),
            "distance_km": round((s.get("distance") or 0) / 1000, 1),
            "elevation_m": round(s.get("elevation_gain") or 0),
            "time_hours":  round((s.get("moving_time") or 0) / 3600, 1),
        }

    return json.dumps({
        "recent_4_weeks":  fmt(stats.get("recent_ride_totals", {})),
        "year_to_date":    fmt(stats.get("ytd_ride_totals", {})),
        "all_time":        fmt(stats.get("all_ride_totals", {})),
        "biggest_ride_km": round((stats.get("biggest_ride_distance") or 0) / 1000, 1),
        "biggest_climb_m": stats.get("biggest_climb_elevation_gain"),
    }, indent=2)


# Exported list — parent notebook merges this with other tool lists
strava_live_tools = [
    strava_get_recent_activities,
    strava_get_activity_detail,
    strava_get_activity_streams,
    strava_get_athlete_stats,
]

print(f"  lib/tools_strava_live loaded: {len(strava_live_tools)} tools")
