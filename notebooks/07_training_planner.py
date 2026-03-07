# Databricks notebook source
# MAGIC %md
# MAGIC # 07 — Training Planner
# MAGIC
# MAGIC Generates and saves multi-week training plans to Delta tables.
# MAGIC Plans are then queryable by the coaching agent via `get_saved_training_plan`.
# MAGIC
# MAGIC ## Training Phases
# MAGIC - **Base**: Z2 volume focus, build aerobic engine
# MAGIC - **Build**: Add threshold / sweet spot work on top of base
# MAGIC - **Peak**: Race-specific intensity, maintain fitness, sharpen
# MAGIC - **Taper**: Reduce volume, maintain intensity, arrive fresh
# MAGIC
# MAGIC **Run after:** notebook 05 (athlete profile must exist)

# COMMAND ----------

# MAGIC %pip install databricks-langchain langchain-core -q

# COMMAND ----------

# MAGIC %restart_python

# COMMAND ----------

# MAGIC %md ## Configuration

# COMMAND ----------

CATALOG = "ai_coach"
ATHLETE_ID = "athlete_1"

print(f"Catalog:  {CATALOG}")
print(f"Athlete:  {ATHLETE_ID}")

# COMMAND ----------

# MAGIC %md ## Ensure Tables Exist

# COMMAND ----------

from pyspark.sql import SparkSession
spark = SparkSession.builder.getOrCreate()

# ── Ensure correct schema ────────────────────────────────────────────────────
# If planned_workouts was previously created with duration_min INT (type mismatch),
# Delta will reject DOUBLE writes. Drop and recreate to fix.

def _col_type(catalog, schema, table, col_name):
    try:
        rows = spark.sql(f"DESCRIBE TABLE {catalog}.{schema}.{table}").collect()
        for r in rows:
            if r["col_name"] == col_name:
                return r["data_type"].upper()
    except Exception:
        pass
    return None

# Check for type conflict on planned_workouts.duration_min
existing_type = _col_type(CATALOG, "coach", "planned_workouts", "duration_min")
if existing_type is not None and existing_type != "DOUBLE":
    print(f"⚠️  planned_workouts.duration_min is {existing_type}, expected DOUBLE — dropping and recreating table")
    spark.sql(f"DROP TABLE IF EXISTS {CATALOG}.coach.planned_workouts")

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.coach.training_plans (
    plan_id         STRING NOT NULL,
    athlete_id      STRING NOT NULL,
    phase           STRING,
    start_date      DATE,
    end_date        DATE,
    goal_event_name STRING,
    goal_event_date DATE,
    target_ctl_end  DOUBLE,
    notes           STRING,
    created_at      TIMESTAMP
) USING DELTA
""")

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.coach.planned_workouts (
    workout_id      STRING NOT NULL,
    plan_id         STRING NOT NULL,
    athlete_id      STRING NOT NULL,
    planned_date    DATE,
    workout_type    STRING,
    description     STRING,
    target_tss      DOUBLE,
    duration_min    DOUBLE,
    target_zones    STRING,
    target_power_w  DOUBLE,
    completed       BOOLEAN,
    actual_tss      DOUBLE,
    notes           STRING
) USING DELTA
""")

print("✅ Tables ready")

# COMMAND ----------

# MAGIC %md ## Training Phase Logic

# COMMAND ----------

import uuid
import math
from datetime import date, timedelta
from pyspark.sql.types import (
    StructType, StructField, StringType, DateType, DoubleType,
    BooleanType, TimestampType
)
from pyspark.sql import Row
from datetime import datetime


