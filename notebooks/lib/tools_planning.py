# Databricks notebook source
# MAGIC %md
# MAGIC # lib/tools_planning — Workout & Ride Planning Tools
# MAGIC
# MAGIC Five tools for workout prescription and ride planning.
# MAGIC %run'd by 06_coaching_agent.py — do not run standalone.

# COMMAND ----------

from pyspark.sql import SparkSession
from langchain.tools import tool
import json
import math

spark = SparkSession.builder.getOrCreate()

# CATALOG set by parent notebook


@tool
def suggest_todays_workout(athlete_id: str) -> str:
    """
    Prescribe today's optimal workout based on current TSB (form), training load trends,
    weekly TSS so far, and days to goal event. Returns a structured workout with type,
    duration, target power zones, description, and target TSS.
    Use this when the athlete asks 'what should I do today?' or 'should I train hard today?'
    """
    # Get current training state
    load = spark.sql(f"""
        SELECT ctl, atl, tsb, form
        FROM {CATALOG}.gold.daily_training_load
        WHERE athlete_id = '{athlete_id}'
        ORDER BY date DESC LIMIT 1
    """).collect()

    if not load:
        return "No training load data available. Run the pipeline first."

    l = load[0]
    tsb = float(l.tsb)
    ctl = float(l.ctl)
    atl = float(l.atl)

    # Weekly TSS so far
    weekly = spark.sql(f"""
        SELECT COALESCE(SUM(tss), 0) AS weekly_tss_so_far
        FROM {CATALOG}.silver.activities
        WHERE athlete_id = '{athlete_id}'
          AND start_time >= DATE_TRUNC('week', CURRENT_DATE())
    """).collect()
    weekly_tss = float(weekly[0].weekly_tss_so_far) if weekly else 0.0

    # Days to goal event
    goals = spark.sql(f"""
        SELECT DATEDIFF(event_date, CURRENT_DATE()) AS days_to_goal
        FROM {CATALOG}.coach.athlete_goals
        WHERE athlete_id = '{athlete_id}' AND priority = 1
        ORDER BY event_date
        LIMIT 1
    """).collect()
    days_to_goal = int(goals[0].days_to_goal) if goals else 999

    # Athlete FTP
    athlete = spark.sql(f"""
        SELECT ftp_w, available_hours_week FROM {CATALOG}.silver.athletes WHERE athlete_id = '{athlete_id}'
    """).collect()
    ftp = int(athlete[0].ftp_w) if athlete and athlete[0].ftp_w else 250
    available_hours = float(athlete[0].available_hours_week) if athlete and athlete[0].available_hours_week else 8.0
    weekly_tss_target = available_hours * 60  # rough: 1 TSS/min at moderate intensity

    # Decision matrix
    if tsb < -30:
        workout = {
            "recommendation": "RECOVERY",
            "tsb": round(tsb, 1),
            "reason": f"TSB is {round(tsb, 1)} — you are overreached. Full rest or very easy spin only.",
            "type": "Recovery spin or full rest",
            "duration_min": 30,
            "target_power_pct_ftp": "< 55% FTP",
            "target_power_w": f"< {round(ftp * 0.55)}W",
            "target_zones": ["Z1"],
            "intensity_factor": "< 0.65",
            "target_tss": 20,
            "description": "30-minute easy spin, never exceeding Z1. Focus on flushing legs. If you feel terrible, take the day completely off.",
        }
    elif tsb < -10:
        # Productive training zone — type depends on imbalance check
        # Default to endurance/threshold progression
        if days_to_goal > 42:
            workout = {
                "recommendation": "PRODUCTIVE_BASE",
                "tsb": round(tsb, 1),
                "reason": f"TSB {round(tsb, 1)}: good productive training state with {days_to_goal} days to goal.",
                "type": "Endurance + sweet spot",
                "duration_min": 75,
                "target_power_pct_ftp": "65-88% FTP (Z2-Z3)",
                "target_power_w": f"{round(ftp * 0.65)}-{round(ftp * 0.88)}W",
                "target_zones": ["Z2", "Z3"],
                "intensity_factor": "0.70-0.80",
                "target_tss": 75,
                "description": "75-minute endurance ride, mostly Z2 with 2x10-minute sweet spot blocks (88% FTP). Build aerobic base while applying some threshold stimulus.",
            }
        else:
            workout = {
                "recommendation": "PRODUCTIVE_BUILD",
                "tsb": round(tsb, 1),
                "reason": f"TSB {round(tsb, 1)}: productive state, {days_to_goal} days to goal — build phase intensity.",
                "type": "Threshold intervals",
                "duration_min": 70,
                "target_power_pct_ftp": "95-105% FTP (Z4)",
                "target_power_w": f"{round(ftp * 0.95)}-{round(ftp * 1.05)}W",
                "target_zones": ["Z2", "Z4"],
                "intensity_factor": "0.82-0.88",
                "target_tss": 80,
                "description": "Warm up 15min Z2, then 3x10min at 95-100% FTP with 5min recovery, cool down 15min. Classic threshold session.",
            }
    elif tsb <= 5:
        workout = {
            "recommendation": "MODERATE_QUALITY",
            "tsb": round(tsb, 1),
            "reason": f"TSB {round(tsb, 1)}: neutral form — moderate quality session appropriate.",
            "type": "Tempo or VO2max",
            "duration_min": 60,
            "target_power_pct_ftp": "88-106% FTP (Z3-Z5)",
            "target_power_w": f"{round(ftp * 0.88)}-{round(ftp * 1.06)}W",
            "target_zones": ["Z2", "Z3", "Z5"],
            "intensity_factor": "0.78-0.85",
            "target_tss": 65,
            "description": "Warm up 15min, then 4x4min at 106% FTP (VO2max) with 4min easy recovery, cool down 10min. Short but high-quality stimulus.",
        }
    else:
        # TSB > +5 — fresh
        if days_to_goal <= 14:
            workout = {
                "recommendation": "RACE_PREP",
                "tsb": round(tsb, 1),
                "reason": f"TSB {round(tsb, 1)}: very fresh with race in {days_to_goal} days — activation only.",
                "type": "Race activation",
                "duration_min": 45,
                "target_power_pct_ftp": "60-100% FTP with 3 short efforts",
                "target_power_w": f"{round(ftp * 0.6)}-{round(ftp * 1.0)}W",
                "target_zones": ["Z1", "Z2", "Z4"],
                "intensity_factor": "0.68",
                "target_tss": 35,
                "description": "45-minute activation: 30min Z1-Z2 with 3x1min at threshold pace. Keep legs fresh, just remind muscles what hard effort feels like.",
            }
        else:
            workout = {
                "recommendation": "PRODUCTIVE_FRESH",
                "tsb": round(tsb, 1),
                "reason": f"TSB {round(tsb, 1)}: you're fresh — good time for quality work.",
                "type": "VO2max or sprint work",
                "duration_min": 75,
                "target_power_pct_ftp": "106-120% FTP with sprints",
                "target_power_w": f"{round(ftp * 1.06)}-{round(ftp * 1.2)}W",
                "target_zones": ["Z2", "Z5", "Z6"],
                "intensity_factor": "0.80",
                "target_tss": 70,
                "description": "Freshness is a weapon — use it. Warm up well then 5x4min at 110% FTP with full 5min recovery. Alternatively, a fast group ride or Zwift race.",
            }

    workout["context"] = {
        "current_ctl": round(ctl, 1),
        "current_atl": round(atl, 1),
        "weekly_tss_so_far": round(weekly_tss, 0),
        "weekly_tss_target": weekly_tss_target,
        "days_to_goal_event": days_to_goal,
        "athlete_ftp_w": ftp,
    }

    return json.dumps(workout, indent=2)


