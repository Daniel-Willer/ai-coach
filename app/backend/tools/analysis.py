"""
Enhanced performance analysis tools — ported from notebooks/lib/tools_analysis.py.
"""
from __future__ import annotations

import json
from langchain.tools import tool
from db.client import query, query_one, CATALOG


@tool
def analyze_activity(athlete_id: str, activity_id: str) -> str:
    """
    Deep analysis of a specific ride by activity_id: power zones, HR drift,
    intensity factor, TSS, and coaching flags. Use this when the athlete asks
    about a specific ride (e.g. 'how did my ride last Tuesday go?').
    Call get_recent_activities first to find the activity_id if needed.
    """
    ride = query_one(f"""
        SELECT * FROM {CATALOG}.silver.activities
        WHERE athlete_id = '{athlete_id}' AND activity_id = '{activity_id}'
        LIMIT 1
    """)
    if not ride:
        return f"Activity {activity_id} not found for athlete {athlete_id}."

    athlete = query_one(f"SELECT ftp_w FROM {CATALOG}.silver.athletes WHERE athlete_id = '{athlete_id}'")
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
            fh, sh = streams[:mid], streams[mid:]
            fh_pw = [r["power_w"] for r in fh if r.get("power_w")]
            sh_pw = [r["power_w"] for r in sh if r.get("power_w")]
            fh_hr = [r["heart_rate"] for r in fh if r.get("heart_rate")]
            sh_hr = [r["heart_rate"] for r in sh if r.get("heart_rate")]
            if fh_pw and sh_pw and fh_hr and sh_hr:
                r1 = (sum(fh_pw) / len(fh_pw)) / (sum(fh_hr) / len(fh_hr))
                r2 = (sum(sh_pw) / len(sh_pw)) / (sum(sh_hr) / len(sh_hr))
                hr_drift = round((r1 - r2) / r1 * 100, 1)
    except Exception:
        pass

    result = {
        "activity_id": activity_id,
        "ride_date": str(ride["start_time"])[:10],
        "duration_min": round((ride["duration_sec"] or 0) / 60, 0),
        "distance_km": round((ride["distance_m"] or 0) / 1000, 1),
        "elevation_gain_m": ride["elevation_gain_m"],
        "avg_power_w": ride["avg_power_w"],
        "normalized_power_w": ride["normalized_power"],
        "ftp_w": ftp,
        "intensity_factor": round(float(ride["intensity_factor"]), 2) if ride.get("intensity_factor") else None,
        "tss": round(float(ride["tss"]), 0) if ride.get("tss") else None,
        "avg_hr": ride["avg_hr"],
        "hr_drift_pct": hr_drift,
    }
    if zones:
        result["power_zones"] = {
            f"Z{i}": f"{zones[f'zone_{i}_pct']}%" for i in range(1, 8)
        }
    flags = []
    if hr_drift and hr_drift > 7:
        flags.append("HIGH_HR_DRIFT")
    if ride.get("intensity_factor") and ride["intensity_factor"] > 1.05:
        flags.append("HIGH_INTENSITY")
    if ride.get("tss") and ride["tss"] > 150:
        flags.append("VERY_HIGH_TSS")
    result["coaching_flags"] = flags
    return json.dumps(result, indent=2, default=str)


@tool
def get_power_curve_trend(athlete_id: str) -> str:
    """
    Compare the athlete's power curve at key durations (5s, 1min, 5min, 20min) across
    the last 30, 60, and 90 days. Shows whether peak power is improving or declining.
    Use this when the athlete asks if they're getting stronger or wants to see power progression.
    """
    rows = query(f"""
        SELECT date, peak_5s_w, peak_1m_w, peak_5m_w, peak_20m_w, ftp_estimated_w
        FROM {CATALOG}.gold.fitness_metrics
        WHERE athlete_id = '{athlete_id}'
        ORDER BY date DESC
        LIMIT 90
    """)
    if not rows:
        return "No fitness metrics data found."

    def best_in_window(rows, days):
        window = rows[:days]
        if not window:
            return None
        return {
            "peak_5s_w": max((r["peak_5s_w"] for r in window if r.get("peak_5s_w")), default=None),
            "peak_1m_w": max((r["peak_1m_w"] for r in window if r.get("peak_1m_w")), default=None),
            "peak_5m_w": max((r["peak_5m_w"] for r in window if r.get("peak_5m_w")), default=None),
            "peak_20m_w": max((r["peak_20m_w"] for r in window if r.get("peak_20m_w")), default=None),
        }

    def trend(v30, v90, label):
        if v30 and v90 and v90 > 0:
            delta = v30 - v90
            pct = round(delta / v90 * 100, 1)
            direction = "improving" if delta > 0 else ("declining" if delta < 0 else "flat")
            return f"{direction} ({'+' if delta >= 0 else ''}{delta}W, {'+' if pct >= 0 else ''}{pct}% vs 90d best)"
        return "insufficient data"

    b30, b60, b90 = best_in_window(rows, 30), best_in_window(rows, 60), best_in_window(rows, 90)

    return json.dumps({
        "best_30d": b30, "best_60d": b60, "best_90d": b90,
        "trends": {
            "5s_sprint": trend(b30.get("peak_5s_w") if b30 else None, b90.get("peak_5s_w") if b90 else None, "5s"),
            "1min": trend(b30.get("peak_1m_w") if b30 else None, b90.get("peak_1m_w") if b90 else None, "1m"),
            "5min": trend(b30.get("peak_5m_w") if b30 else None, b90.get("peak_5m_w") if b90 else None, "5m"),
            "20min_ftp_proxy": trend(b30.get("peak_20m_w") if b30 else None, b90.get("peak_20m_w") if b90 else None, "20m"),
        },
    }, indent=2, default=str)


