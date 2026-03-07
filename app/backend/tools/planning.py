"""
Workout and ride planning tools — ported from notebooks/lib/tools_planning.py.
"""
from __future__ import annotations

import json
import math
from langchain.tools import tool
from db.client import query, query_one, CATALOG


@tool
def suggest_todays_workout(athlete_id: str) -> str:
    """
    Prescribe today's optimal workout based on current TSB, training load trends,
    weekly TSS so far, and days to goal event. Returns a structured workout with type,
    duration, target power zones, description, and target TSS.
    Use this when the athlete asks 'what should I do today?' or 'should I train hard today?'
    """
    load = query_one(f"""
        SELECT ctl, atl, tsb, form FROM {CATALOG}.gold.daily_training_load
        WHERE athlete_id = '{athlete_id}' ORDER BY date DESC LIMIT 1
    """)
    if not load:
        return "No training load data available. Run the pipeline first."

    tsb, ctl, atl = float(load["tsb"]), float(load["ctl"]), float(load["atl"])

    weekly = query_one(f"""
        SELECT COALESCE(SUM(tss), 0) AS weekly_tss_so_far
        FROM {CATALOG}.silver.activities
        WHERE athlete_id = '{athlete_id}' AND start_time >= DATE_TRUNC('week', CURRENT_DATE())
    """)
    weekly_tss = float(weekly["weekly_tss_so_far"]) if weekly else 0.0

    goals = query_one(f"""
        SELECT DATEDIFF(event_date, CURRENT_DATE()) AS days_to_goal
        FROM {CATALOG}.coach.athlete_goals
        WHERE athlete_id = '{athlete_id}' AND priority = 1
        ORDER BY event_date LIMIT 1
    """)
    days_to_goal = int(goals["days_to_goal"]) if goals else 999

    athlete = query_one(f"SELECT ftp_w, available_hours_week FROM {CATALOG}.silver.athletes WHERE athlete_id = '{athlete_id}'")
    ftp = int(athlete["ftp_w"]) if athlete and athlete.get("ftp_w") else 250
    available_hours = float(athlete["available_hours_week"]) if athlete and athlete.get("available_hours_week") else 8.0

    if tsb < -30:
        workout = {
            "recommendation": "RECOVERY", "tsb": round(tsb, 1),
            "reason": f"TSB is {round(tsb, 1)} — you are overreached. Full rest or very easy spin only.",
            "type": "Recovery spin or full rest", "duration_min": 30,
            "target_power_w": f"< {round(ftp * 0.55)}W", "target_zones": ["Z1"],
            "intensity_factor": "< 0.65", "target_tss": 20,
            "description": "30-minute easy spin, never exceeding Z1. If you feel terrible, take the day completely off.",
        }
    elif tsb < -10:
        if days_to_goal > 42:
            workout = {
                "recommendation": "PRODUCTIVE_BASE", "tsb": round(tsb, 1),
                "reason": f"TSB {round(tsb, 1)}: good productive training state with {days_to_goal} days to goal.",
                "type": "Endurance + sweet spot", "duration_min": 75,
                "target_power_w": f"{round(ftp * 0.65)}-{round(ftp * 0.88)}W", "target_zones": ["Z2", "Z3"],
                "intensity_factor": "0.70-0.80", "target_tss": 75,
                "description": "75-minute endurance ride, mostly Z2 with 2x10-minute sweet spot blocks (88% FTP).",
            }
        else:
            workout = {
                "recommendation": "PRODUCTIVE_BUILD", "tsb": round(tsb, 1),
                "reason": f"TSB {round(tsb, 1)}: productive state, {days_to_goal} days to goal.",
                "type": "Threshold intervals", "duration_min": 70,
                "target_power_w": f"{round(ftp * 0.95)}-{round(ftp * 1.05)}W", "target_zones": ["Z2", "Z4"],
                "intensity_factor": "0.82-0.88", "target_tss": 80,
                "description": f"15min warm-up Z2, 3x10min at {round(ftp * 0.97)}W with 5min recovery, 15min cool-down.",
            }
    elif tsb <= 5:
        workout = {
            "recommendation": "MODERATE_QUALITY", "tsb": round(tsb, 1),
            "reason": f"TSB {round(tsb, 1)}: neutral form — moderate quality session appropriate.",
            "type": "VO2max", "duration_min": 60,
            "target_power_w": f"{round(ftp * 1.06)}-{round(ftp * 1.12)}W", "target_zones": ["Z2", "Z5"],
            "intensity_factor": "0.78-0.85", "target_tss": 65,
            "description": f"15min warm-up, 4x4min at {round(ftp * 1.08)}W with 4min easy recovery, 10min cool-down.",
        }
    else:
        if days_to_goal <= 14:
            workout = {
                "recommendation": "RACE_PREP", "tsb": round(tsb, 1),
                "reason": f"TSB {round(tsb, 1)}: very fresh with race in {days_to_goal} days.",
                "type": "Race activation", "duration_min": 45,
                "target_power_w": f"{round(ftp * 0.6)}-{round(ftp)}W", "target_zones": ["Z1", "Z2", "Z4"],
                "intensity_factor": "0.68", "target_tss": 35,
                "description": "45-minute activation: 30min Z1-Z2 with 3x1min at threshold pace.",
            }
        else:
            workout = {
                "recommendation": "PRODUCTIVE_FRESH", "tsb": round(tsb, 1),
                "reason": f"TSB {round(tsb, 1)}: you're fresh — use it for quality work.",
                "type": "VO2max or sprint", "duration_min": 75,
                "target_power_w": f"{round(ftp * 1.06)}-{round(ftp * 1.2)}W", "target_zones": ["Z2", "Z5", "Z6"],
                "intensity_factor": "0.80", "target_tss": 70,
                "description": f"5x4min at {round(ftp * 1.1)}W with full 5min recovery. Alternatively a Zwift race.",
            }

    workout["context"] = {
        "current_ctl": round(ctl, 1), "current_atl": round(atl, 1),
        "weekly_tss_so_far": round(weekly_tss, 0), "days_to_goal_event": days_to_goal, "ftp_w": ftp,
    }
    return json.dumps(workout, indent=2)


