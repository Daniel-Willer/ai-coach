# Databricks notebook source
# MAGIC %md
# MAGIC # lib/tools_garmin_live — Live Garmin Connect Tools
# MAGIC
# MAGIC Pulls fresh recovery and wellness data directly from Garmin Connect:
# MAGIC sleep, HRV, body battery, stress, resting HR.
# MAGIC Uses Databricks secrets scope `garmin` (same as 00b_garmin_bronze_v2).
# MAGIC
# MAGIC %run'd by 06_coaching_agent.py — do not run standalone.

# COMMAND ----------

import json
from datetime import date, datetime, timedelta
from langchain.tools import tool

# Module-level client cache — login once per session
_garmin_client = None


def _get_garmin_client():
    global _garmin_client
    if _garmin_client is not None:
        return _garmin_client

    from garminconnect import Garmin
    username = dbutils.secrets.get(scope="garmin", key="username")
    password = dbutils.secrets.get(scope="garmin", key="password")
    client = Garmin(username, password)
    client.login()
    _garmin_client = client
    return client


def _today() -> str:
    return str(date.today())


def _yesterday() -> str:
    return str(date.today() - timedelta(days=1))


# ── Tools ────────────────────────────────────────────────────────────────────

@tool
def garmin_get_sleep(target_date: str = "") -> str:
    """
    Get sleep data from Garmin Connect for a given date: total sleep duration,
    sleep score, time in each stage (deep, light, REM, awake), and overnight
    HRV summary. Empty target_date defaults to last night.
    Use this when the athlete mentions sleep quality, asks if they're recovered,
    or when you need to factor sleep into training recommendations.
    target_date: YYYY-MM-DD format, defaults to yesterday
    """
    target = target_date.strip() or _yesterday()
    client = _get_garmin_client()

    try:
        sleep = client.get_sleep_data(target)
    except Exception as e:
        return json.dumps({"error": str(e), "date": target})

    daily = sleep.get("dailySleepDTO", {}) or {}
    hrv   = sleep.get("hrvData", {}) or {}

    def mins(sec):
        return round((sec or 0) / 60) if sec else None

    return json.dumps({
        "date":                  target,
        "sleep_score":           daily.get("sleepScores", {}).get("overall", {}).get("value") if daily.get("sleepScores") else None,
        "total_sleep_min":       mins(daily.get("sleepTimeSeconds")),
        "deep_sleep_min":        mins(daily.get("deepSleepSeconds")),
        "light_sleep_min":       mins(daily.get("lightSleepSeconds")),
        "rem_sleep_min":         mins(daily.get("remSleepSeconds")),
        "awake_min":             mins(daily.get("awakeSleepSeconds")),
        "avg_overnight_hrv":     hrv.get("lastNight"),
        "hrv_status":            hrv.get("hrvSummary", {}).get("status") if hrv.get("hrvSummary") else None,
        "restless_moments":      daily.get("restlessMomentsCount"),
        "avg_spo2":              daily.get("averageSpO2Value"),
        "interpretation": {
            "sleep_score": "< 60: poor | 60-79: fair | 80+: good",
            "hrv": "Higher overnight HRV = better recovery. Trend matters more than single night.",
        }
    }, indent=2, default=str)