@tool
def generate_weekly_plan(athlete_id: str) -> str:
    """
    Generate a personalized 7-day training plan based on current CTL/ATL/TSB,
    available training hours, days to goal event, and weekly TSS trends.
    Returns a day-by-day schedule with workout type and target TSS for each day.
    Use this when the athlete asks for a weekly plan, how to structure their week,
    or 'what should my training look like this week?'
    """
    # Training state
    load = spark.sql(f"""
        SELECT ctl, atl, tsb, form
        FROM {CATALOG}.gold.daily_training_load
        WHERE athlete_id = '{athlete_id}'
        ORDER BY date DESC LIMIT 1
    """).collect()

    if not load:
        return "No training load data available."

    l = load[0]
    tsb = float(l.tsb)
    ctl = float(l.ctl)

    # Athlete profile
    athlete = spark.sql(f"""
        SELECT ftp_w, available_hours_week FROM {CATALOG}.silver.athletes WHERE athlete_id = '{athlete_id}'
    """).collect()
    ftp = int(athlete[0].ftp_w) if athlete and athlete[0].ftp_w else 250
    available_hours = float(athlete[0].available_hours_week) if athlete and athlete[0].available_hours_week else 8.0

    # Days to goal
    goals = spark.sql(f"""
        SELECT DATEDIFF(event_date, CURRENT_DATE()) AS days_to_goal
        FROM {CATALOG}.coach.athlete_goals
        WHERE athlete_id = '{athlete_id}' AND priority = 1
        ORDER BY event_date LIMIT 1
    """).collect()
    days_to_goal = int(goals[0].days_to_goal) if goals else 999

    # Recent weekly TSS trend (last 4 weeks)
    recent_tss = spark.sql(f"""
        SELECT ROUND(AVG(total_tss), 0) AS avg_weekly_tss
        FROM {CATALOG}.gold.weekly_summary
        WHERE athlete_id = '{athlete_id}'
        ORDER BY week_start DESC
        LIMIT 4
    """).collect()
    avg_weekly_tss = float(recent_tss[0].avg_weekly_tss) if recent_tss and recent_tss[0].avg_weekly_tss else 300.0

    # Determine training phase
    if days_to_goal <= 7:
        phase = "taper"
        target_weekly_tss = avg_weekly_tss * 0.5
    elif days_to_goal <= 14:
        phase = "pre_race"
        target_weekly_tss = avg_weekly_tss * 0.6
    elif days_to_goal <= 42:
        phase = "peak"
        target_weekly_tss = min(avg_weekly_tss * 1.05, available_hours * 65)
    elif tsb < -20:
        phase = "recovery"
        target_weekly_tss = avg_weekly_tss * 0.6
    else:
        phase = "build"
        target_weekly_tss = min(avg_weekly_tss * 1.05, available_hours * 65)

    target_weekly_tss = round(target_weekly_tss)

    # Build 7-day schedule based on phase and hours
    def make_day(day_name, workout_type, desc, tss, duration_min, zones):
        return {
            "day": day_name,
            "workout_type": workout_type,
            "description": desc,
            "target_tss": tss,
            "duration_min": duration_min,
            "target_zones": zones,
        }

    if phase in ("taper", "pre_race"):
        days = [
            make_day("Day 1 (Mon)", "Rest", "Full rest", 0, 0, []),
            make_day("Day 2 (Tue)", "Activation", f"45min easy + 3x1min at {round(ftp*0.95)}W", 30, 45, ["Z1", "Z2", "Z4"]),
            make_day("Day 3 (Wed)", "Easy spin", f"30min Z1-Z2 only", 20, 30, ["Z1", "Z2"]),
            make_day("Day 4 (Thu)", "Activation", f"45min with 2x5min at {round(ftp*0.9)}W", 35, 45, ["Z2", "Z4"]),
            make_day("Day 5 (Fri)", "Rest", "Full rest", 0, 0, []),
            make_day("Day 6 (Sat)", "Race simulation" if phase == "pre_race" else "Easy", "Short hard efforts to wake up legs", 40, 40, ["Z2", "Z5"]),
            make_day("Day 7 (Sun)", "RACE / Long easy", "Race day or 2hr easy aerobic if no race", 60, 90, ["Z1", "Z2"]),
        ]
    elif phase == "recovery":
        days = [
            make_day("Day 1 (Mon)", "Rest", "Full rest", 0, 0, []),
            make_day("Day 2 (Tue)", "Easy spin", f"45min Z1 only, {round(ftp*0.5)}W cap", 25, 45, ["Z1"]),
            make_day("Day 3 (Wed)", "Rest", "Full rest", 0, 0, []),
            make_day("Day 4 (Thu)", "Easy endurance", f"60min Z2, {round(ftp*0.75)}W avg", 40, 60, ["Z1", "Z2"]),
            make_day("Day 5 (Fri)", "Rest", "Full rest", 0, 0, []),
            make_day("Day 6 (Sat)", "Endurance", f"75min Z2 — first quality session this week", 55, 75, ["Z2"]),
            make_day("Day 7 (Sun)", "Easy spin", f"30min Z1, loosen up", 20, 30, ["Z1"]),
        ]
    elif phase == "peak":
        days = [
            make_day("Day 1 (Mon)", "Rest", "Full rest", 0, 0, []),
            make_day("Day 2 (Tue)", "Threshold", f"3x10min at {round(ftp*0.97)}W + Z2 base", 80, 70, ["Z2", "Z4"]),
            make_day("Day 3 (Wed)", "Endurance", f"90min steady Z2 at {round(ftp*0.72)}W", 65, 90, ["Z2"]),
            make_day("Day 4 (Thu)", "VO2max", f"5x4min at {round(ftp*1.1)}W, 4min rest", 70, 65, ["Z2", "Z5"]),
            make_day("Day 5 (Fri)", "Rest or easy", "Rest or 30min easy spin", 15, 30, ["Z1"]),
            make_day("Day 6 (Sat)", "Long endurance", f"2.5-3hr Z2 ride, {round(ftp*0.70)}W avg", 130, 165, ["Z2", "Z3"]),
            make_day("Day 7 (Sun)", "Easy spin", "1hr active recovery Z1-Z2", 40, 60, ["Z1", "Z2"]),
        ]
    else:  # build
        days = [
            make_day("Day 1 (Mon)", "Rest", "Full rest", 0, 0, []),
            make_day("Day 2 (Tue)", "Sweet spot", f"2x20min at {round(ftp*0.9)}W + warm-up/cool-down", 75, 75, ["Z2", "Z3"]),
            make_day("Day 3 (Wed)", "Endurance", f"60-75min Z2 at {round(ftp*0.70)}W", 50, 70, ["Z2"]),
            make_day("Day 4 (Thu)", "Threshold", f"3x8min at {round(ftp*0.98)}W, full recovery", 70, 65, ["Z2", "Z4"]),
            make_day("Day 5 (Fri)", "Rest", "Full rest", 0, 0, []),
            make_day("Day 6 (Sat)", "Long ride", f"2-3hr endurance, {round(ftp*0.70)}W avg", 120, 150, ["Z2", "Z3"]),
            make_day("Day 7 (Sun)", "Recovery spin", "45min Z1, flush the legs", 25, 45, ["Z1"]),
        ]

    actual_tss = sum(d["target_tss"] for d in days)

    return json.dumps({
        "training_phase": phase,
        "current_tsb": round(tsb, 1),
        "current_ctl": round(ctl, 1),
        "days_to_goal": days_to_goal,
        "available_hours_per_week": available_hours,
        "target_weekly_tss": target_weekly_tss,
        "planned_weekly_tss": actual_tss,
        "weekly_plan": days,
        "note": "Adjust workout days to fit your schedule — the order matters less than the recovery between hard sessions.",
    }, indent=2)


