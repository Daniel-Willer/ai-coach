# Databricks notebook source
# MAGIC %md
# MAGIC # lib/tools_intervals_live — Live Intervals.icu Tools
# MAGIC
# MAGIC Intervals.icu is a free training analytics platform with an excellent API.
# MAGIC Provides CTL/ATL/TSB, power curves, wellness data, and structured workouts.
# MAGIC
# MAGIC **Secret setup (one-time):**
# MAGIC   databricks secrets put --scope intervals --key api_key
# MAGIC   databricks secrets put --scope intervals --key athlete_id
# MAGIC
# MAGIC Get your API key: intervals.icu → Settings → API
# MAGIC Get your athlete_id from your profile URL: intervals.icu/athletes/iXXXXXX
# MAGIC
# MAGIC %run'd by 06_coaching_agent.py — do not run standalone.

# COMMAND ----------

import json
import requests
from datetime import date, timedelta
from langchain.tools import tool


def _icu_get(path: str, params: dict | None = None) -> dict | list:
    athlete_id = dbutils.secrets.get(scope="intervals", key="athlete_id")
    api_key    = dbutils.secrets.get(scope="intervals", key="api_key")

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


def _n_days_ago(n: int) -> str:
    return str(date.today() - timedelta(days=n))


# ── Tools ────────────────────────────────────────────────────────────────────

@tool
def intervals_get_fitness() -> str:
    """
    Get the athlete's current CTL (fitness), ATL (fatigue), TSB (form), and
    VO2max estimate from Intervals.icu — often more current than the Delta
    pipeline. Also returns ramp rate and training load status.
    Use this as a fresh source for training load when Delta data may be stale.
    """
    try:
        data = _icu_get("/wellness", params={"oldest": _n_days_ago(2), "newest": _today()})
    except Exception as e:
        return json.dumps({"error": str(e)})

    if not data:
        return json.dumps({"error": "No wellness data returned"})

    # Most recent day
    latest = data[-1] if isinstance(data, list) else data

    return json.dumps({
        "date":            latest.get("id"),
        "ctl":             latest.get("ctl"),
        "atl":             latest.get("atl"),
        "tsb":             round(float(latest.get("ctl") or 0) - float(latest.get("atl") or 0), 1),
        "rampRate":        latest.get("rampRate"),
        "ctlLoad":         latest.get("ctlLoad"),
        "atlLoad":         latest.get("atlLoad"),
        "vo2max":          latest.get("VO2max"),
        "interpretation": {
            "tsb": "TSB > +5: fresh | -10 to +5: neutral | -30 to -10: productive | < -30: overreached",
            "ramp_rate": "Ideal CTL ramp: +3 to +8 per week. Above +10 = injury risk.",
        }
    }, indent=2, default=str)


@tool
def intervals_get_recent_activities(count: int = 10) -> str:
    """
    Get recent activities from Intervals.icu with training load metrics:
    TSS, intensity factor, training load, pace/power, and compliance vs planned.
    Intervals.icu aggregates data from Strava, Garmin, and other sources.
    Use this for a unified view of recent training across all platforms.
    count: number of activities (default 10, max 30)
    """
    count = min(max(1, count), 30)
    try:
        activities = _icu_get(
            "/activities",
            params={"oldest": _n_days_ago(90), "newest": _today()}
        )
    except Exception as e:
        return json.dumps({"error": str(e)})

    if not activities:
        return json.dumps({"activities": [], "note": "No activities found"})

    recent = activities[-count:] if len(activities) > count else activities
    result = []
    for a in reversed(recent):
        result.append({
            "id":              a.get("id"),
            "name":            a.get("name"),
            "type":            a.get("type"),
            "date":            a.get("start_date_local", "")[:10],
            "duration_min":    round((a.get("elapsed_time") or 0) / 60, 1),
            "distance_km":     round((a.get("distance") or 0) / 1000, 1),
            "avg_power_w":     a.get("average_watts"),
            "normalized_power_w": a.get("weighted_average_watts"),
            "tss":             a.get("icu_training_load"),
            "intensity_factor": a.get("icu_intensity"),
            "avg_hr":          a.get("average_heartrate"),
            "elevation_m":     a.get("total_elevation_gain"),
        })

    return json.dumps(result, indent=2, default=str)


