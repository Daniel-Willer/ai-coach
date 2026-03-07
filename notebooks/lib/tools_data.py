# Databricks notebook source
# MAGIC %md
# MAGIC # lib/tools_data — Data Retrieval Tools
# MAGIC
# MAGIC Extracted from 06_coaching_agent.py. Provides the 7 core data-fetching tools.
# MAGIC %run'd by 06_coaching_agent.py — do not run standalone.

# COMMAND ----------

from pyspark.sql import SparkSession
from langchain.tools import tool
from typing import Optional
import json

spark = SparkSession.builder.getOrCreate()

# CATALOG and ATHLETE_ID are set by the parent notebook before %run


@tool
def get_training_load(athlete_id: str) -> str:
    """
    Get the athlete's current training load metrics: CTL (fitness), ATL (fatigue),
    TSB (form/freshness), and form state. Also returns the trend over the last 14 days.
    Use this when the athlete asks about fitness, fatigue, form, recovery, or readiness.
    """
    current = spark.sql(f"""
        SELECT date, ctl, atl, tsb, form
        FROM {CATALOG}.gold.daily_training_load
        WHERE athlete_id = '{athlete_id}'
        ORDER BY date DESC
        LIMIT 1
    """).collect()

    if not current:
        return "No training load data found. Make sure the pipeline has run."

    r = current[0]

    trend = spark.sql(f"""
        SELECT date, ctl, atl, tsb, form
        FROM {CATALOG}.gold.daily_training_load
        WHERE athlete_id = '{athlete_id}'
        ORDER BY date DESC
        LIMIT 14
    """).toPandas()

    ctl_14d_ago = float(trend.iloc[-1]["ctl"]) if len(trend) >= 14 else None
    ctl_change = round(float(r.ctl) - ctl_14d_ago, 1) if ctl_14d_ago else None

    return json.dumps({
        "date": str(r.date),
        "ctl_fitness": round(float(r.ctl), 1),
        "atl_fatigue": round(float(r.atl), 1),
        "tsb_form": round(float(r.tsb), 1),
        "form_state": r.form,
        "ctl_change_14d": ctl_change,
        "interpretation": {
            "tsb_guide": "TSB > +25: Very Fresh | +5 to +25: Fresh (race-ready) | -10 to +5: Neutral | -30 to -10: Tired (productive training) | < -30: Overreached"
        }
    }, indent=2)


@tool
def get_recent_activities(athlete_id: str, n: int = 10) -> str:
    """
    Get the athlete's most recent rides with key metrics: duration, distance, power,
    heart rate, TSS, and elevation. Use this when the athlete asks about recent rides,
    training history, or wants to know what they've been doing.
    """
    rows = spark.sql(f"""
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
    """).toPandas()

    if rows.empty:
        return "No activities found."

    return rows.to_json(orient="records", date_format="iso", indent=2)