@tool
def get_saved_training_plan(athlete_id: str) -> str:
    """
    Retrieve the athlete's current saved training plan including phase, start/end dates,
    and upcoming workouts. Use this when the athlete asks about their training plan,
    what phase they're in, or what's coming up in their schedule.
    """
    plan = spark.sql(f"""
        SELECT plan_id, phase, start_date, end_date, goal_event_name, created_at
        FROM {CATALOG}.coach.training_plans
        WHERE athlete_id = '{athlete_id}'
        ORDER BY created_at DESC
        LIMIT 1
    """).collect()

    if not plan:
        return "No saved training plan found. Run notebook 07_training_planner to generate one."

    p = plan[0]
    plan_id = p.plan_id

    workouts = spark.sql(f"""
        SELECT planned_date, workout_type, description, target_tss, duration_min, target_zones, completed
        FROM {CATALOG}.coach.planned_workouts
        WHERE plan_id = '{plan_id}'
          AND planned_date >= CURRENT_DATE()
        ORDER BY planned_date
        LIMIT 14
    """).toPandas()

    return json.dumps({
        "plan_id": plan_id,
        "phase": p.phase,
        "start_date": str(p.start_date),
        "end_date": str(p.end_date),
        "goal_event": p.goal_event_name,
        "created_at": str(p.created_at),
        "upcoming_workouts": workouts.to_dict(orient="records") if not workouts.empty else [],
    }, indent=2, default=str)


