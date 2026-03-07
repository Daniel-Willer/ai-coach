"""
Strava MCP Server
-----------------
Exposes Strava API as tools for the AI cycling coach agent.

Setup:
  cd mcp/strava
  pip install -r requirements.txt
  cp .env.example .env        # fill in your credentials
  python server.py             # or: mcp dev server.py

Credentials (in mcp/strava/.env):
  STRAVA_CLIENT_ID
  STRAVA_CLIENT_SECRET
  STRAVA_REFRESH_TOKEN        # must have activity:read_all scope
"""

import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Load .env from the same directory as this file
load_dotenv(Path(__file__).parent / ".env")

mcp = FastMCP("strava-coach")

# ── Token cache (module-level, survives across tool calls) ───────────────────
_access_token: str | None = None
_token_expires_at: float = 0


def _get_access_token() -> str:
    global _access_token, _token_expires_at

    # Reuse cached token if still valid (with 60s buffer)
    if _access_token and _token_expires_at > time.time() + 60:
        return _access_token

    resp = requests.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id":     os.environ["STRAVA_CLIENT_ID"],
            "client_secret": os.environ["STRAVA_CLIENT_SECRET"],
            "refresh_token": os.environ["STRAVA_REFRESH_TOKEN"],
            "grant_type":    "refresh_token",
        },
        timeout=10,
    )
    resp.raise_for_status()
    tokens = resp.json()
    _access_token = tokens["access_token"]
    _token_expires_at = tokens["expires_at"]
    return _access_token


def _get(url: str, params: dict | None = None) -> dict | list:
    """GET with automatic token refresh and rate-limit retry."""
    for attempt in range(3):
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {_get_access_token()}"},
            params=params or {},
            timeout=15,
        )
        if resp.status_code == 429:
            # Rate limited — back off and retry
            wait = int(resp.headers.get("X-RateLimit-Limit", 60))
            time.sleep(min(wait, 60))
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"Strava API failed after retries: {url}")


# ── Tools ────────────────────────────────────────────────────────────────────

@mcp.tool()
def strava_get_athlete_profile() -> str:
    """
    Get the authenticated athlete's Strava profile: name, FTP, weight, city,
    country. Returns fresh data direct from Strava (not from Delta tables).
    Use this to get the athlete's current FTP or weight as Strava has it.
    """
    a = _get("https://www.strava.com/api/v3/athlete")
    return json.dumps({
        "athlete_id": a.get("id"),
        "name":       f"{a.get('firstname', '')} {a.get('lastname', '')}".strip(),
        "ftp_w":      a.get("ftp"),
        "weight_kg":  a.get("weight"),
        "city":       a.get("city"),
        "country":    a.get("country"),
        "sex":        a.get("sex"),
    }, indent=2)


@mcp.tool()
def strava_get_athlete_stats() -> str:
    """
    Get the athlete's Strava training volume statistics: ride count, distance,
    elevation, and time for the last 4 weeks, year-to-date, and all-time.
    Use this for big-picture volume context or when the athlete asks about
    lifetime totals.
    """
    profile = _get("https://www.strava.com/api/v3/athlete")
    stats = _get(f"https://www.strava.com/api/v3/athletes/{profile['id']}/stats")

    def fmt(s: dict) -> dict:
        return {
            "ride_count":    s.get("count"),
            "distance_km":   round((s.get("distance") or 0) / 1000, 1),
            "elevation_m":   round(s.get("elevation_gain") or 0),
            "time_hours":    round((s.get("moving_time") or 0) / 3600, 1),
        }

    return json.dumps({
        "recent_4_weeks":   fmt(stats.get("recent_ride_totals", {})),
        "year_to_date":     fmt(stats.get("ytd_ride_totals", {})),
        "all_time":         fmt(stats.get("all_ride_totals", {})),
        "biggest_ride_km":  round((stats.get("biggest_ride_distance") or 0) / 1000, 1),
        "biggest_climb_m":  stats.get("biggest_climb_elevation_gain"),
    }, indent=2)


