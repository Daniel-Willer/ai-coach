"""
Core data retrieval tools — ported from notebooks/lib/tools_data.py.
Replaces spark.sql() with databricks-sql-connector via db.client.
"""
from __future__ import annotations

import json
from langchain.tools import tool
from db.client import query, query_one, CATALOG


@tool
def get_training_load(athlete_id: str) -> str:
    """
    Get the athlete's current training load metrics: CTL (fitness), ATL (fatigue),
    TSB (form/freshness), and form state. Also returns the trend over the last 14 days.
    Use this when the athlete asks about fitness, fatigue, form, recovery, or readiness.
    """
    current = query_one(f"""
        SELECT date, ctl, atl, tsb, form
        FROM {CATALOG}.gold.daily_training_load
        WHERE athlete_id = '{athlete_id}'
        ORDER BY date DESC
        LIMIT 1
    """)
    if not current:
        return "No training load data found. Make sure the pipeline has run."

    trend = query(f"""
        SELECT date, ctl, atl, tsb, form
        FROM {CATALOG}.gold.daily_training_load
        WHERE athlete_id = '{athlete_id}'
        ORDER BY date DESC
        LIMIT 14
    """)
    ctl_14d_ago = float(trend[-1]["ctl"]) if len(trend) >= 14 and trend[-1]["ctl"] else None
    ctl_change = round(float(current["ctl"]) - ctl_14d_ago, 1) if ctl_14d_ago else None

    return json.dumps({
        "date": str(current["date"]),
        "ctl_fitness": round(float(current["ctl"]), 1),
        "atl_fatigue": round(float(current["atl"]), 1),
        "tsb_form": round(float(current["tsb"]), 1),
        "form_state": current["form"],
        "ctl_change_14d": ctl_change,
        "interpretation": {
            "tsb_guide": "TSB > +25: Very Fresh | +5 to +25: Fresh (race-ready) | -10 to +5: Neutral | -30 to -10: Tired (productive training) | < -30: Overreached"
        },
    }, indent=2, default=str)


@tool
def get_recent_activities(athlete_id: str, n: int = 10) -> str:
    """
    Get the athlete's most recent rides with key metrics: duration, distance, power,
    heart rate, TSS, and elevation. Use this when the athlete asks about recent rides,
    training history, or wants to know what they've been doing.
    """
    rows = query(f"""
        SELECT
            activity_id,
            source_system,
            CAST(start_time AS DATE) AS date,
            ROUND(duration_sec / 60.0, 0) AS duration_min,
            ROUND(distance_m / 1000.0, 1) AS distance_km,
            avg_power_w,
            normalized_power,
            avg_hr,
            ROUND(tss, 0) AS tss,
            ROUND(elevation_gain_m, 0) AS elevation_m,
            intensity_factor
        FROM {CATALOG}.silver.activities
        WHERE athlete_id = '{athlete_id}'
        ORDER BY start_time DESC
        LIMIT {n}
    """)
    if not rows:
        return "No activities found."
    return json.dumps(rows, indent=2, default=str)