@tool
def suggest_route(athlete_id: str, duration_min: int, elevation_preference: str = "moderate") -> str:
    """
    Suggest 1-3 routes from the athlete's history that match a target duration
    and elevation preference (flat/moderate/hilly). Matches target duration against
    historical pace. Use this when the athlete asks what route to ride today,
    wants a route recommendation, or asks 'where should I ride?'
    """
    # Get athlete's avg speed from recent activities for duration estimation
    speed_data = spark.sql(f"""
        SELECT AVG(distance_m / duration_sec) AS avg_speed_ms
        FROM {CATALOG}.silver.activities
        WHERE athlete_id = '{athlete_id}'
          AND duration_sec > 1800
          AND distance_m > 0
    """).collect()

    avg_speed_ms = float(speed_data[0].avg_speed_ms) if speed_data and speed_data[0].avg_speed_ms else 8.0
    target_distance_km = round(avg_speed_ms * (duration_min * 60) / 1000, 1)

    # Elevation preference filter
    if elevation_preference.lower() == "flat":
        elev_filter = "elevation_gain_m < 500"
    elif elevation_preference.lower() == "hilly":
        elev_filter = "elevation_gain_m > 1000"
    else:  # moderate
        elev_filter = "elevation_gain_m BETWEEN 300 AND 1200"

    routes = spark.sql(f"""
        SELECT
            route_id, name, distance_m / 1000.0 AS distance_km,
            elevation_gain_m, surface_type, source_system
        FROM {CATALOG}.silver.routes
        WHERE {elev_filter}
          AND ABS(distance_m / 1000.0 - {target_distance_km}) < {target_distance_km * 0.3}
        ORDER BY ABS(distance_m / 1000.0 - {target_distance_km})
        LIMIT 3
    """).toPandas()

    if routes.empty:
        return json.dumps({
            "message": f"No saved routes found matching {duration_min}min / {elevation_preference} elevation. Try logging more routes in RideWithGPS.",
            "target_distance_km": target_distance_km,
            "avg_speed_kph": round(avg_speed_ms * 3.6, 1),
        }, indent=2)

    suggestions = []
    for _, row in routes.iterrows():
        est_duration = round((row["distance_km"] / (avg_speed_ms * 3.6)) * 60) if avg_speed_ms > 0 else None
        difficulty = "easy" if row["elevation_gain_m"] < 500 else ("moderate" if row["elevation_gain_m"] < 1000 else "hard")
        suggestions.append({
            "route_id": row["route_id"],
            "name": row["name"],
            "distance_km": round(float(row["distance_km"]), 1),
            "elevation_m": int(row["elevation_gain_m"]) if row["elevation_gain_m"] else None,
            "estimated_duration_min": est_duration,
            "difficulty": difficulty,
            "surface": row["surface_type"],
        })

    return json.dumps({
        "target_duration_min": duration_min,
        "elevation_preference": elevation_preference,
        "suggestions": suggestions,
    }, indent=2, default=str)