@tool
def generate_weekly_plan(athlete_id: str) -> str:
    """
    Generate a personalized 7-day training plan based on current CTL/ATL/TSB,
    available training hours, days to goal event, and weekly TSS trends.
    Use this when the athlete asks for a weekly plan or how to structure their week.
    """
    load = query_one(f"""
        SELECT ctl, atl, tsb FROM {CATALOG}.gold.daily_training_load
        WHERE athlete_id = '{athlete_id}' ORDER BY date DESC LIMIT 1
    """)
    if not load:
        return "No training load data available."

    tsb, ctl = float(load["tsb"]), float(load["ctl"])
    athlete = query_one(f"SELECT ftp_w, available_hours_week FROM {CATALOG}.silver.athletes WHERE athlete_id = '{athlete_id}'")
    ftp = int(athlete["ftp_w"]) if athlete and athlete.get("ftp_w") else 250
    available_hours = float(athlete["available_hours_week"]) if athlete and athlete.get("available_hours_week") else 8.0

    goals = query_one(f"""
        SELECT DATEDIFF(event_date, CURRENT_DATE()) AS days_to_goal
        FROM {CATALOG}.coach.athlete_goals WHERE athlete_id = '{athlete_id}' AND priority = 1
        ORDER BY event_date LIMIT 1
    """)
    days_to_goal = int(goals["days_to_goal"]) if goals else 999

    avg_row = query_one(f"""
        SELECT ROUND(AVG(total_tss), 0) AS avg_weekly_tss FROM {CATALOG}.gold.weekly_summary
        WHERE athlete_id = '{athlete_id}' ORDER BY week_start DESC LIMIT 4
    """)
    avg_tss = float(avg_row["avg_weekly_tss"]) if avg_row and avg_row.get("avg_weekly_tss") else 300.0

    if days_to_goal <= 7:
        phase, factor = "taper", 0.5
    elif days_to_goal <= 14:
        phase, factor = "pre_race", 0.6
    elif tsb < -20:
        phase, factor = "recovery", 0.6
    elif days_to_goal <= 42:
        phase, factor = "peak", 1.05
    else:
        phase, factor = "build", 1.05

    target_tss = round(min(avg_tss * factor, available_hours * 65))

    def day(name, wtype, desc, tss, dur, zones):
        return {"day": name, "workout_type": wtype, "description": desc,
                "target_tss": tss, "duration_min": dur, "target_zones": zones}

    if phase in ("taper", "pre_race"):
        days = [
            day("Mon", "Rest", "Full rest", 0, 0, []),
            day("Tue", "Activation", f"45min + 3x1min at {round(ftp*.95)}W", 30, 45, ["Z1","Z2","Z4"]),
            day("Wed", "Easy spin", "30min Z1-Z2 only", 20, 30, ["Z1","Z2"]),
            day("Thu", "Activation", f"45min with 2x5min at {round(ftp*.9)}W", 35, 45, ["Z2","Z4"]),
            day("Fri", "Rest", "Full rest", 0, 0, []),
            day("Sat", "Short quality", "Short efforts to wake up legs", 40, 40, ["Z2","Z5"]),
            day("Sun", "Race / Long easy", "Race day or 2hr easy aerobic", 60, 90, ["Z1","Z2"]),
        ]
    elif phase == "recovery":
        days = [
            day("Mon", "Rest", "Full rest", 0, 0, []),
            day("Tue", "Easy spin", f"45min Z1, {round(ftp*.5)}W cap", 25, 45, ["Z1"]),
            day("Wed", "Rest", "Full rest", 0, 0, []),
            day("Thu", "Easy endurance", f"60min Z2, {round(ftp*.75)}W avg", 40, 60, ["Z1","Z2"]),
            day("Fri", "Rest", "Full rest", 0, 0, []),
            day("Sat", "Endurance", "75min Z2 — first quality session", 55, 75, ["Z2"]),
            day("Sun", "Easy spin", "30min Z1, loosen up", 20, 30, ["Z1"]),
        ]
    elif phase == "peak":
        days = [
            day("Mon", "Rest", "Full rest", 0, 0, []),
            day("Tue", "Threshold", f"3x10min at {round(ftp*.97)}W + Z2 base", 80, 70, ["Z2","Z4"]),
            day("Wed", "Endurance", f"90min Z2 at {round(ftp*.72)}W", 65, 90, ["Z2"]),
            day("Thu", "VO2max", f"5x4min at {round(ftp*1.1)}W, 4min rest", 70, 65, ["Z2","Z5"]),
            day("Fri", "Rest or easy", "Rest or 30min easy spin", 15, 30, ["Z1"]),
            day("Sat", "Long endurance", f"2.5-3hr Z2 at {round(ftp*.70)}W avg", 130, 165, ["Z2","Z3"]),
            day("Sun", "Easy spin", "1hr active recovery Z1-Z2", 40, 60, ["Z1","Z2"]),
        ]
    else:
        days = [
            day("Mon", "Rest", "Full rest", 0, 0, []),
            day("Tue", "Sweet spot", f"2x20min at {round(ftp*.9)}W", 75, 75, ["Z2","Z3"]),
            day("Wed", "Endurance", f"60-75min Z2 at {round(ftp*.70)}W", 50, 70, ["Z2"]),
            day("Thu", "Threshold", f"3x8min at {round(ftp*.98)}W, full recovery", 70, 65, ["Z2","Z4"]),
            day("Fri", "Rest", "Full rest", 0, 0, []),
            day("Sat", "Long ride", f"2-3hr endurance, {round(ftp*.70)}W avg", 120, 150, ["Z2","Z3"]),
            day("Sun", "Recovery spin", "45min Z1, flush the legs", 25, 45, ["Z1"]),
        ]

    return json.dumps({
        "training_phase": phase, "current_tsb": round(tsb, 1), "current_ctl": round(ctl, 1),
        "days_to_goal": days_to_goal, "available_hours_per_week": available_hours,
        "target_weekly_tss": target_tss, "planned_weekly_tss": sum(d["target_tss"] for d in days),
        "weekly_plan": days,
    }, indent=2)