@tool
def intervals_get_wellness(target_date: str = "") -> str:
    """
    Get wellness data from Intervals.icu for a specific date: HRV, resting HR,
    sleep duration, sleep score, weight, mood, fatigue, and soreness.
    Intervals.icu aggregates wellness from Garmin, Whoop, and manual entries.
    Use this for a comprehensive recovery picture when planning training intensity.
    target_date: YYYY-MM-DD, defaults to today
    """
    target = target_date.strip() or _today()
    try:
        data = _icu_get("/wellness", params={"oldest": target, "newest": target})
    except Exception as e:
        return json.dumps({"error": str(e), "date": target})

    if not data:
        return json.dumps({"date": target, "note": "No wellness data for this date"})

    w = data[0] if isinstance(data, list) else data

    return json.dumps({
        "date":          w.get("id"),
        "hrv_rmssd":     w.get("hrv"),
        "hrv_sdnn":      w.get("hrvSDNN"),
        "resting_hr":    w.get("restingHR"),
        "sleep_sec":     w.get("sleepSecs"),
        "sleep_min":     round((w.get("sleepSecs") or 0) / 60) if w.get("sleepSecs") else None,
        "sleep_score":   w.get("sleepScore"),
        "weight_kg":     w.get("weight"),
        "mood":          w.get("mood"),       # 1-5 subjective scale
        "fatigue":       w.get("fatigue"),    # 1-5
        "soreness":      w.get("soreness"),   # 1-5
        "stress":        w.get("stress"),     # 1-5
        "motivation":    w.get("motivation"), # 1-5
        "spO2":          w.get("spO2"),
        "ctl":           w.get("ctl"),
        "atl":           w.get("atl"),
    }, indent=2, default=str)


@tool
def intervals_get_power_curve() -> str:
    """
    Get the athlete's best power curve from Intervals.icu across all time and
    last 90 days: peak watts at standard durations (5s, 1min, 5min, 20min, 60min)
    with W/kg if weight is available. More comprehensive than a single activity.
    Use this to assess power strengths/weaknesses and FTP estimation.
    """
    try:
        curve = _icu_get("/power-curves", params={"curves": "all-time,last-90-days"})
    except Exception as e:
        return json.dumps({"error": str(e)})

    def extract_curve(data, label):
        if not data:
            return None
        # Intervals returns array of {secs, watts, wkg}
        durations = {5: None, 60: None, 300: None, 1200: None, 3600: None}
        for point in (data or []):
            secs = point.get("secs")
            if secs in durations:
                durations[secs] = {
                    "watts": point.get("watts"),
                    "w_kg":  round(float(point.get("wkg") or 0), 2) if point.get("wkg") else None,
                }
        return {
            "label":  label,
            "5s":     durations[5],
            "1min":   durations[60],
            "5min":   durations[300],
            "20min":  durations[1200],
            "60min":  durations[3600],
        }

    result = {}
    if isinstance(curve, list):
        for c in curve:
            label = c.get("name", "unknown")
            result[label] = extract_curve(c.get("watts"), label)
    elif isinstance(curve, dict):
        result["curve"] = extract_curve(curve.get("watts"), "current")

    return json.dumps(result, indent=2, default=str)


# Exported list
intervals_live_tools = [
    intervals_get_fitness,
    intervals_get_recent_activities,
    intervals_get_wellness,
    intervals_get_power_curve,
]

print(f"  lib/tools_intervals_live loaded: {len(intervals_live_tools)} tools")