def compute_phase_schedule(start_date: date, goal_date: date, current_ctl: float) -> list[dict]:
    """
    Given a start date and goal event, compute week-by-week phases.
    Returns list of dicts: {week_num, week_start, phase, target_tss_multiplier}.
    Classic periodization: Base → Build → Peak → Taper
    """
    total_weeks = max(1, math.ceil((goal_date - start_date).days / 7))

    if total_weeks <= 4:
        # Too short — just taper and sharpen
        phases = [("peak", 0.9)] * (total_weeks - 1) + [("taper", 0.55)]
    elif total_weeks <= 8:
        build_weeks = total_weeks - 3
        phases = (
            [("build", 1.0)] * build_weeks +
            [("peak", 0.95)] * 2 +
            [("taper", 0.55)]
        )
    elif total_weeks <= 16:
        base_weeks = max(2, total_weeks // 3)
        build_weeks = max(2, total_weeks // 3)
        peak_weeks = 2
        taper_weeks = 1
        phases = (
            [("base", 1.0)] * base_weeks +
            [("build", 1.05)] * build_weeks +
            [("peak", 1.0)] * peak_weeks +
            [("taper", 0.55)] * taper_weeks
        )
        # Trim to total_weeks
        phases = phases[:total_weeks]
    else:
        # Long plan — 3-4 week blocks with recovery weeks
        schedule = []
        week = 0
        while week < total_weeks - 3:
            block_len = min(3, total_weeks - 3 - week)
            for i in range(block_len):
                phase = "base" if week < total_weeks * 0.4 else "build"
                multiplier = 1.0 + (i * 0.05)
                schedule.append((phase, multiplier))
                week += 1
            # Recovery week every 3 weeks
            if week < total_weeks - 3:
                schedule.append(("recovery", 0.6))
                week += 1
        schedule += [("peak", 1.0), ("peak", 0.95), ("taper", 0.55)]
        phases = schedule[:total_weeks]

    result = []
    for i, (phase, multiplier) in enumerate(phases):
        week_start = start_date + timedelta(weeks=i)
        result.append({
            "week_num": i + 1,
            "week_start": week_start,
            "phase": phase,
            "tss_multiplier": multiplier,
        })
    return result


def generate_workout_for_day(
    day_of_week: int,   # 0=Mon, 6=Sun
    phase: str,
    weekly_tss: float,
    ftp: int,
    available_hours: float,
) -> dict:
    """
    Generate a single day's workout given phase, weekly TSS target, and day of week.
    Day distribution: Mon=rest, Tue=intensity, Wed=endurance, Thu=intensity,
                      Fri=rest, Sat=long, Sun=recovery
    """
    # TSS weights by day (must sum to ~1.0)
    day_weights = {
        0: 0.0,   # Mon — rest
        1: 0.18,  # Tue — intensity
        2: 0.14,  # Wed — endurance
        3: 0.18,  # Thu — intensity
        4: 0.0,   # Fri — rest
        5: 0.35,  # Sat — long
        6: 0.15,  # Sun — recovery spin
    }

    tss_target = round(weekly_tss * day_weights.get(day_of_week, 0))

    if tss_target == 0:
        return {
            "workout_type": "Rest",
            "description": "Full rest day. Sleep, eat, recover.",
            "target_tss": 0,
            "duration_min": 0,
            "target_zones": "",
            "target_power_w": 0,
        }

    duration_min = min(round(tss_target * 1.1), available_hours / 7 * 60 * 2.5)

    if phase == "base":
        if day_of_week in (1, 3):
            wtype = "Sweet spot"
            desc = f"Warm-up 15min, 2x15min at {round(ftp*0.88)}W (sweet spot), cool-down 10min"
            zones = "Z2,Z3"
            pwr = round(ftp * 0.82)
        elif day_of_week == 2:
            wtype = "Endurance"
            desc = f"Steady Z2 at {round(ftp*0.68)}-{round(ftp*0.75)}W, easy conversational pace"
            zones = "Z2"
            pwr = round(ftp * 0.70)
        else:
            wtype = "Long endurance"
            desc = f"Long Z2 ride at {round(ftp*0.68)}-{round(ftp*0.72)}W, focus on time in saddle"
            zones = "Z2"
            pwr = round(ftp * 0.70)
    elif phase == "build":
        if day_of_week == 1:
            wtype = "Threshold intervals"
            desc = f"Warm-up 15min, 3x10min at {round(ftp*0.97)}W (FTP), 5min recovery, cool-down"
            zones = "Z2,Z4"
            pwr = round(ftp * 0.88)
        elif day_of_week == 3:
            wtype = "VO2max intervals"
            desc = f"Warm-up 15min, 5x4min at {round(ftp*1.1)}W, 4min easy recovery, cool-down 15min"
            zones = "Z2,Z5"
            pwr = round(ftp * 0.85)
        elif day_of_week == 2:
            wtype = "Endurance"
            desc = f"Steady Z2 at {round(ftp*0.70)}W, aerobic base maintenance"
            zones = "Z2"
            pwr = round(ftp * 0.70)
        else:
            wtype = "Long ride with quality"
            desc = f"2+ hrs Z2 base with 2x20min sweet spot at {round(ftp*0.90)}W in the middle"
            zones = "Z2,Z3"
            pwr = round(ftp * 0.75)
    elif phase == "peak":
        if day_of_week == 1:
            wtype = "Race simulation"
            desc = f"Warm-up 15min, 2x20min at {round(ftp*1.0)}W (threshold), 5min recovery, cool-down"
            zones = "Z2,Z4,Z5"
            pwr = round(ftp * 0.88)
        elif day_of_week == 3:
            wtype = "Anaerobic capacity"
            desc = f"6x1min max effort at {round(ftp*1.3)}+W, 4min full recovery, Z2 base around efforts"
            zones = "Z2,Z6"
            pwr = round(ftp * 0.90)
        elif day_of_week == 2:
            wtype = "Endurance"
            desc = f"60-75min moderate Z2 at {round(ftp*0.70)}W"
            zones = "Z2"
            pwr = round(ftp * 0.70)
        else:
            wtype = "Long aerobic"
            desc = f"Long ride 2-3hrs, mostly Z2 with some Z3. Simulate race day conditions."
            zones = "Z2,Z3"
            pwr = round(ftp * 0.73)
    else:  # recovery or taper
        wtype = "Easy spin" if day_of_week != 5 else "Moderate endurance"
        desc = f"Easy Z1-Z2 at {round(ftp*0.60)}-{round(ftp*0.72)}W. No intensity. Active recovery."
        zones = "Z1,Z2"
        pwr = round(ftp * 0.65)

    return {
        "workout_type": wtype,
        "description": desc,
        "target_tss": tss_target,
        "duration_min": round(duration_min),
        "target_zones": zones,
        "target_power_w": pwr,
    }


# COMMAND ----------

# MAGIC %md ## Generate and Save Training Plan

# COMMAND ----------

def generate_and_save_plan(athlete_id: str, dry_run: bool = False):
    """
    Generate a full multi-week training plan and save to Delta tables.
    Set dry_run=True to preview without writing.
    """
    # Load athlete profile
    athlete = spark.sql(f"""
        SELECT ftp_w, available_hours_week
        FROM {CATALOG}.silver.athletes
        WHERE athlete_id = '{athlete_id}'
    """).collect()

    if not athlete:
        print("Athlete profile not found. Run notebook 05_athlete_setup first.")
        return

    ftp = int(athlete[0].ftp_w) if athlete[0].ftp_w else 250
    available_hours = float(athlete[0].available_hours_week) if athlete[0].available_hours_week else 8.0

    # Load current training load
    load = spark.sql(f"""
        SELECT ctl, atl, tsb
        FROM {CATALOG}.gold.daily_training_load
        WHERE athlete_id = '{athlete_id}'
        ORDER BY date DESC LIMIT 1
    """).collect()

    current_ctl = float(load[0].ctl) if load else 40.0
    base_weekly_tss = max(current_ctl * 7, available_hours * 50)

    # Load goal event
    goal = spark.sql(f"""
        SELECT event_name, event_date
        FROM {CATALOG}.coach.athlete_goals
        WHERE athlete_id = '{athlete_id}' AND priority = 1
        ORDER BY event_date LIMIT 1
    """).collect()

    if not goal:
        print("No goal event found. Using 12-week plan from today.")
        goal_name = "Peak fitness"
        goal_date = date.today() + timedelta(weeks=12)
    else:
        goal_name = goal[0].event_name
        goal_date = goal[0].event_date

    start_date = date.today()
    plan_id = str(uuid.uuid4())
    weeks = compute_phase_schedule(start_date, goal_date, current_ctl)

    print(f"\nPlan for: {athlete_id}")
    print(f"Goal:     {goal_name} on {goal_date}")
    print(f"Duration: {len(weeks)} weeks")
    print(f"Base TSS: {round(base_weekly_tss)}/week | FTP: {ftp}W | Hours: {available_hours}h/wk")
    print(f"\n{'Week':>4}  {'Start':>12}  {'Phase':>10}  {'TSS Target':>10}")
    print("-" * 50)

    plan_rows = []
    workout_rows = []

    for w in weeks:
        weekly_tss = round(base_weekly_tss * w["tss_multiplier"])
        week_start = w["week_start"]
        phase = w["phase"]
        print(f"{w['week_num']:>4}  {str(week_start):>12}  {phase:>10}  {weekly_tss:>10}")

        for day_offset in range(7):
            workout_date = week_start + timedelta(days=day_offset)
            day_of_week = workout_date.weekday()

            workout = generate_workout_for_day(day_of_week, phase, weekly_tss, ftp, available_hours)

            workout_rows.append({
                "workout_id": str(uuid.uuid4()),
                "plan_id": plan_id,
                "athlete_id": athlete_id,
                "planned_date": workout_date,
                "workout_type": workout["workout_type"],
                "description": workout["description"],
                "target_tss": float(workout["target_tss"]),
                "duration_min": float(workout["duration_min"]),
                "target_zones": workout["target_zones"],
                "target_power_w": float(workout["target_power_w"]),
                "completed": False,
                "actual_tss": None,
                "notes": None,
            })

    target_ctl = round(current_ctl * 1.15, 1)
    plan_rows.append({
        "plan_id": plan_id,
        "athlete_id": athlete_id,
        "phase": weeks[0]["phase"] if weeks else "base",
        "start_date": start_date,
        "end_date": goal_date,
        "goal_event_name": goal_name,
        "goal_event_date": goal_date,
        "target_ctl_end": target_ctl,
        "notes": f"Auto-generated plan: {len(weeks)} weeks, base TSS {round(base_weekly_tss)}",
        "created_at": datetime.now(),
    })

    if dry_run:
        print(f"\nDry run — {len(workout_rows)} workouts generated, not saved.")
        return plan_id, plan_rows, workout_rows

    # Write training plan
    plan_schema = StructType([
        StructField("plan_id",          StringType(),    False),
        StructField("athlete_id",       StringType(),    True),
        StructField("phase",            StringType(),    True),
        StructField("start_date",       DateType(),      True),
        StructField("end_date",         DateType(),      True),
        StructField("goal_event_name",  StringType(),    True),
        StructField("goal_event_date",  DateType(),      True),
        StructField("target_ctl_end",   DoubleType(),    True),
        StructField("notes",            StringType(),    True),
        StructField("created_at",       TimestampType(), True),
    ])

    workout_schema = StructType([
        StructField("workout_id",     StringType(),  False),
        StructField("plan_id",        StringType(),  True),
        StructField("athlete_id",     StringType(),  True),
        StructField("planned_date",   DateType(),    True),
        StructField("workout_type",   StringType(),  True),
        StructField("description",    StringType(),  True),
        StructField("target_tss",     DoubleType(),  True),
        StructField("duration_min",   DoubleType(),  True),
        StructField("target_zones",   StringType(),  True),
        StructField("target_power_w", DoubleType(),  True),
        StructField("completed",      BooleanType(), True),
        StructField("actual_tss",     DoubleType(),  True),
        StructField("notes",          StringType(),  True),
    ])

    spark.createDataFrame(plan_rows, schema=plan_schema) \
        .write.format("delta").mode("append") \
        .saveAsTable(f"{CATALOG}.coach.training_plans")

    spark.createDataFrame(workout_rows, schema=workout_schema) \
        .write.format("delta").mode("append") \
        .saveAsTable(f"{CATALOG}.coach.planned_workouts")

    print(f"\n✅ Plan {plan_id[:8]}... saved:")
    print(f"   • {len(plan_rows)} plan record")
    print(f"   • {len(workout_rows)} planned workouts")
    print(f"   • Query: SELECT * FROM {CATALOG}.coach.planned_workouts WHERE plan_id = '{plan_id}' ORDER BY planned_date")
    return plan_id


# COMMAND ----------

# Generate the plan (set dry_run=True to preview first)
plan_id = None
plan_id = generate_and_save_plan(ATHLETE_ID, dry_run=False)

# COMMAND ----------

# MAGIC %md ## Verify the Plan

# COMMAND ----------

# Preview the first 2 weeks of the saved plan
if plan_id:
    display(spark.sql(f"""
        SELECT planned_date, workout_type, description, target_tss, duration_min, target_zones, target_power_w
        FROM {CATALOG}.coach.planned_workouts
        WHERE plan_id = '{plan_id}'
        ORDER BY planned_date
        LIMIT 14
    """))

# COMMAND ----------

# Summary by phase
if plan_id:
    display(spark.sql(f"""
        SELECT
            pw.workout_type,
            COUNT(*) AS num_sessions,
            ROUND(AVG(pw.target_tss), 0) AS avg_tss,
            ROUND(AVG(pw.duration_min), 0) AS avg_duration_min
        FROM {CATALOG}.coach.planned_workouts pw
        WHERE pw.plan_id = '{plan_id}' AND pw.workout_type != 'Rest'
        GROUP BY pw.workout_type
        ORDER BY num_sessions DESC
    """))