@tool
def get_saved_training_plan(athlete_id: str) -> str:
    """
    Retrieve the athlete's current saved training plan including phase, dates, and
    upcoming workouts. Use this when the athlete asks about their training plan,
    what phase they're in, or what's coming up in their schedule.
    """
    plan = query_one(f"""
        SELECT plan_id, phase, start_date, end_date, goal_event_name, created_at
        FROM {CATALOG}.coach.training_plans WHERE athlete_id = '{athlete_id}'
        ORDER BY created_at DESC LIMIT 1
    """)
    if not plan:
        return "No saved training plan found. Run notebook 07_training_planner to generate one."

    workouts = query(f"""
        SELECT scheduled_date, workout_type, instructions, tss_target, duration_min, completed
        FROM {CATALOG}.coach.planned_workouts
        WHERE plan_id = '{plan["plan_id"]}' AND scheduled_date >= CURRENT_DATE()
        ORDER BY scheduled_date LIMIT 14
    """)
    return json.dumps({
        "plan_id": plan["plan_id"], "phase": plan["phase"],
        "start_date": str(plan["start_date"]), "end_date": str(plan["end_date"]),
        "goal_event": plan.get("goal_event_name"), "created_at": str(plan["created_at"]),
        "upcoming_workouts": workouts,
    }, indent=2, default=str)


