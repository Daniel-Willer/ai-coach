"""
Live Garmin Connect tools — ported from notebooks/lib/tools_garmin_live.py.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from langchain.tools import tool
from db.secrets import get_secret

_garmin_client = None


def _get_garmin_client():
    global _garmin_client
    if _garmin_client is not None:
        return _garmin_client
    from garminconnect import Garmin
    client = Garmin(get_secret("garmin", "username"), get_secret("garmin", "password"))
    client.login()
    _garmin_client = client
    return client


def _today() -> str:
    return str(date.today())

def _yesterday() -> str:
    return str(date.today() - timedelta(days=1))


@tool
def garmin_get_sleep(target_date: str = "") -> str:
    """
    Get sleep data from Garmin Connect: total sleep duration, sleep score, time in
    each stage (deep, light, REM, awake), and overnight HRV. Defaults to last night.
    Use this when the athlete asks about sleep or recovery, or before recommending intensity.
    target_date: YYYY-MM-DD format, defaults to yesterday
    """
    target = target_date.strip() or _yesterday()
    try:
        sleep = _get_garmin_client().get_sleep_data(target)
        daily = sleep.get("dailySleepDTO", {}) or {}
        hrv = sleep.get("hrvData", {}) or {}
        def mins(sec): return round((sec or 0) / 60) if sec else None
        return json.dumps({
            "date": target,
            "sleep_score": (daily.get("sleepScores", {}) or {}).get("overall", {}).get("value"),
            "total_sleep_min": mins(daily.get("sleepTimeSeconds")),
            "deep_sleep_min": mins(daily.get("deepSleepSeconds")),
            "light_sleep_min": mins(daily.get("lightSleepSeconds")),
            "rem_sleep_min": mins(daily.get("remSleepSeconds")),
            "awake_min": mins(daily.get("awakeSleepSeconds")),
            "avg_overnight_hrv": hrv.get("lastNight"),
            "hrv_status": (hrv.get("hrvSummary", {}) or {}).get("status"),
            "interpretation": {"sleep_score": "< 60: poor | 60-79: fair | 80+: good"},
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "date": target})


@tool
def garmin_get_daily_stats(target_date: str = "") -> str:
    """
    Get Garmin daily wellness stats: body battery, average stress score, resting HR,
    steps, and calories. Defaults to today.
    Use this to check the athlete's current recovery state before prescribing intensity.
    target_date: YYYY-MM-DD format, defaults to today
    """
    target = target_date.strip() or _today()
    try:
        stats = _get_garmin_client().get_stats(target)
        return json.dumps({
            "date": target,
            "body_battery_highest": stats.get("bodyBatteryHighestValue"),
            "body_battery_lowest": stats.get("bodyBatteryLowestValue"),
            "body_battery_most_recent": stats.get("bodyBatteryMostRecentValue"),
            "resting_hr": stats.get("restingHeartRate"),
            "avg_stress": stats.get("averageStressLevel"),
            "steps": stats.get("totalSteps"),
            "interpretation": {"body_battery": "0-25: rest | 26-50: low | 51-75: medium | 76-100: ready to train hard"},
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "date": target})


@tool
def garmin_get_hrv_status() -> str:
    """
    Get the athlete's HRV status: last night's HRV, 5-day average, baseline, and
    Garmin's classification (Balanced / Unbalanced / Low).
    Use this when assessing readiness for hard training or when the athlete asks about HRV.
    """
    try:
        hrv_data = _get_garmin_client().get_hrv_data(_today())
        summary = hrv_data.get("hrvSummary", {}) or {}
        readings = hrv_data.get("hrvReadings", []) or []
        last_5 = [r.get("hrvValue") for r in readings[-5:] if r.get("hrvValue")]
        return json.dumps({
            "status": summary.get("status"),
            "last_night_hrv": summary.get("lastNight"),
            "baseline_low": summary.get("baselineLowUpper"),
            "baseline_high": summary.get("baselineHighUpper"),
            "weekly_avg": summary.get("weeklyAvg"),
            "last_5_nights": last_5,
            "interpretation": {"Balanced": "Normal range", "Unbalanced": "Moderate only", "Low": "Easy only"},
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def garmin_get_body_battery_today() -> str:
    """
    Get the athlete's current Garmin Body Battery level: current level, peak, and low today.
    Body battery combines sleep, HRV, stress, and activity into a 0-100 readiness score.
    Use this for a quick real-time readiness check before prescribing workouts.
    """
    try:
        bb_data = _get_garmin_client().get_body_battery(_today(), _today())
        if not bb_data:
            return json.dumps({"error": "No body battery data for today yet"})
        readings = []
        for entry in (bb_data or []):
            for event in (entry.get("bodyBatteryValuesArray") or []):
                if event and len(event) >= 2:
                    readings.append(event[1])
        current = readings[-1] if readings else None
        return json.dumps({
            "current_level": current,
            "peak_today": max(readings) if readings else None,
            "low_today": min(readings) if readings else None,
            "interpretation": (
                "Ready to train hard" if current and current >= 75 else
                "Moderate training OK" if current and current >= 50 else
                "Easy training only" if current and current >= 25 else
                "Rest day recommended"
            ) if current else "No data",
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


garmin_live_tools = [garmin_get_sleep, garmin_get_daily_stats, garmin_get_hrv_status, garmin_get_body_battery_today]
