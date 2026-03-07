# Databricks notebook source
# MAGIC %md
# MAGIC # lib/tools_analysis — Enhanced Performance Analysis Tools
# MAGIC
# MAGIC Four new tools for deeper analysis beyond a single ride.
# MAGIC %run'd by 06_coaching_agent.py — do not run standalone.

# COMMAND ----------

from pyspark.sql import SparkSession
from langchain.tools import tool
import json

spark = SparkSession.builder.getOrCreate()

# CATALOG set by parent notebook


@tool
def analyze_activity(athlete_id: str, activity_id: str) -> str:
    """
    Deep analysis of a specific ride by activity_id: power zones, HR drift,
    intensity factor, TSS, and coaching flags. Use this when the athlete asks
    about a specific ride (e.g. 'how did my ride last Tuesday go?').
    Call get_recent_activities first to find the activity_id if needed.
    """
    ride = spark.sql(f"""
        SELECT *
        FROM {CATALOG}.silver.activities
        WHERE athlete_id = '{athlete_id}' AND activity_id = '{activity_id}'
        LIMIT 1
    """).collect()

    if not ride:
        return f"Activity {activity_id} not found for athlete {athlete_id}."

    r = ride[0]

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
        "activity_id": activity_id,
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
        "hr_drift_note": "< 5% = aerobically efficient | > 5% = HR rising relative to power" if hr_drift else None,
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

    result["coaching_flags"] = flags
    return json.dumps(result, indent=2, default=str)


@tool
def get_power_curve_trend(athlete_id: str) -> str:
    """
    Compare the athlete's power curve at key durations (5s, 1min, 5min, 20min) across
    the last 30, 60, and 90 days. Shows whether peak power is improving or declining
    at each duration. Use this when the athlete asks if they're getting stronger,
    wants to see power progression, or questions their training effectiveness.
    """
    rows = spark.sql(f"""
        SELECT date, peak_5s_w, peak_1m_w, peak_5m_w, peak_20m_w, ftp_estimated_w
        FROM {CATALOG}.gold.fitness_metrics
        WHERE athlete_id = '{athlete_id}'
        ORDER BY date DESC
        LIMIT 90
    """).toPandas()

    if rows.empty:
        return "No fitness metrics data found."

    rows["date"] = rows["date"].astype(str)

    def best_in_window(df, days):
        recent = df.head(days)
        if recent.empty:
            return None
        return {
            "peak_5s_w": int(recent["peak_5s_w"].max()) if recent["peak_5s_w"].notna().any() else None,
            "peak_1m_w": int(recent["peak_1m_w"].max()) if recent["peak_1m_w"].notna().any() else None,
            "peak_5m_w": int(recent["peak_5m_w"].max()) if recent["peak_5m_w"].notna().any() else None,
            "peak_20m_w": int(recent["peak_20m_w"].max()) if recent["peak_20m_w"].notna().any() else None,
            "ftp_w": int(recent["ftp_estimated_w"].max()) if recent["ftp_estimated_w"].notna().any() else None,
        }

    last_30 = best_in_window(rows, 30)
    last_60 = best_in_window(rows, 60)
    last_90 = best_in_window(rows, 90)

    def trend(v30, v90, label):
        if v30 and v90 and v90 > 0:
            delta = v30 - v90
            pct = round(delta / v90 * 100, 1)
            direction = "improving" if delta > 0 else ("declining" if delta < 0 else "flat")
            return f"{direction} ({'+' if delta >= 0 else ''}{delta}W, {'+' if pct >= 0 else ''}{pct}% vs 90d best)"
        return "insufficient data"

    result = {
        "best_30d": last_30,
        "best_60d": last_60,
        "best_90d": last_90,
        "trends": {
            "5s_sprint": trend(last_30.get("peak_5s_w") if last_30 else None, last_90.get("peak_5s_w") if last_90 else None, "5s"),
            "1min": trend(last_30.get("peak_1m_w") if last_30 else None, last_90.get("peak_1m_w") if last_90 else None, "1m"),
            "5min": trend(last_30.get("peak_5m_w") if last_30 else None, last_90.get("peak_5m_w") if last_90 else None, "5m"),
            "20min_ftp_proxy": trend(last_30.get("peak_20m_w") if last_30 else None, last_90.get("peak_20m_w") if last_90 else None, "20m"),
        }
    }

    return json.dumps(result, indent=2, default=str)


