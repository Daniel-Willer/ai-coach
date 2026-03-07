"""
Garmin Connect MCP Server
-------------------------
Exposes Garmin sleep, HRV, body battery, and daily wellness as tools.

Setup:
  cd mcp/garmin
  pip install -r requirements.txt
  cp .env.example .env   # fill in Garmin username + password
  python server.py
"""

import json
import os
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv(Path(__file__).parent / ".env")

mcp = FastMCP("garmin-coach")

_client = None


def _get_client():
    global _client
    if _client:
        return _client
    from garminconnect import Garmin
    c = Garmin(os.environ["GARMIN_USERNAME"], os.environ["GARMIN_PASSWORD"])
    c.login()
    _client = c
    return c


def _today() -> str:
    return str(date.today())

def _yesterday() -> str:
    return str(date.today() - timedelta(days=1))


@mcp.tool()
def garmin_get_sleep(target_date: str = "") -> str:
    """
    Get sleep data from Garmin Connect: sleep score, duration, sleep stages
    (deep/light/REM/awake), and overnight HRV. Defaults to last night.
    target_date: YYYY-MM-DD, defaults to yesterday
    """
    target = target_date.strip() or _yesterday()
    client = _get_client()
    try:
        sleep = client.get_sleep_data(target)
    except Exception as e:
        return json.dumps({"error": str(e), "date": target})

    daily = sleep.get("dailySleepDTO", {}) or {}
    hrv   = sleep.get("hrvData", {}) or {}

    def mins(s):
        return round((s or 0) / 60) if s else None

    return json.dumps({
        "date":             target,
        "sleep_score":      (daily.get("sleepScores") or {}).get("overall", {}).get("value"),
        "total_sleep_min":  mins(daily.get("sleepTimeSeconds")),
        "deep_min":         mins(daily.get("deepSleepSeconds")),
        "light_min":        mins(daily.get("lightSleepSeconds")),
        "rem_min":          mins(daily.get("remSleepSeconds")),
        "awake_min":        mins(daily.get("awakeSleepSeconds")),
        "avg_hrv":          hrv.get("lastNight"),
        "hrv_status":       (hrv.get("hrvSummary") or {}).get("status"),
        "avg_spo2":         daily.get("averageSpO2Value"),
    }, indent=2, default=str)


@mcp.tool()
def garmin_get_daily_stats(target_date: str = "") -> str:
    """
    Get Garmin daily stats: body battery, resting HR, stress score, steps,
    and calories. Defaults to today.
    target_date: YYYY-MM-DD, defaults to today
    """
    target = target_date.strip() or _today()
    client = _get_client()
    try:
        stats = client.get_stats(target)
    except Exception as e:
        return json.dumps({"error": str(e), "date": target})

    return json.dumps({
        "date":                 target,
        "body_battery_current": stats.get("bodyBatteryMostRecentValue"),
        "body_battery_high":    stats.get("bodyBatteryHighestValue"),
        "resting_hr":           stats.get("restingHeartRate"),
        "avg_stress":           stats.get("averageStressLevel"),
        "steps":                stats.get("totalSteps"),
        "active_calories":      stats.get("activeKilocalories"),
    }, indent=2, default=str)


@mcp.tool()
def garmin_get_hrv_status() -> str:
    """
    Get the athlete's current HRV status from Garmin: last night's HRV,
    5-night baseline, weekly average, and Garmin's status classification
    (Balanced / Unbalanced / Low / Poor).
    """
    client = _get_client()
    try:
        data = client.get_hrv_data(_today())
    except Exception as e:
        return json.dumps({"error": str(e)})

    summary  = data.get("hrvSummary", {}) or {}
    readings = data.get("hrvReadings", []) or []
    last_5   = [r.get("hrvValue") for r in readings[-5:] if r.get("hrvValue")]

    return json.dumps({
        "status":        summary.get("status"),
        "last_night":    summary.get("lastNight"),
        "weekly_avg":    summary.get("weeklyAvg"),
        "baseline_low":  summary.get("baselineLowUpper"),
        "baseline_high": summary.get("baselineHighUpper"),
        "last_5_nights": last_5,
    }, indent=2, default=str)


@mcp.tool()
def garmin_get_body_battery() -> str:
    """
    Get today's Garmin Body Battery timeline: current level, peak and low,
    and a readiness interpretation. Body battery (0-100) combines sleep,
    HRV, stress, and activity into a single recovery score.
    """
    client = _get_client()
    try:
        data = client.get_body_battery(_today(), _today())
    except Exception as e:
        return json.dumps({"error": str(e)})

    readings = []
    for entry in (data or []):
        for event in (entry.get("bodyBatteryValuesArray") or []):
            if event and len(event) >= 2:
                readings.append(event[1])

    current = readings[-1] if readings else None
    return json.dumps({
        "current": current,
        "peak":    max(readings) if readings else None,
        "low":     min(readings) if readings else None,
        "verdict": (
            "Ready to train hard" if current and current >= 75 else
            "Moderate training OK" if current and current >= 50 else
            "Easy only" if current and current >= 25 else
            "Rest recommended"
        ) if current else "No data",
    }, indent=2)


if __name__ == "__main__":
    missing = [k for k in ("GARMIN_USERNAME", "GARMIN_PASSWORD") if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"Missing env vars: {missing}. Copy .env.example to .env.")
    mcp.run()
