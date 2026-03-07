# Databricks notebook source
# MAGIC %md
# MAGIC # 05 — Athlete Setup & Onboarding
# MAGIC
# MAGIC Run this **once** to create your athlete profile and set your training goals.
# MAGIC All other notebooks use this data to personalize coaching.
# MAGIC
# MAGIC Fill in the widgets below, then run all cells.

# COMMAND ----------

# MAGIC %md ## Athlete Profile Widgets
# MAGIC
# MAGIC Use the widgets above (or set the variables directly below) to configure your profile.

# COMMAND ----------

# Athlete Profile Configuration — now loaded from config.yaml
# Place config.yaml in /Users/danielwiller38@gmail.com/ai-coach/config/config.yaml
import yaml
import os

CONFIG_PATH = "/Workspace/Users/danielwiller38@gmail.com/ai-coach/config/config.yaml"
assert os.path.exists(CONFIG_PATH), f"Config file not found: {CONFIG_PATH}"

with open(CONFIG_PATH, "r") as f:
    config = yaml.safe_load(f)
if config is None:
    raise ValueError(f"Config file is empty or invalid YAML: {CONFIG_PATH}")

ATHLETE_ID      = config["athlete_id"]
NAME            = config["name"]
STRAVA_ID       = config.get("strava_id", None)
GARMIN_ID       = config.get("garmin_id", None)
FTP             = int(config["ftp_watts"])
WEIGHT_KG       = float(config["weight_kg"])
BIRTH_YEAR      = int(config["birth_year"])
GENDER          = config["gender"]
FITNESS_LEVEL   = config["fitness_level"]
AVAIL_HOURS     = int(config["available_hours"])
MAX_HR          = int(config["max_hr"])
RESTING_HR      = int(config["resting_hr"])
LTHR            = int(config["lthr"])
TRAINING_GOAL   = config["training_goal"]
INJURY_HISTORY  = config.get("injury_history", None)

print(f"Loaded athlete profile for: {NAME} ({ATHLETE_ID})")
print(f"FTP: {FTP}W | Weight: {WEIGHT_KG}kg | Available: {AVAIL_HOURS}h/week")

# Optionally remove all dbutils.widgets code (fully YAML driven)
# (if you wish to keep widgets for UI updates, retain them as-is for separate profile entry)

# COMMAND ----------

CATALOG = "ai_coach"

ATHLETE_ID      = dbutils.widgets.get("athlete_id")
NAME            = dbutils.widgets.get("name")
STRAVA_ID       = dbutils.widgets.get("strava_id") or None
GARMIN_ID       = dbutils.widgets.get("garmin_id") or None
FTP             = int(dbutils.widgets.get("ftp_watts"))
WEIGHT_KG       = float(dbutils.widgets.get("weight_kg"))
BIRTH_YEAR      = int(dbutils.widgets.get("birth_year"))
GENDER          = dbutils.widgets.get("gender")
FITNESS_LEVEL   = dbutils.widgets.get("fitness_level")
AVAIL_HOURS     = int(dbutils.widgets.get("available_hours"))
MAX_HR          = int(dbutils.widgets.get("max_hr"))
RESTING_HR      = int(dbutils.widgets.get("resting_hr"))
LTHR            = int(dbutils.widgets.get("lthr"))
TRAINING_GOAL   = dbutils.widgets.get("training_goal")
INJURY_HISTORY  = dbutils.widgets.get("injury_history")

print(f"Setting up athlete profile for: {NAME} ({ATHLETE_ID})")
print(f"FTP: {FTP}W | Weight: {WEIGHT_KG}kg | Available: {AVAIL_HOURS}h/week")

# COMMAND ----------

from pyspark.sql import SparkSession
from pyspark.sql.types import *
from datetime import datetime, date
import uuid

spark = SparkSession.builder.getOrCreate()

# COMMAND ----------

# MAGIC %md ## Create / Update Athlete Record

# COMMAND ----------

athlete_schema = StructType([
    StructField("athlete_id",           StringType(),  False),
    StructField("name",                 StringType(),  True),
    StructField("strava_id",            StringType(),  True),
    StructField("garmin_id",            StringType(),  True),
    StructField("ftp_w",               IntegerType(), True),
    StructField("weight_kg",            DoubleType(),  True),
    StructField("birth_date",           DateType(),    True),
    StructField("gender",               StringType(),  True),
    StructField("fitness_level",        StringType(),  True),
    StructField("training_goal",        StringType(),  True),
    StructField("available_hours_week", IntegerType(), True),
    StructField("lthr",                 IntegerType(), True),
    StructField("max_hr",               IntegerType(), True),
    StructField("resting_hr",           IntegerType(), True),
    StructField("notes",                StringType(),  True),
    StructField("created_at",           TimestampType(), True),
    StructField("updated_at",           TimestampType(), True),
])

athlete_row = [{
    "athlete_id":           ATHLETE_ID,
    "name":                 NAME,
    "strava_id":            STRAVA_ID,
    "garmin_id":            GARMIN_ID,
    "ftp_w":               FTP,
    "weight_kg":            WEIGHT_KG,
    "birth_date":           date(BIRTH_YEAR, 1, 1),
    "gender":               GENDER,
    "fitness_level":        FITNESS_LEVEL,
    "training_goal":        TRAINING_GOAL,
    "available_hours_week": AVAIL_HOURS,
    "lthr":                 LTHR,
    "max_hr":               MAX_HR,
    "resting_hr":           RESTING_HR,
    "notes":                INJURY_HISTORY,
    "created_at":           datetime.now(),
    "updated_at":           datetime.now(),
}]

