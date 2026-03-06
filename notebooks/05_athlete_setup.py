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

# Add widgets for easy configuration in Databricks UI
dbutils.widgets.text("athlete_id",         "athlete_1",        "Athlete ID")
dbutils.widgets.text("name",               "Mr. Willer",        "Full Name")
dbutils.widgets.text("strava_id",          "",                 "Strava ID (optional)")
dbutils.widgets.text("garmin_id",          "",                 "Garmin ID (optional)")
dbutils.widgets.text("ftp_watts",          "235",              "FTP (watts)")
dbutils.widgets.text("weight_kg",          "83",               "Weight (kg)")
dbutils.widgets.text("birth_year",         "1991",             "Birth Year")
dbutils.widgets.text("gender",             "M",                "Gender (M/F)")
dbutils.widgets.text("fitness_level",      "Intermediate",     "Fitness Level (Beginner/Intermediate/Advanced/Elite)")
dbutils.widgets.text("available_hours",    "8",                "Available Training Hours/Week")
dbutils.widgets.text("max_hr",             "185",              "Max Heart Rate (bpm)")
dbutils.widgets.text("resting_hr",         "55",               "Resting Heart Rate (bpm)")
dbutils.widgets.text("lthr",               "165",              "Lactate Threshold HR (bpm)")
dbutils.widgets.text("training_goal",      "Build cycling fitness for a gran fondo", "Training Goal")
dbutils.widgets.text("injury_history",     "None",             "Injury History")

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

# ── EDIT THIS LIST WITH YOUR ACTUAL EVENTS ──────────────────────────────────
GOAL_EVENTS = [
    {
        "event_name": "Example Gran Fondo",
        "event_date": date(2025, 9, 15),
        "priority":   "A",
        "event_type": "Gran Fondo",
        "target":     "Finish strong, sub-5 hours",
        "notes":      "Hilly course, ~120 miles",
    },
    # Add more events:
    # {
    #     "event_name": "Local Criterium",
    #     "event_date": date(2025, 7, 4),
    #     "priority":   "B",
    #     "event_type": "Race",
    #     "target":     "Top 10 finish",
    #     "notes":      "",
    # },
]
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
    df_goals.write.format("delta").mode("append") \
        .option("mergeSchema", "true") \
        .saveAsTable(f"{CATALOG}.coach.athlete_goals")

    print(f"✅ {len(GOAL_EVENTS)} goal events saved")
    for g in GOAL_EVENTS:
        print(f"   [{g['priority']}] {g['event_name']} — {g['event_date']}")
else:
    print("No goal events defined. Edit GOAL_EVENTS list above and re-run.")

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