@tool
def detect_training_imbalance(athlete_id: str) -> str:
    """
    Analyze zone distribution across the last 4 weeks to detect training imbalances.
    Flags polarization deficit (too little Z2), lack of high-intensity work, or
    excessive Z3-Z4 'grey zone' riding. Returns specific recommendations.
    Use this when the athlete asks about training balance, zone distribution,
    whether they're doing too much or too little intensity.
    """
    zones_df = spark.sql(f"""
        SELECT
            zd.zone_1_pct, zd.zone_2_pct, zd.zone_3_pct, zd.zone_4_pct,
            zd.zone_5_pct, zd.zone_6_pct, zd.zone_7_pct,
            a.duration_sec
        FROM {CATALOG}.gold.zone_distribution zd
        JOIN {CATALOG}.silver.activities a
            ON zd.activity_id = a.activity_id AND zd.athlete_id = a.athlete_id
        WHERE zd.athlete_id = '{athlete_id}'
          AND a.start_time >= DATEADD(week, -4, CURRENT_DATE())
    """).toPandas()

    if zones_df.empty:
        return "No zone distribution data found for the last 4 weeks."

    # Weighted average by duration
    total_sec = zones_df["duration_sec"].sum()
    if total_sec == 0:
        return "No valid duration data."

    def wavg(col):
        return round(float((zones_df[col] * zones_df["duration_sec"]).sum() / total_sec), 1)

    z1 = wavg("zone_1_pct")
    z2 = wavg("zone_2_pct")
    z3 = wavg("zone_3_pct")
    z4 = wavg("zone_4_pct")
    z5 = wavg("zone_5_pct")
    z6 = wavg("zone_6_pct")
    z7 = wavg("zone_7_pct")

    low_intensity_pct = z1 + z2       # Z1+Z2 — aerobic base
    grey_zone_pct = z3 + z4           # Z3+Z4 — tempo/threshold (often overused)
    high_intensity_pct = z5 + z6 + z7 # Z5+ — VO2max+

    # Check last 2 weeks for high-intensity recency
    recent_z5_df = spark.sql(f"""
        SELECT zd.zone_5_pct, zd.zone_6_pct, zd.zone_7_pct
        FROM {CATALOG}.gold.zone_distribution zd
        JOIN {CATALOG}.silver.activities a
            ON zd.activity_id = a.activity_id
        WHERE zd.athlete_id = '{athlete_id}'
          AND a.start_time >= DATEADD(week, -2, CURRENT_DATE())
    """).toPandas()

    has_recent_intensity = False
    if not recent_z5_df.empty:
        avg_hi = float((recent_z5_df["zone_5_pct"] + recent_z5_df["zone_6_pct"] + recent_z5_df["zone_7_pct"]).mean())
        has_recent_intensity = avg_hi > 5.0

    flags = []
    recommendations = []

    if low_intensity_pct < 60:
        flags.append("POLARIZATION_DEFICIT")
        recommendations.append(f"Only {low_intensity_pct}% of time in Z1-Z2 (target: >60%). Add more long, easy rides.")

    if grey_zone_pct > 30:
        flags.append("GREY_ZONE_OVERLOAD")
        recommendations.append(f"{grey_zone_pct}% in Z3-Z4 is too high — these zones accumulate fatigue without VO2max stimulus. Go easier or harder, not moderate.")

    if not has_recent_intensity and high_intensity_pct < 5:
        flags.append("NO_RECENT_HIGH_INTENSITY")
        recommendations.append("No Z5+ work in the last 2 weeks. Add one interval session (4-6x4min at VO2max) this week.")

    if not flags:
        flags.append("BALANCED")
        recommendations.append("Zone distribution looks well-balanced. Maintain current approach.")

    return json.dumps({
        "4_week_zone_distribution": {
            "Z1_recovery_pct": z1,
            "Z2_endurance_pct": z2,
            "Z3_tempo_pct": z3,
            "Z4_threshold_pct": z4,
            "Z5_vo2max_pct": z5,
            "Z6_anaerobic_pct": z6,
            "Z7_neuromuscular_pct": z7,
        },
        "summary": {
            "low_intensity_Z1_Z2_pct": low_intensity_pct,
            "grey_zone_Z3_Z4_pct": grey_zone_pct,
            "high_intensity_Z5plus_pct": high_intensity_pct,
            "has_recent_high_intensity_2wk": has_recent_intensity,
        },
        "flags": flags,
        "recommendations": recommendations,
    }, indent=2)


@tool
def compare_route_performances(athlete_id: str, keyword: str) -> str:
    """
    Search for rides matching a keyword (e.g. 'Zwift', 'morning loop', 'climb') and
    show performance trend for those rides over time: avg_power, duration, TSS, elevation.
    Use this when the athlete asks 'am I getting faster on my usual route?' or wants
    to compare performances on repeated routes or ride types.
    """
    rows = spark.sql(f"""
        SELECT
            activity_id,
            CAST(start_time AS DATE) AS date,
            name,
            ROUND(duration_sec / 60.0, 0) AS duration_min,
            avg_power_w,
            normalized_power,
            ROUND(tss, 0) AS tss,
            ROUND(elevation_gain_m, 0) AS elevation_m,
            intensity_factor,
            source_system
        FROM {CATALOG}.silver.activities
        WHERE athlete_id = '{athlete_id}'
          AND LOWER(name) LIKE LOWER('%{keyword}%')
        ORDER BY start_time ASC
    """).toPandas()

    if rows.empty:
        return f"No rides found matching '{keyword}'. Try a different keyword."

    if len(rows) < 2:
        return json.dumps({
            "keyword": keyword,
            "message": "Only one matching ride found — need at least 2 to show a trend.",
            "rides": rows.to_dict(orient="records"),
        }, indent=2, default=str)

    # Simple trend: first vs last
    first = rows.iloc[0]
    last = rows.iloc[-1]

    def delta(col):
        f, l = first.get(col), last.get(col)
        if f and l and f > 0:
            return round(float(l) - float(f), 1)
        return None

    trend = {
        "avg_power_delta_w": delta("avg_power_w"),
        "duration_delta_min": delta("duration_min"),
        "tss_delta": delta("tss"),
    }

    return json.dumps({
        "keyword": keyword,
        "matching_rides": len(rows),
        "date_range": f"{rows.iloc[0]['date']} → {rows.iloc[-1]['date']}",
        "trend_first_to_last": trend,
        "rides": rows.to_dict(orient="records"),
    }, indent=2, default=str)


# Exported list
analysis_tools = [
    analyze_activity,
    get_power_curve_trend,
    detect_training_imbalance,
    compare_route_performances,
]

print(f"  lib/tools_analysis loaded: {len(analysis_tools)} tools")