@tool
def suggest_route(athlete_id: str, duration_min: int, elevation_preference: str = "moderate") -> str:
    """
    Suggest routes from the athlete's history matching a target duration and elevation
    preference (flat/moderate/hilly). Use this when the athlete asks what route to ride
    or 'where should I ride today?'
    """
    speed_row = query_one(f"""
        SELECT AVG(distance_m / duration_sec) AS avg_speed_ms FROM {CATALOG}.silver.activities
        WHERE athlete_id = '{athlete_id}' AND duration_sec > 1800 AND distance_m > 0
    """)
    avg_speed_ms = float(speed_row["avg_speed_ms"]) if speed_row and speed_row.get("avg_speed_ms") else 8.0
    target_km = round(avg_speed_ms * (duration_min * 60) / 1000, 1)

    elev_filter = {
        "flat": "elevation_gain_m < 500",
        "hilly": "elevation_gain_m > 1000",
    }.get(elevation_preference.lower(), "elevation_gain_m BETWEEN 300 AND 1200")

    routes = query(f"""
        SELECT route_id, name, distance_m / 1000.0 AS distance_km, elevation_gain_m, surface_type
        FROM {CATALOG}.silver.routes
        WHERE {elev_filter} AND ABS(distance_m / 1000.0 - {target_km}) < {target_km * 0.3}
        ORDER BY ABS(distance_m / 1000.0 - {target_km}) LIMIT 3
    """)
    if not routes:
        return json.dumps({"message": f"No routes found matching {duration_min}min / {elevation_preference}.", "target_km": target_km}, indent=2)

    suggestions = []
    for r in routes:
        est_dur = round((float(r["distance_km"]) / (avg_speed_ms * 3.6)) * 60) if avg_speed_ms > 0 else None
        suggestions.append({
            "route_id": r["route_id"], "name": r["name"],
            "distance_km": round(float(r["distance_km"]), 1),
            "elevation_m": int(r["elevation_gain_m"]) if r.get("elevation_gain_m") else None,
            "estimated_duration_min": est_dur,
            "difficulty": "easy" if (r.get("elevation_gain_m") or 0) < 500 else ("moderate" if (r.get("elevation_gain_m") or 0) < 1000 else "hard"),
        })
    return json.dumps({"target_duration_min": duration_min, "elevation_preference": elevation_preference, "suggestions": suggestions}, indent=2, default=str)