@tool
def analyze_last_ride(athlete_id: str) -> str:
    """
    Deep analysis of the athlete's most recent ride: power zones, HR drift,
    performance vs FTP, normalized power, intensity factor, and coaching flags.
    Use this when the athlete asks for feedback on their last ride or wants to
    understand how a ride went.
    """
    ride = query_one(f"""
        SELECT *
        FROM {CATALOG}.silver.activities
        WHERE athlete_id = '{athlete_id}'
        ORDER BY start_time DESC
        LIMIT 1
    """)
    if not ride:
        return "No rides found."

    activity_id = ride["activity_id"]
    athlete = query_one(f"SELECT ftp_w, lthr FROM {CATALOG}.silver.athletes WHERE athlete_id = '{athlete_id}'")
    ftp = athlete["ftp_w"] if athlete else None

    zones = query_one(f"""
        SELECT zone_1_pct, zone_2_pct, zone_3_pct, zone_4_pct,
               zone_5_pct, zone_6_pct, zone_7_pct
        FROM {CATALOG}.gold.zone_distribution
        WHERE athlete_id = '{athlete_id}' AND activity_id = '{activity_id}'
        LIMIT 1
    """)

    hr_drift = None
    try:
        streams = query(f"""
            SELECT time_offset, power_w, heart_rate
            FROM {CATALOG}.silver.activity_streams
            WHERE activity_id = '{activity_id}' AND heart_rate IS NOT NULL
            ORDER BY time_offset
        """)
        if len(streams) > 60:
            mid = len(streams) // 2
            first_half, second_half = streams[:mid], streams[mid:]
            fh_hr = [r["heart_rate"] for r in first_half if r["heart_rate"]]
            sh_hr = [r["heart_rate"] for r in second_half if r["heart_rate"]]
            fh_pw = [r["power_w"] for r in first_half if r["power_w"]]
            sh_pw = [r["power_w"] for r in second_half if r["power_w"]]
            if fh_hr and sh_hr and fh_pw and sh_pw:
                avg_fh_hr = sum(fh_hr) / len(fh_hr)
                avg_sh_hr = sum(sh_hr) / len(sh_hr)
                avg_fh_pw = sum(fh_pw) / len(fh_pw)
                avg_sh_pw = sum(sh_pw) / len(sh_pw)
                if avg_fh_hr > 0:
                    ratio_first = avg_fh_pw / avg_fh_hr
                    ratio_second = avg_sh_pw / avg_sh_hr
                    hr_drift = round((ratio_first - ratio_second) / ratio_first * 100, 1)
    except Exception:
        pass

    result = {
        "ride_date": str(ride["start_time"])[:10],
        "source": ride["source_system"],
        "duration_min": round((ride["duration_sec"] or 0) / 60, 0),
        "distance_km": round((ride["distance_m"] or 0) / 1000, 1),
        "elevation_gain_m": ride["elevation_gain_m"],
        "avg_power_w": ride["avg_power_w"],
        "normalized_power_w": ride["normalized_power"],
        "ftp_w": ftp,
        "intensity_factor": round(float(ride["intensity_factor"]), 2) if ride.get("intensity_factor") else None,
        "tss": round(float(ride["tss"]), 0) if ride.get("tss") else None,
        "avg_hr": ride["avg_hr"],
        "max_hr": ride["max_hr"],
        "hr_drift_pct": hr_drift,
        "hr_drift_note": "< 5% = aerobically efficient | > 5% = HR rising relative to power (aerobic base needs work)" if hr_drift is not None else None,
    }
    if zones:
        result["power_zones"] = {
            "Z1_recovery": f"{zones['zone_1_pct']}%",
            "Z2_endurance": f"{zones['zone_2_pct']}%",
            "Z3_tempo": f"{zones['zone_3_pct']}%",
            "Z4_threshold": f"{zones['zone_4_pct']}%",
            "Z5_vo2max": f"{zones['zone_5_pct']}%",
            "Z6_anaerobic": f"{zones['zone_6_pct']}%",
            "Z7_neuromuscular": f"{zones['zone_7_pct']}%",
        }
    flags = []
    if hr_drift and hr_drift > 7:
        flags.append("HIGH_HR_DRIFT: aerobic base needs more Z2 work")
    if ride.get("intensity_factor") and ride["intensity_factor"] > 1.05:
        flags.append("HIGH_INTENSITY: above threshold — check if intentional")
    if ride.get("tss") and ride["tss"] > 150:
        flags.append("VERY_HIGH_TSS: >150 — significant recovery needed")
    result["coaching_flags"] = flags
    return json.dumps(result, indent=2, default=str)


@tool
def get_power_curve(athlete_id: str) -> str:
    """
    Get the athlete's power curve — peak power output at key durations (5s, 30s, 1min,
    5min, 20min, 60min). Use this to assess strengths and weaknesses, discuss FTP,
    or compare to benchmark standards.
    """
    row = query_one(f"""
        SELECT ftp_estimated_w, peak_5s_w, peak_30s_w, peak_1m_w, peak_5m_w, peak_20m_w, peak_60m_w, date
        FROM {CATALOG}.gold.fitness_metrics
        WHERE athlete_id = '{athlete_id}'
        ORDER BY date DESC
        LIMIT 1
    """)
    if not row:
        return "No power curve data found. Strava streams with power data are required."

    athlete = query_one(f"SELECT weight_kg FROM {CATALOG}.silver.athletes WHERE athlete_id = '{athlete_id}'")
    weight = athlete["weight_kg"] if athlete else None

    def wkg(watts):
        if weight and watts:
            return f" ({round(watts / weight, 1)} W/kg)"
        return ""

    return json.dumps({
        "as_of_date": str(row["date"]),
        "ftp_w": row["ftp_estimated_w"],
        "power_curve": {
            "5_sec":  f"{row['peak_5s_w']}W{wkg(row['peak_5s_w'])}",
            "30_sec": f"{row['peak_30s_w']}W{wkg(row['peak_30s_w'])}",
            "1_min":  f"{row['peak_1m_w']}W{wkg(row['peak_1m_w'])}",
            "5_min":  f"{row['peak_5m_w']}W{wkg(row['peak_5m_w'])}",
            "20_min": f"{row['peak_20m_w']}W{wkg(row['peak_20m_w'])}",
            "60_min": f"{row['peak_60m_w']}W{wkg(row['peak_60m_w'])}",
        },
        "weight_kg": weight,
    }, indent=2, default=str)