@tool
def estimate_ride_tss(duration_min: float, avg_power_w: float, ftp_w: float) -> str:
    """
    Calculate TSS, intensity factor (IF), and training zone for a planned ride.
    Formula: TSS = (duration_hours * NP^2 / FTP^2) * 100, assuming avg_power ≈ NP.
    Use this when the athlete wants to know how hard a planned ride will be,
    or asks 'if I ride for X minutes at Y watts, what TSS will I get?'
    """
    if ftp_w <= 0 or duration_min <= 0:
        return "Invalid inputs: FTP and duration must be positive."

    duration_hours = duration_min / 60.0
    intensity_factor = avg_power_w / ftp_w
    tss = round(duration_hours * (intensity_factor ** 2) * 100, 1)

    if intensity_factor < 0.55:
        zone = "Z1 Recovery"
        effort = "Very easy — active recovery"
    elif intensity_factor < 0.75:
        zone = "Z2 Endurance"
        effort = "Easy aerobic — can hold a conversation"
    elif intensity_factor < 0.87:
        zone = "Z3 Tempo"
        effort = "Moderate — comfortably hard"
    elif intensity_factor < 0.95:
        zone = "Z4 Sub-threshold (sweet spot)"
        effort = "Hard but sustainable for 30-60min"
    elif intensity_factor < 1.05:
        zone = "Z4/Z5 Threshold"
        effort = "Very hard — FTP effort, 60min maximal"
    elif intensity_factor < 1.20:
        zone = "Z5 VO2max"
        effort = "Extremely hard — 4-8min maximal"
    else:
        zone = "Z6-Z7 Anaerobic/Sprint"
        effort = "All-out — seconds to a few minutes"

    recovery_guidance = (
        "Light day or rest tomorrow" if tss < 50 else
        "Normal recovery (1 rest day sufficient)" if tss < 100 else
        "Full rest day needed tomorrow" if tss < 150 else
        "2+ recovery days — significant load"
    )

    return json.dumps({
        "inputs": {
            "duration_min": duration_min,
            "avg_power_w": avg_power_w,
            "ftp_w": ftp_w,
        },
        "results": {
            "tss": tss,
            "intensity_factor": round(intensity_factor, 2),
            "pct_of_ftp": f"{round(intensity_factor * 100, 0)}%",
            "zone": zone,
            "effort_description": effort,
            "recovery_needed": recovery_guidance,
        }
    }, indent=2)