@tool
def garmin_get_daily_stats(target_date: str = "") -> str:
    """
    Get Garmin daily wellness stats: body battery start/end, average stress score,
    resting heart rate, steps, calories, and intensity minutes.
    Use this to assess the athlete's current recovery state, especially body battery
    and stress score, before recommending workout intensity.
    target_date: YYYY-MM-DD format, defaults to today
    """
    target = target_date.strip() or _today()
    client = _get_garmin_client()

    try:
        stats = client.get_stats(target)
    except Exception as e:
        return json.dumps({"error": str(e), "date": target})

    return json.dumps({
        "date":                    target,
        "body_battery_highest":    stats.get("bodyBatteryHighestValue"),
        "body_battery_lowest":     stats.get("bodyBatteryLowestValue"),
        "body_battery_most_recent": stats.get("bodyBatteryMostRecentValue"),
        "resting_hr":              stats.get("restingHeartRate"),
        "avg_stress":              stats.get("averageStressLevel"),
        "max_stress":              stats.get("maxStressLevel"),
        "steps":                   stats.get("totalSteps"),
        "active_calories":         stats.get("activeKilocalories"),
        "total_calories":          stats.get("totalKilocalories"),
        "intensity_minutes":       stats.get("vigorousIntensityMinutes", 0) + stats.get("moderateIntensityMinutes", 0),
        "interpretation": {
            "body_battery": "0-25: very low (rest) | 26-50: low | 51-75: medium | 76-100: high (ready to train)",
            "stress": "0-25: rest | 26-50: low stress | 51-75: medium | 76-100: high stress",
        }
    }, indent=2, default=str)


@tool
def garmin_get_hrv_status() -> str:
    """
    Get the athlete's HRV (Heart Rate Variability) status from Garmin: last
    night's HRV, 5-day average, baseline, and Garmin's status classification
    (Balanced / Unbalanced / Low). HRV is one of the best recovery indicators.
    Use this when assessing readiness for hard training or when the athlete
    asks about recovery or HRV specifically.
    """
    client = _get_garmin_client()

    try:
        hrv_data = client.get_hrv_data(_today())
    except Exception as e:
        return json.dumps({"error": str(e)})

    summary = hrv_data.get("hrvSummary", {}) or {}
    readings = hrv_data.get("hrvReadings", []) or []

    last_5 = [r.get("hrvValue") for r in readings[-5:] if r.get("hrvValue")]

    return json.dumps({
        "status":           summary.get("status"),
        "last_night_hrv":   summary.get("lastNight"),
        "baseline_low":     summary.get("baselineLowUpper"),
        "baseline_high":    summary.get("baselineHighUpper"),
        "weekly_avg":       summary.get("weeklyAvg"),
        "last_5_nights":    last_5,
        "interpretation": {
            "Balanced":    "HRV within your normal range — body is adapted",
            "Unbalanced":  "HRV outside normal — moderate training only",
            "Low":         "HRV significantly below baseline — rest or easy only",
            "Poor":        "Very low HRV — consider full rest day",
        }
    }, indent=2, default=str)


@tool
def garmin_get_body_battery_today() -> str:
    """
    Get the athlete's Garmin Body Battery readings throughout today: current
    level, peak so far, and a timeline of charge/drain events. Body battery
    combines sleep, HRV, stress, and activity into a 0-100 readiness score.
    Use this for a quick real-time readiness check before prescribing workouts.
    """
    client = _get_garmin_client()

    try:
        bb_data = client.get_body_battery(_today(), _today())
    except Exception as e:
        return json.dumps({"error": str(e)})

    if not bb_data:
        return json.dumps({"error": "No body battery data for today yet"})

    readings = []
    for entry in (bb_data or []):
        for event in (entry.get("bodyBatteryValuesArray") or []):
            if event and len(event) >= 2:
                readings.append({"time_ms": event[0], "level": event[1]})

    current = readings[-1]["level"] if readings else None
    peak    = max(r["level"] for r in readings) if readings else None
    low     = min(r["level"] for r in readings) if readings else None

    return json.dumps({
        "current_level": current,
        "peak_today":    peak,
        "low_today":     low,
        "interpretation": (
            "Ready to train hard" if current and current >= 75 else
            "Moderate training OK" if current and current >= 50 else
            "Easy training only" if current and current >= 25 else
            "Rest day recommended"
        ) if current else "No data",
    }, indent=2)


# Exported list
garmin_live_tools = [
    garmin_get_sleep,
    garmin_get_daily_stats,
    garmin_get_hrv_status,
    garmin_get_body_battery_today,
]

print(f"  lib/tools_garmin_live loaded: {len(garmin_live_tools)} tools")