df_athlete = spark.createDataFrame(athlete_row, schema=athlete_schema)
df_athlete.createOrReplaceTempView("athlete_upsert")

spark.sql(f"""
MERGE INTO {CATALOG}.silver.athletes AS target
USING athlete_upsert AS source
ON target.athlete_id = source.athlete_id
WHEN MATCHED THEN UPDATE SET
  ftp_w = source.ftp_w,
  weight_kg = source.weight_kg,
  fitness_level = source.fitness_level,
  training_goal = source.training_goal,
  available_hours_week = source.available_hours_week,
  lthr = source.lthr,
  max_hr = source.max_hr,
  resting_hr = source.resting_hr,
  notes = source.notes,
  updated_at = source.updated_at
WHEN NOT MATCHED THEN INSERT *
""")

print(f"✅ Athlete record saved: {NAME} ({ATHLETE_ID})")

# COMMAND ----------

# MAGIC %md ## Add Goal Events
# MAGIC
# MAGIC Add your target races/events below. Priority A = main goal, B = secondary, C = just for fun.
# MAGIC Add as many as you want — the coach will build your plan around the A events.

# COMMAND ----------

# DBTITLE 1,Load Goal Events from athlete config.yaml
# ── LOAD GOALS FROM YAML ──────────────────────────────────
import yaml
import os
from datetime import datetime, date
import uuid

goals_path = "/Workspace/Users/danielwiller38@gmail.com/ai-coach/config/event-goal-config.yaml"
if os.path.exists(goals_path):
    with open(goals_path, "r") as f:
        yaml_goals = yaml.safe_load(f)
    GOAL_EVENTS = []
    for g in yaml_goals:
        event_date = datetime.strptime(g["event_date"], "%Y-%m-%d").date() if isinstance(g["event_date"], str) else g["event_date"]
        GOAL_EVENTS.append({
            "event_name": g["event_name"],
            "event_date": event_date,
            "priority":   g["priority"],
            "event_type": g.get("event_type", "Other"),
            "target":     g.get("target", ""),
            "notes":      g.get("notes", ""),
        })
else:
    GOAL_EVENTS = []
    print(f"⚠️  Goals YAML file not found: {goals_path} — edit goals in code or create the file to use YAML.")
# ─────────────────────────────────────────────────────────────────────────────

if GOAL_EVENTS:
    goals_schema = StructType([
        StructField("goal_id",    StringType(), False),
        StructField("athlete_id", StringType(), True),
        StructField("event_name", StringType(), True),
        StructField("event_date", DateType(),   True),
        StructField("priority",   StringType(), True),
        StructField("event_type", StringType(), True),
        StructField("target",     StringType(), True),
        StructField("notes",      StringType(), True),
        StructField("created_at", TimestampType(), True),
    ])

    # Create a temp view for upsert
    goals_rows = [{
        "goal_id":    str(uuid.uuid4()),
        "athlete_id": ATHLETE_ID,
        "event_name": g["event_name"],
        "event_date": g["event_date"],
        "priority":   g["priority"],
        "event_type": g["event_type"],
        "target":     g["target"],
        "notes":      g["notes"],
        "created_at": datetime.now(),
    } for g in GOAL_EVENTS]
    df_goals = spark.createDataFrame(goals_rows, schema=goals_schema)
    df_goals.createOrReplaceTempView("goals_upsert")

    # Use Delta Lake MERGE to deduplicate on athlete_id, event_name, event_date
    spark.sql(f"""
    MERGE INTO {CATALOG}.coach.athlete_goals AS target
    USING goals_upsert AS source
    ON target.athlete_id = source.athlete_id
      AND target.event_name = source.event_name
      AND target.event_date = source.event_date
    WHEN MATCHED THEN UPDATE SET
        priority    = source.priority,
        event_type  = source.event_type,
        target      = source.target,
        notes       = source.notes,
        created_at  = source.created_at
    WHEN NOT MATCHED THEN INSERT *
    """)

    print(f"✅ {len(GOAL_EVENTS)} goal events saved (deduplicated)")
    for g in GOAL_EVENTS:
        print(f"   [{g['priority']}] {g['event_name']} — {g['event_date']}")
else:
    print("No goal events defined. Edit event-goal-config.yaml or GOAL_EVENTS list and re-run.")

# COMMAND ----------

# MAGIC %md ## Verify Profile

# COMMAND ----------

spark.sql(f"""
SELECT athlete_id, name, ftp_w, weight_kg, fitness_level, available_hours_week, lthr, max_hr
FROM {CATALOG}.silver.athletes
WHERE athlete_id = '{ATHLETE_ID}'
""").show(truncate=False)

spark.sql(f"""
SELECT event_name, event_date, priority, event_type, target
FROM {CATALOG}.coach.athlete_goals
WHERE athlete_id = '{ATHLETE_ID}'
ORDER BY priority, event_date
""").show(truncate=False)

# COMMAND ----------

# MAGIC %md ## Next Steps
# MAGIC
# MAGIC Now that your profile is set up:
# MAGIC
# MAGIC 1. **Run notebook 00** to ensure the catalog is set up
# MAGIC 2. **Run the existing ETL notebooks** (Garmin, Strava, RideWithGPS) to ingest your historical data
# MAGIC 3. **Run notebook 01** to write Strava data to bronze
# MAGIC 4. **Run notebook 02** to normalize everything into silver
# MAGIC 5. **Run notebook 03** to compute CTL/ATL/TSB and power curves
# MAGIC 6. **Run notebook 04** to build the feature table
# MAGIC 7. **Run notebook 06** (coming next) — the coaching agent will analyze your data and introduce itself