@tool
def plan_ride_pacing(athlete_id: str, target_duration_min: float, target_tss: float) -> str:
    """
    Back-calculate the required average power to hit a target TSS in a given duration.
    Returns target average power, intensity factor, zone guidance, and effort description.
    Use this when the athlete wants to plan a ride with a specific training stress target,
    or asks 'how hard should I ride to get X TSS in Y minutes?'
    """
    athlete = spark.sql(f"""
        SELECT ftp_w FROM {CATALOG}.silver.athletes WHERE athlete_id = '{athlete_id}'
    """).collect()
    ftp = float(athlete[0].ftp_w) if athlete and athlete[0].ftp_w else None

    if not ftp:
        return "Athlete FTP not found. Run notebook 05_athlete_setup first."
    if target_duration_min <= 0 or target_tss <= 0:
        return "Invalid inputs: duration and target TSS must be positive."

    duration_hours = target_duration_min / 60.0

    # TSS = duration_h * IF^2 * 100 → IF = sqrt(TSS / (duration_h * 100))
    intensity_factor = math.sqrt(target_tss / (duration_hours * 100))
    target_avg_power = round(intensity_factor * ftp)

    # Zone
    if intensity_factor < 0.55:
        zone = "Z1 Recovery"
        suggestion = "This is a very easy recovery ride."
    elif intensity_factor < 0.75:
        zone = "Z2 Endurance"
        suggestion = "Steady aerobic — keep HR in zone 2, conversational pace."
    elif intensity_factor < 0.87:
        zone = "Z3 Tempo"
        suggestion = "Comfortably hard. Good for sweet spot blocks."
    elif intensity_factor < 1.05:
        zone = "Z4 Threshold"
        suggestion = "Threshold effort. Doable for 20-60min. Discipline required."
    else:
        zone = "Z5+ VO2max / Anaerobic"
        suggestion = "Very high intensity — only achievable in short intervals, not a sustained average."
        # Flag unrealistic TSS
        max_realistic_tss = round(duration_hours * (0.85 ** 2) * 100)  # ~IF 0.85 max sustained
        if target_tss > max_realistic_tss * 1.2:
            return json.dumps({
                "warning": f"Target TSS of {target_tss} in {target_duration_min}min requires IF={round(intensity_factor,2)}, which is unrealistic as a sustained average power.",
                "max_realistic_tss_for_duration": max_realistic_tss,
                "suggestion": f"Reduce target TSS to {max_realistic_tss} or extend duration.",
            }, indent=2)

    # Zone distribution suggestion
    if intensity_factor < 0.75:
        zone_dist = "90%+ Z2, minimal higher zone work"
    elif intensity_factor < 0.87:
        zone_dist = "60% Z2, 30% Z3, 10% Z4 sweet spot blocks"
    else:
        zone_dist = "Warm-up in Z2, main set in Z4, recovery in Z1-Z2"

    return json.dumps({
        "athlete_ftp_w": int(ftp),
        "target_duration_min": target_duration_min,
        "target_tss": target_tss,
        "pacing_prescription": {
            "target_avg_power_w": target_avg_power,
            "intensity_factor": round(intensity_factor, 2),
            "pct_of_ftp": f"{round(intensity_factor * 100, 0)}%",
            "zone": zone,
            "suggested_zone_distribution": zone_dist,
        },
        "coaching_note": suggestion,
    }, indent=2)


# Exported list
planning_tools = [
    suggest_todays_workout,
    generate_weekly_plan,
    get_saved_training_plan,
    suggest_route,
    estimate_ride_tss,
    plan_ride_pacing,
]

print(f"  lib/tools_planning loaded: {len(planning_tools)} tools")