@mcp.tool()
def strava_get_recent_activities(count: int = 10) -> str:
    """
    Get the athlete's most recent Strava activities with key metrics: name, type,
    date, duration, distance, power, heart rate, elevation, suffer score.
    Returns fresh data direct from Strava.
    Use this when the athlete asks about recent rides or you need up-to-date
    activity data not yet in the Delta pipeline.
    count: number of activities to return (1-50, default 10)
    """
    count = min(max(1, count), 50)
    activities = _get(
        "https://www.strava.com/api/v3/athlete/activities",
        params={"per_page": count, "page": 1},
    )

    result = []
    for a in activities:
        result.append({
            "activity_id":          a.get("id"),
            "name":                 a.get("name"),
            "type":                 a.get("sport_type") or a.get("type"),
            "date":                 (a.get("start_date_local") or "")[:10],
            "duration_min":         round((a.get("elapsed_time") or 0) / 60, 1),
            "distance_km":          round((a.get("distance") or 0) / 1000, 1),
            "elevation_m":          round(a.get("total_elevation_gain") or 0),
            "avg_power_w":          a.get("average_watts"),
            "normalized_power_w":   a.get("weighted_average_watts"),
            "avg_hr":               a.get("average_heartrate"),
            "max_hr":               a.get("max_heartrate"),
            "calories":             a.get("calories"),
            "suffer_score":         a.get("suffer_score"),
            "pr_count":             a.get("pr_count"),
            "has_power_data":       a.get("device_watts", False),
        })

    return json.dumps(result, indent=2)


@mcp.tool()
def strava_get_activity(activity_id: int) -> str:
    """
    Get full details for a specific Strava activity by ID: description, gear,
    perceived exertion, best efforts (peak power at standard durations like
    5s/1min/5min/20min), and top segment efforts with PR ranks.
    Call strava_get_recent_activities first to find the activity_id if needed.
    """
    a = _get(f"https://www.strava.com/api/v3/activities/{activity_id}")

    # Peak power best efforts (5s, 1min, 5min, 20min etc.)
    best_efforts = {}
    for effort in (a.get("best_efforts") or []):
        name = effort.get("name", "")
        best_efforts[name] = {
            "elapsed_sec": effort.get("elapsed_time"),
            "pr_rank":     effort.get("pr_rank"),
        }

    # Top segment efforts
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
        "activity_id":          a.get("id"),
        "name":                 a.get("name"),
        "description":          a.get("description"),
        "type":                 a.get("sport_type") or a.get("type"),
        "date":                 (a.get("start_date_local") or "")[:10],
        "duration_min":         round((a.get("elapsed_time") or 0) / 60, 1),
        "moving_time_min":      round((a.get("moving_time") or 0) / 60, 1),
        "distance_km":          round((a.get("distance") or 0) / 1000, 1),
        "elevation_m":          round(a.get("total_elevation_gain") or 0),
        "avg_power_w":          a.get("average_watts"),
        "normalized_power_w":   a.get("weighted_average_watts"),
        "max_power_w":          a.get("max_watts"),
        "avg_hr":               a.get("average_heartrate"),
        "max_hr":               a.get("max_heartrate"),
        "avg_cadence":          a.get("average_cadence"),
        "calories":             a.get("calories"),
        "suffer_score":         a.get("suffer_score"),
        "perceived_exertion":   a.get("perceived_exertion"),
        "gear":                 (a.get("gear") or {}).get("name"),
        "pr_count":             a.get("pr_count"),
        "best_efforts":         best_efforts,
        "top_segments":         segments,
    }, indent=2, default=str)