@tool
def get_weekly_summary(athlete_id: str, num_weeks: int = 8) -> str:
    """
    Get weekly training summaries showing volume, TSS, distance, elevation, ride count,
    sleep, and recovery metrics. Use this for weekly reviews, trend analysis, or when
    the athlete asks about their training load over time.
    """
    rows = query(f"""
        SELECT
            week_start,
            ROUND(total_hours, 1) AS hours,
            ROUND(total_tss, 0) AS tss,
            ROUND(total_distance_km, 0) AS distance_km,
            total_elevation_m AS elevation_m,
            ride_count,
            ROUND(avg_sleep_sec / 3600.0, 1) AS avg_sleep_hrs,
            ROUND(avg_body_battery, 0) AS avg_body_battery,
            ROUND(avg_resting_hr, 0) AS avg_resting_hr
        FROM {CATALOG}.gold.weekly_summary
        WHERE athlete_id = '{athlete_id}'
        ORDER BY week_start DESC
        LIMIT {num_weeks}
    """)
    if not rows:
        return "No weekly summary data found."
    return json.dumps(rows, indent=2, default=str)


@tool
def get_athlete_profile(athlete_id: str) -> str:
    """
    Get the athlete's profile: name, FTP, weight, fitness level, training goal,
    available hours, and upcoming goal events. Use this to personalize advice
    or when the athlete mentions their goals or upcoming races.
    """
    athlete = query_one(f"""
        SELECT name, ftp_w, weight_kg, fitness_level, training_goal,
               available_hours_week, lthr, max_hr, resting_hr, notes
        FROM {CATALOG}.silver.athletes
        WHERE athlete_id = '{athlete_id}'
    """)
    goals = query(f"""
        SELECT event_name, event_date, priority, event_type, target
        FROM {CATALOG}.coach.athlete_goals
        WHERE athlete_id = '{athlete_id}'
        ORDER BY priority, event_date
    """)
    if not athlete:
        return "Athlete profile not found. Run notebook 05_athlete_setup first."

    return json.dumps({
        "name": athlete["name"],
        "ftp_w": athlete["ftp_w"],
        "weight_kg": athlete["weight_kg"],
        "wkg": round(athlete["ftp_w"] / athlete["weight_kg"], 2) if athlete["ftp_w"] and athlete["weight_kg"] else None,
        "fitness_level": athlete["fitness_level"],
        "training_goal": athlete["training_goal"],
        "available_hours_per_week": athlete["available_hours_week"],
        "max_hr": athlete["max_hr"],
        "lthr": athlete["lthr"],
        "resting_hr": athlete["resting_hr"],
        "injury_history": athlete["notes"],
        "goal_events": goals,
    }, indent=2, default=str)


@tool
def get_fitness_snapshot(athlete_id: str) -> str:
    """
    Get a complete current snapshot of the athlete's fitness: training load, recent
    weekly trends, health metrics, and goal proximity. Use this for comprehensive
    reviews or when you need full context about where the athlete stands right now.
    """
    row = query_one(f"""
        SELECT *
        FROM {CATALOG}.features.athlete_daily
        WHERE athlete_id = '{athlete_id}'
        ORDER BY date DESC
        LIMIT 1
    """)
    if not row:
        return "No feature data found. Run notebook 04_feature_refresh first."

    return json.dumps({
        "date": str(row["date"]),
        "training_load": {
            "ctl": round(float(row["ctl"]), 1) if row["ctl"] else None,
            "atl": round(float(row["atl"]), 1) if row["atl"] else None,
            "tsb": round(float(row["tsb"]), 1) if row["tsb"] else None,
            "form": row["form"],
        },
        "this_week": {
            "hours": row["weekly_hours"],
            "tss": row["weekly_tss"],
        },
        "recovery": {
            "sleep_hrs": round(row["sleep_duration_sec"] / 3600, 1) if row.get("sleep_duration_sec") else None,
            "body_battery": int(row["body_battery"]) if row.get("body_battery") else None,
            "resting_hr": int(row["resting_hr"]) if row.get("resting_hr") else None,
            "stress_score": int(row["stress_score"]) if row.get("stress_score") else None,
        },
        "goals": {
            "days_to_goal_event": row.get("days_to_goal_event"),
            "ftp_w": row.get("ftp_w"),
            "compliance_7d_pct": row.get("compliance_7d"),
        },
    }, indent=2, default=str)


data_tools = [
    get_training_load,
    get_recent_activities,
    analyze_last_ride,
    get_power_curve,
    get_weekly_summary,
    get_athlete_profile,
    get_fitness_snapshot,
]