@tool
def analyze_last_ride(athlete_id: str) -> str:
    """
    Deep analysis of the athlete's most recent ride: power zones, HR drift,
    performance vs FTP, normalized power, intensity factor, and coaching flags.
    Use this when the athlete asks for feedback on their last ride or wants to
    understand how a ride went.
    """
    last_ride = spark.sql(f"""
        SELECT *
        FROM {CATALOG}.silver.activities
        WHERE athlete_id = '{athlete_id}'
        ORDER BY start_time DESC
        LIMIT 1
    """).collect()

    if not last_ride:
        return "No rides found."

    r = last_ride[0]
    activity_id = r.activity_id

    athlete = spark.sql(f"""
        SELECT ftp_w, lthr FROM {CATALOG}.silver.athletes WHERE athlete_id = '{athlete_id}'
    """).collect()
    ftp = athlete[0].ftp_w if athlete else None

    zones = spark.sql(f"""
        SELECT zone_1_pct, zone_2_pct, zone_3_pct, zone_4_pct, zone_5_pct, zone_6_pct, zone_7_pct
        FROM {CATALOG}.gold.zone_distribution
        WHERE athlete_id = '{athlete_id}' AND activity_id = '{activity_id}'
        LIMIT 1
    """).collect()

    hr_drift = None
    try:
        streams = spark.sql(f"""
            SELECT time_offset, power_w, heart_rate
            FROM {CATALOG}.silver.activity_streams
            WHERE activity_id = '{activity_id}' AND heart_rate IS NOT NULL
            ORDER BY time_offset
        """).toPandas()

        if len(streams) > 60:
            mid = len(streams) // 2
            first_half = streams.iloc[:mid]
            second_half = streams.iloc[mid:]

            if first_half["heart_rate"].mean() > 0 and second_half["heart_rate"].mean() > 0:
                if first_half["power_w"].notna().any() and first_half["power_w"].mean() > 0:
                    ratio_first = first_half["power_w"].mean() / first_half["heart_rate"].mean()
                    ratio_second = second_half["power_w"].mean() / second_half["heart_rate"].mean()
                    hr_drift = round((ratio_first - ratio_second) / ratio_first * 100, 1)
    except Exception:
        pass

    result = {
        "ride_date": str(r.start_time)[:10],
        "source": r.source_system,
        "duration_min": round((r.duration_sec or 0) / 60, 0),
        "distance_km": round((r.distance_m or 0) / 1000, 1),
        "elevation_gain_m": r.elevation_gain_m,
        "avg_power_w": r.avg_power_w,
        "normalized_power_w": r.normalized_power,
        "ftp_w": ftp,
        "intensity_factor": round(float(r.intensity_factor), 2) if r.intensity_factor else None,
        "tss": round(float(r.tss), 0) if r.tss else None,
        "avg_hr": r.avg_hr,
        "max_hr": r.max_hr,
        "hr_drift_pct": hr_drift,
        "hr_drift_note": "< 5% = aerobically efficient | > 5% = HR rising relative to power (aerobic base needs work)" if hr_drift else None,
    }

    if zones:
        z = zones[0]
        result["power_zones"] = {
            "Z1_recovery": f"{z.zone_1_pct}%",
            "Z2_endurance": f"{z.zone_2_pct}%",
            "Z3_tempo": f"{z.zone_3_pct}%",
            "Z4_threshold": f"{z.zone_4_pct}%",
            "Z5_vo2max": f"{z.zone_5_pct}%",
            "Z6_anaerobic": f"{z.zone_6_pct}%",
            "Z7_neuromuscular": f"{z.zone_7_pct}%",
        }

    flags = []
    if hr_drift and hr_drift > 7:
        flags.append("HIGH_HR_DRIFT: aerobic base needs more Z2 work")
    if r.intensity_factor and r.intensity_factor > 1.05:
        flags.append("HIGH_INTENSITY: above threshold — check if intentional")
    if r.tss and r.tss > 150:
        flags.append("VERY_HIGH_TSS: >150 — significant recovery needed")
    if r.avg_hr and ftp and r.avg_power_w and (r.avg_hr / r.avg_power_w) < 0.5:
        flags.append("GOOD_EFFICIENCY: strong power:HR ratio")

    result["coaching_flags"] = flags
    return json.dumps(result, indent=2, default=str)


@tool
def get_power_curve(athlete_id: str) -> str:
    """
    Get the athlete's power curve — peak power output at key durations (5s, 30s, 1min,
    5min, 20min, 60min). Use this to assess strengths and weaknesses, discuss FTP,
    or compare to benchmark standards.
    """
    row = spark.sql(f"""
        SELECT ftp_estimated_w, peak_5s_w, peak_30s_w, peak_1m_w, peak_5m_w, peak_20m_w, peak_60m_w, date
        FROM {CATALOG}.gold.fitness_metrics
        WHERE athlete_id = '{athlete_id}'
        ORDER BY date DESC
        LIMIT 1
    """).collect()

    if not row:
        return "No power curve data found. Strava streams with power data are required."

    r = row[0]

    athlete = spark.sql(f"SELECT weight_kg FROM {CATALOG}.silver.athletes WHERE athlete_id = '{athlete_id}'").collect()
    weight = athlete[0].weight_kg if athlete else None

    result = {
        "as_of_date": str(r.date),
        "ftp_w": r.ftp_estimated_w,
        "power_curve": {
            "5_sec":  f"{r.peak_5s_w}W" + (f" ({round(r.peak_5s_w/weight, 1)} W/kg)" if weight and r.peak_5s_w else ""),
            "30_sec": f"{r.peak_30s_w}W" + (f" ({round(r.peak_30s_w/weight, 1)} W/kg)" if weight and r.peak_30s_w else ""),
            "1_min":  f"{r.peak_1m_w}W" + (f" ({round(r.peak_1m_w/weight, 1)} W/kg)" if weight and r.peak_1m_w else ""),
            "5_min":  f"{r.peak_5m_w}W" + (f" ({round(r.peak_5m_w/weight, 1)} W/kg)" if weight and r.peak_5m_w else ""),
            "20_min": f"{r.peak_20m_w}W" + (f" ({round(r.peak_20m_w/weight, 1)} W/kg)" if weight and r.peak_20m_w else ""),
            "60_min": f"{r.peak_60m_w}W" + (f" ({round(r.peak_60m_w/weight, 1)} W/kg)" if weight and r.peak_60m_w else ""),
        },
        "weight_kg": weight,
    }

    return json.dumps(result, indent=2, default=str)


