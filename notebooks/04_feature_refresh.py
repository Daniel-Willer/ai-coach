# Databricks notebook source

# MAGIC %md
# MAGIC # 04 — Feature Refresh
# MAGIC
# MAGIC Builds the `features.athlete_daily` table — the primary input for AI coaching agents.
# MAGIC Run after `03_silver_to_gold`.
# MAGIC
# MAGIC Each row = one athlete on one date with everything the coach needs to make decisions:
# MAGIC CTL, ATL, TSB, form, sleep, recovery, goal proximity, compliance.

# COMMAND ----------

CATALOG = "ai_coach"
ATHLETE_ID = dbutils.widgets.get("athlete_id") if "athlete_id" in [w.name for w in dbutils.widgets.getAll()] else "athlete_1"

print(f"Catalog: {CATALOG} | Athlete: {ATHLETE_ID}")

# COMMAND ----------

from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    col, lit, to_date, date_diff, current_date, coalesce,
    when, min as spark_min, spark_partition_id,
    sum as spark_sum, avg as spark_avg, count
)
from datetime import datetime, date, timedelta

spark = SparkSession.builder.getOrCreate()

# COMMAND ----------

# MAGIC %md ## Load Gold Tables

# COMMAND ----------

df_load = spark.table(f"{CATALOG}.gold.daily_training_load") \
    .filter(col("athlete_id") == ATHLETE_ID)

df_health = spark.table(f"{CATALOG}.silver.daily_health") \
    .filter(col("athlete_id") == ATHLETE_ID)

df_athlete = spark.table(f"{CATALOG}.silver.athletes") \
    .filter(col("athlete_id") == ATHLETE_ID)

df_weekly = spark.table(f"{CATALOG}.gold.weekly_summary") \
    .filter(col("athlete_id") == ATHLETE_ID)

# COMMAND ----------

# MAGIC %md ## Find Next Goal Event

# COMMAND ----------

try:
    df_goals = spark.table(f"{CATALOG}.coach.athlete_goals") \
        .filter(col("athlete_id") == ATHLETE_ID) \
        .filter(col("event_date") >= current_date()) \
        .filter(col("priority") == "A") \
        .orderBy("event_date")

    next_goal = df_goals.select("event_date").limit(1).collect()
    next_goal_date = next_goal[0].event_date if next_goal else None
    print(f"Next A-priority goal event: {next_goal_date}")
except Exception:
    next_goal_date = None
    print("No goal events found — set them in notebook 05_athlete_setup")

# COMMAND ----------

# MAGIC %md ## Compute 7-day Compliance (planned vs executed)

# COMMAND ----------

try:
    # Compliance = percentage of planned workouts completed in last 7 days
    df_planned = spark.table(f"{CATALOG}.coach.planned_workouts") \
        .filter(col("athlete_id") == ATHLETE_ID)

    compliance_pdf = df_planned.toPandas()
    if len(compliance_pdf) > 0:
        import pandas as pd
        compliance_pdf["scheduled_date"] = pd.to_datetime(compliance_pdf["scheduled_date"])
        cutoff = pd.Timestamp.now() - pd.Timedelta(days=7)
        recent = compliance_pdf[compliance_pdf["scheduled_date"] >= cutoff]
        compliance_7d = (recent["completed"].sum() / len(recent) * 100) if len(recent) > 0 else None
    else:
        compliance_7d = None

    print(f"7-day compliance: {compliance_7d}%")
except Exception:
    compliance_7d = None

# COMMAND ----------

# MAGIC %md ## Get Athlete FTP

# COMMAND ----------

try:
    ftp_w = df_athlete.select("ftp_w").collect()[0].ftp_w
except Exception:
    ftp_w = None

# COMMAND ----------

# MAGIC %md ## Build Feature Table

# COMMAND ----------

# Join training load with daily health
df_features = df_load.join(
    df_health.select(
        "date",
        col("sleep_duration_sec"),
        col("body_battery"),
        col("resting_hr"),
        col("stress_score"),
    ),
    on="date",
    how="left"
)

# Add days to next goal event
if next_goal_date:
    df_features = df_features.withColumn(
        "days_to_goal_event",
        date_diff(lit(next_goal_date), col("date"))
    )
else:
    df_features = df_features.withColumn("days_to_goal_event", lit(None).cast("int"))

# Add static athlete fields
df_features = df_features \
    .withColumn("ftp_w", lit(ftp_w).cast("int")) \
    .withColumn("injury_flag", lit(False)) \
    .withColumn("compliance_7d", lit(compliance_7d).cast("double")) \
    .withColumn("weekly_hours", lit(None).cast("double")) \
    .withColumn("weekly_tss", lit(None).cast("double"))

# Join weekly metrics for the relevant week
df_weekly_lookup = df_weekly.withColumnRenamed("week_start", "week_start_join") \
    .select("week_start_join", "total_hours", "total_tss")

# Add week_start to features for joining
from pyspark.sql.functions import date_trunc
df_features = df_features.withColumn("week_start", date_trunc("week", col("date")).cast("date"))

df_features = df_features.join(
    df_weekly_lookup.withColumnRenamed("week_start_join", "week_start"),
    on="week_start",
    how="left"
).withColumn("weekly_hours", coalesce(col("total_hours"), col("weekly_hours"))) \
 .withColumn("weekly_tss", coalesce(col("total_tss"), col("weekly_tss")))

# Final column selection matching features.athlete_daily schema
df_final = df_features.select(
    col("athlete_id"),
    col("date"),
    col("ctl"),
    col("atl"),
    col("tsb"),
    col("form"),
    col("weekly_hours"),
    col("weekly_tss"),
    col("sleep_duration_sec"),
    col("body_battery"),
    col("resting_hr"),
    col("stress_score"),
    col("days_to_goal_event"),
    col("ftp_w"),
    col("injury_flag"),
    col("compliance_7d"),
)

df_final.write.format("delta") \
    .mode("overwrite") \
    .option("mergeSchema", "true") \
    .saveAsTable(f"{CATALOG}.features.athlete_daily")

feature_count = spark.sql(f"SELECT COUNT(*) AS n FROM {CATALOG}.features.athlete_daily").collect()[0].n
print(f"✅ {feature_count:,} rows written to features.athlete_daily")

# COMMAND ----------

# MAGIC %md ## Current Athlete Snapshot

# COMMAND ----------

latest = spark.sql(f"""
SELECT *
FROM {CATALOG}.features.athlete_daily
WHERE athlete_id = '{ATHLETE_ID}'
ORDER BY date DESC
LIMIT 1
""").collect()

if latest:
    r = latest[0]
    print(f"""
{'='*50}
Athlete Snapshot — {r.date}
{'='*50}
CTL (Fitness)     : {r.ctl:.1f}
ATL (Fatigue)     : {r.atl:.1f}
TSB (Form)        : {r.tsb:.1f}
Form State        : {r.form}

Sleep last night  : {int(r.sleep_duration_sec/3600) if r.sleep_duration_sec else 'N/A'} hrs
Body Battery      : {r.body_battery}
Resting HR        : {r.resting_hr} bpm
Stress Score      : {r.stress_score}

FTP               : {r.ftp_w}W
Days to Goal Race : {r.days_to_goal_event}
7d Compliance     : {r.compliance_7d}%
{'='*50}
""")