@mcp.tool()
def strava_get_activity_streams(activity_id: int) -> str:
    """
    Get time-series analysis for a specific activity: power distribution,
    heart rate distribution, cadence stats, and estimated metrics like
    normalized power and 20-min peak power. Returns summary stats (not raw
    data points) to keep the response focused and useful.
    Use this for deep physiological analysis of a specific ride.
    """
    streams = _get(
        f"https://www.strava.com/api/v3/activities/{activity_id}/streams",
        params={
            "keys": "time,watts,heartrate,cadence,velocity_smooth,altitude,moving",
            "key_by_type": "true",
        },
    )

    def safe(key) -> list:
        return [v for v in (streams.get(key, {}).get("data") or []) if v is not None]

    watts   = safe("watts")
    hr      = safe("heartrate")
    cadence = safe("cadence")
    times   = streams.get("time", {}).get("data") or []
    duration_sec = max(times) if times else 0

    def pct(data, p):
        if not data:
            return None
        s = sorted(data)
        return s[int(len(s) * p / 100)]

    # Normalized power: 30s rolling average raised to 4th power
    def normalized_power(w_list):
        if len(w_list) < 30:
            return None
        rolling = [sum(w_list[i:i+30]) / 30 for i in range(len(w_list) - 30)]
        return round((sum(x**4 for x in rolling) / len(rolling)) ** 0.25)

    # Best 20-min average power
    def best_n_min(w_list, n_sec=1200):
        if len(w_list) < n_sec:
            return None
        return round(max(sum(w_list[i:i+n_sec]) / n_sec for i in range(len(w_list) - n_sec)))

    power_result = None
    if watts:
        np_w = normalized_power(watts)
        peak_20m = best_n_min(watts)
        power_result = {
            "avg_w":              round(sum(watts) / len(watts)),
            "max_w":              max(watts),
            "normalized_power_w": np_w,
            "peak_20min_w":       peak_20m,
            "estimated_ftp_w":    round(peak_20m * 0.95) if peak_20m else None,
            "p90_w":              pct(watts, 90),
            "p50_w":              pct(watts, 50),
            "sec_above_300w":     sum(1 for w in watts if w > 300),
            "sec_above_400w":     sum(1 for w in watts if w > 400),
        }

    hr_result = None
    if hr:
        hr_result = {
            "avg_bpm":             round(sum(hr) / len(hr)),
            "max_bpm":             max(hr),
            "p90_bpm":             pct(hr, 90),
            "sec_above_160bpm":    sum(1 for h in hr if h > 160),
            "sec_above_170bpm":    sum(1 for h in hr if h > 170),
        }

    return json.dumps({
        "activity_id":  activity_id,
        "duration_sec": duration_sec,
        "data_points":  len(times),
        "power":        power_result,
        "heart_rate":   hr_result,
        "cadence": {
            "avg_rpm": round(sum(cadence) / len(cadence)),
            "max_rpm": max(cadence),
        } if cadence else None,
    }, indent=2)


@mcp.tool()
def strava_get_athlete_zones() -> str:
    """
    Get the athlete's configured heart rate and power zones from Strava.
    Returns zone boundaries as set in the athlete's Strava settings.
    Use this to compare Strava's zones against the coaching agent's FTP-based zones.
    """
    zones = _get("https://www.strava.com/api/v3/athlete/zones")

    hr_zones = [
        {"min": z.get("min"), "max": z.get("max")}
        for z in (zones.get("heart_rate", {}).get("zones") or [])
    ]
    power_zones = [
        {"min": z.get("min"), "max": z.get("max")}
        for z in (zones.get("power", {}).get("zones") or [])
    ]

    return json.dumps({
        "heart_rate_zones": hr_zones,
        "power_zones":      power_zones,
        "note": "Values of -1 mean no upper limit. Power zones require FTP set in Strava settings.",
    }, indent=2)


@mcp.tool()
def strava_get_starred_segments() -> str:
    """
    Get the athlete's starred Strava segments — saved climbs, sprints, or
    benchmark efforts. Returns distance, elevation, grade, and effort counts.
    Use this to find segments the athlete cares about for tracking progress.
    """
    segments = _get(
        "https://www.strava.com/api/v3/segments/starred",
        params={"per_page": 20},
    )

    result = []
    for s in segments:
        result.append({
            "segment_id":      s.get("id"),
            "name":            s.get("name"),
            "distance_km":     round((s.get("distance") or 0) / 1000, 2),
            "elevation_m":     s.get("total_elevation_gain"),
            "avg_grade_pct":   s.get("average_grade"),
            "max_grade_pct":   s.get("maximum_grade"),
            "climb_category":  s.get("climb_category_desc") or s.get("climb_category"),
            "effort_count":    s.get("effort_count"),
        })

    return json.dumps(result, indent=2, default=str)


# ── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    missing = [
        k for k in ("STRAVA_CLIENT_ID", "STRAVA_CLIENT_SECRET", "STRAVA_REFRESH_TOKEN")
        if not os.environ.get(k)
    ]
    if missing:
        raise RuntimeError(
            f"Missing environment variables: {missing}\n"
            f"Copy mcp/strava/.env.example to mcp/strava/.env and fill in your credentials."
        )
    mcp.run()