@tool
def get_weekly_summary(athlete_id: str, num_weeks: int = 8) -> str:
    """
    Get weekly training summaries showing volume, TSS, distance, elevation, ride count,
    sleep, and recovery metrics. Use this for weekly reviews, trend analysis, or when
    the athlete asks about their training load over time.
    """
    rows = spark.sql(f"""
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
    """).toPandas()

    if rows.empty:
        return "No weekly summary data found."

    return rows.to_json(orient="records", date_format="iso", indent=2)


@tool
def get_athlete_profile(athlete_id: str) -> str:
    """
    Get the athlete's profile: name, FTP, weight, fitness level, training goal,
    available hours, and upcoming goal events. Use this to personalize advice
    or when the athlete mentions their goals or upcoming races.
    """
    athlete = spark.sql(f"""
        SELECT name, ftp_w, weight_kg, fitness_level, training_goal,
               available_hours_week, lthr, max_hr, resting_hr, notes
        FROM {CATALOG}.silver.athletes
        WHERE athlete_id = '{athlete_id}'
    """).collect()

    goals = spark.sql(f"""
        SELECT event_name, event_date, priority, event_type, target
        FROM {CATALOG}.coach.athlete_goals
        WHERE athlete_id = '{athlete_id}'
        ORDER BY priority, event_date
    """).toPandas()

    if not athlete:
        return "Athlete profile not found. Run notebook 05_athlete_setup first."

    r = athlete[0]
    result = {
        "name": r.name,
        "ftp_w": r.ftp_w,
        "weight_kg": r.weight_kg,
        "wkg": round(r.ftp_w / r.weight_kg, 2) if r.ftp_w and r.weight_kg else None,
        "fitness_level": r.fitness_level,
        "training_goal": r.training_goal,
        "available_hours_per_week": r.available_hours_week,
        "max_hr": r.max_hr,
        "lthr": r.lthr,
        "resting_hr": r.resting_hr,
        "injury_history": r.notes,
        "goal_events": goals.to_dict(orient="records") if not goals.empty else [],
    }

    return json.dumps(result, indent=2, default=str)


@tool
def get_fitness_snapshot(athlete_id: str) -> str:
    """
    Get a complete current snapshot of the athlete's fitness: training load, recent
    weekly trends, health metrics, and goal proximity. Use this for comprehensive
    reviews or when you need full context about where the athlete stands right now.
    """
    row = spark.sql(f"""
        SELECT *
        FROM {CATALOG}.features.athlete_daily
        WHERE athlete_id = '{athlete_id}'
        ORDER BY date DESC
        LIMIT 1
    """).collect()

    if not row:
        return "No feature data found. Run notebook 04_feature_refresh first."

    r = row[0]
    return json.dumps({
        "date": str(r.date),
        "training_load": {
            "ctl": round(float(r.ctl), 1) if r.ctl else None,
            "atl": round(float(r.atl), 1) if r.atl else None,
            "tsb": round(float(r.tsb), 1) if r.tsb else None,
            "form": r.form,
        },
        "this_week": {
            "hours": r.weekly_hours,
            "tss": r.weekly_tss,
        },
        "recovery": {
            "sleep_hrs": round(r.sleep_duration_sec / 3600, 1) if r.sleep_duration_sec else None,
            "body_battery": int(r.body_battery) if r.body_battery else None,
            "resting_hr": int(r.resting_hr) if r.resting_hr else None,
            "stress_score": int(r.stress_score) if r.stress_score else None,
        },
        "goals": {
            "days_to_goal_event": r.days_to_goal_event,
            "ftp_w": r.ftp_w,
            "compliance_7d_pct": r.compliance_7d,
        }
    }, indent=2)


# Exported list — parent notebook merges this with other tool lists
data_tools = [
    get_training_load,
    get_recent_activities,
    analyze_last_ride,
    get_power_curve,
    get_weekly_summary,
    get_athlete_profile,
    get_fitness_snapshot,
]

print(f"  lib/tools_data loaded: {len(data_tools)} tools")