@tool
def detect_training_imbalance(athlete_id: str) -> str:
    """
    Analyze zone distribution across the last 4 weeks to detect training imbalances.
    Flags polarization deficit, lack of high-intensity work, or excessive grey-zone riding.
    Use this when the athlete asks about training balance or whether they're doing too
    much or too little intensity.
    """
    zones_rows = query(f"""
        SELECT
            zd.zone_1_pct, zd.zone_2_pct, zd.zone_3_pct, zd.zone_4_pct,
            zd.zone_5_pct, zd.zone_6_pct, zd.zone_7_pct,
            a.duration_sec
        FROM {CATALOG}.gold.zone_distribution zd
        JOIN {CATALOG}.silver.activities a
            ON zd.activity_id = a.activity_id AND zd.athlete_id = a.athlete_id
        WHERE zd.athlete_id = '{athlete_id}'
          AND a.start_time >= DATEADD(week, -4, CURRENT_DATE())
    """)
    if not zones_rows:
        return "No zone distribution data found for the last 4 weeks."

    total_sec = sum(r["duration_sec"] for r in zones_rows if r.get("duration_sec")) or 1

    def wavg(col):
        return round(sum(r[col] * r["duration_sec"] for r in zones_rows if r.get(col) and r.get("duration_sec")) / total_sec, 1)

    z = {i: wavg(f"zone_{i}_pct") for i in range(1, 8)}
    low = z[1] + z[2]
    grey = z[3] + z[4]
    high = z[5] + z[6] + z[7]

    recent = query(f"""
        SELECT zd.zone_5_pct, zd.zone_6_pct, zd.zone_7_pct
        FROM {CATALOG}.gold.zone_distribution zd
        JOIN {CATALOG}.silver.activities a ON zd.activity_id = a.activity_id
        WHERE zd.athlete_id = '{athlete_id}'
          AND a.start_time >= DATEADD(week, -2, CURRENT_DATE())
    """)
    has_recent_hi = bool(recent) and (sum((r.get("zone_5_pct", 0) or 0) + (r.get("zone_6_pct", 0) or 0) + (r.get("zone_7_pct", 0) or 0) for r in recent) / len(recent)) > 5.0

    flags, recs = [], []
    if low < 60:
        flags.append("POLARIZATION_DEFICIT")
        recs.append(f"Only {low}% in Z1-Z2 (target: >60%). Add more long, easy rides.")
    if grey > 30:
        flags.append("GREY_ZONE_OVERLOAD")
        recs.append(f"{grey}% in Z3-Z4 is too high. Go easier or harder, not moderate.")
    if not has_recent_hi and high < 5:
        flags.append("NO_RECENT_HIGH_INTENSITY")
        recs.append("No Z5+ work in 2 weeks. Add one VO2max interval session.")
    if not flags:
        flags.append("BALANCED")
        recs.append("Zone distribution looks well-balanced.")

    return json.dumps({
        "4_week_zones": {f"Z{i}_pct": z[i] for i in range(1, 8)},
        "summary": {"low_intensity_Z1_Z2_pct": low, "grey_zone_Z3_Z4_pct": grey, "high_intensity_Z5plus_pct": high},
        "flags": flags, "recommendations": recs,
    }, indent=2)


@tool
def compare_route_performances(athlete_id: str, keyword: str) -> str:
    """
    Search for rides matching a keyword and show performance trend over time.
    Use this when the athlete asks 'am I getting faster on my usual route?' or wants
    to compare performances on repeated routes or ride types.
    """
    rows = query(f"""
        SELECT activity_id, CAST(start_time AS DATE) AS date, name,
               ROUND(duration_sec / 60.0, 0) AS duration_min,
               avg_power_w, normalized_power, ROUND(tss, 0) AS tss,
               ROUND(elevation_gain_m, 0) AS elevation_m, intensity_factor
        FROM {CATALOG}.silver.activities
        WHERE athlete_id = '{athlete_id}'
          AND LOWER(name) LIKE LOWER('%{keyword}%')
        ORDER BY start_time ASC
    """)
    if not rows:
        return f"No rides found matching '{keyword}'."
    if len(rows) < 2:
        return json.dumps({"keyword": keyword, "message": "Only one matching ride found — need at least 2 for a trend.", "rides": rows}, indent=2, default=str)

    def delta(col):
        f, l = rows[0].get(col), rows[-1].get(col)
        return round(float(l) - float(f), 1) if f and l else None

    return json.dumps({
        "keyword": keyword,
        "matching_rides": len(rows),
        "date_range": f"{rows[0]['date']} → {rows[-1]['date']}",
        "trend_first_to_last": {
            "avg_power_delta_w": delta("avg_power_w"),
            "duration_delta_min": delta("duration_min"),
            "tss_delta": delta("tss"),
        },
        "rides": rows,
    }, indent=2, default=str)


analysis_tools = [
    analyze_activity,
    get_power_curve_trend,
    detect_training_imbalance,
    compare_route_performances,
]