@tool
def estimate_ride_tss(duration_min: float, avg_power_w: float, ftp_w: float) -> str:
    """
    Calculate TSS and intensity factor for a planned ride.
    Use this when the athlete wants to know how hard a planned ride will be,
    e.g. 'if I ride for 90 minutes at 200W with FTP 250W, what TSS will I get?'
    """
    if ftp_w <= 0 or duration_min <= 0:
        return "Invalid inputs."
    duration_h = duration_min / 60.0
    intensity_factor = avg_power_w / ftp_w
    tss = round(duration_h * (intensity_factor ** 2) * 100, 1)

    if intensity_factor < 0.55:
        zone, effort = "Z1 Recovery", "Very easy — active recovery"
    elif intensity_factor < 0.75:
        zone, effort = "Z2 Endurance", "Easy aerobic, conversational"
    elif intensity_factor < 0.87:
        zone, effort = "Z3 Tempo", "Comfortably hard"
    elif intensity_factor < 1.05:
        zone, effort = "Z4 Threshold", "Very hard — FTP-level effort"
    elif intensity_factor < 1.20:
        zone, effort = "Z5 VO2max", "Extremely hard — 4-8min maximal"
    else:
        zone, effort = "Z6-Z7 Anaerobic/Sprint", "All-out — seconds to minutes"

    return json.dumps({
        "inputs": {"duration_min": duration_min, "avg_power_w": avg_power_w, "ftp_w": ftp_w},
        "results": {
            "tss": tss, "intensity_factor": round(intensity_factor, 2),
            "pct_of_ftp": f"{round(intensity_factor * 100)}%",
            "zone": zone, "effort_description": effort,
            "recovery_needed": (
                "Light day tomorrow" if tss < 50 else
                "1 rest day sufficient" if tss < 100 else
                "Full rest day needed" if tss < 150 else
                "2+ recovery days"
            ),
        },
    }, indent=2)


@tool
def plan_ride_pacing(athlete_id: str, target_duration_min: float, target_tss: float) -> str:
    """
    Back-calculate the required average power to hit a target TSS in a given duration.
    Use this when the athlete wants to plan a ride with a specific training stress target,
    e.g. 'how hard should I ride to get 80 TSS in 75 minutes?'
    """
    athlete = query_one(f"SELECT ftp_w FROM {CATALOG}.silver.athletes WHERE athlete_id = '{athlete_id}'")
    ftp = float(athlete["ftp_w"]) if athlete and athlete.get("ftp_w") else None
    if not ftp:
        return "Athlete FTP not found."
    if target_duration_min <= 0 or target_tss <= 0:
        return "Invalid inputs."

    duration_h = target_duration_min / 60.0
    intensity_factor = math.sqrt(target_tss / (duration_h * 100))
    target_power = round(intensity_factor * ftp)

    if intensity_factor > 0.95:
        max_tss = round(duration_h * (0.85 ** 2) * 100)
        if target_tss > max_tss * 1.2:
            return json.dumps({
                "warning": f"TSS {target_tss} in {target_duration_min}min requires IF={round(intensity_factor,2)}, which is unrealistic as a sustained average.",
                "max_realistic_tss": max_tss,
            }, indent=2)

    zone = (
        "Z1" if intensity_factor < 0.55 else
        "Z2 Endurance" if intensity_factor < 0.75 else
        "Z3 Tempo" if intensity_factor < 0.87 else
        "Z4 Threshold" if intensity_factor < 1.05 else
        "Z5+ VO2max"
    )
    return json.dumps({
        "ftp_w": int(ftp), "target_duration_min": target_duration_min, "target_tss": target_tss,
        "pacing": {
            "target_avg_power_w": target_power, "intensity_factor": round(intensity_factor, 2),
            "pct_of_ftp": f"{round(intensity_factor * 100)}%", "zone": zone,
        },
    }, indent=2)


planning_tools = [
    suggest_todays_workout,
    generate_weekly_plan,
    get_saved_training_plan,
    suggest_route,
    estimate_ride_tss,
    plan_ride_pacing,
]
