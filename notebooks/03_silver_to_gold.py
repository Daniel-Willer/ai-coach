# Databricks notebook source
# MAGIC %md
# MAGIC # 03 — Silver to Gold
# MAGIC
# MAGIC Computes all coaching metrics from the silver layer.
# MAGIC
# MAGIC **Metrics computed:**
# MAGIC - **TSS per activity** — Training Stress Score (power-based or HR-based fallback)
# MAGIC - **CTL / ATL / TSB** — Chronic/Acute Training Load and Training Stress Balance
# MAGIC - **Power Curve** — peak power at key durations (5s, 30s, 1m, 5m, 20m, 60m)
# MAGIC - **Zone Distribution** — time in each power zone per ride
# MAGIC - **Weekly Summary** — volume, TSS, sleep, compliance
# MAGIC
# MAGIC **Reads from:** `ai_coach.silver.*`
# MAGIC **Writes to:** `ai_coach.gold.*`

# COMMAND ----------

# MAGIC %md ## Configuration

# COMMAND ----------

CATALOG = "ai_coach"

ATHLETE_ID = dbutils.widgets.get("athlete_id") if "athlete_id" in [w.name for w in dbutils.widgets.getAll()] else "athlete_1"

# FTP in watts — used for TSS and zone calculations
# Pulled from silver.athletes if available, else use this default
DEFAULT_FTP = 250

# Lactate threshold heart rate for HR-based TSS fallback
# Approximate: 90% of max HR or a known value
DEFAULT_LTHR = 160

print(f"Catalog:    {CATALOG}")
print(f"Athlete ID: {ATHLETE_ID}")

# COMMAND ----------

import pandas as pd
import numpy as np
from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    col, lit, to_date, date_trunc, date_add, date_sub,
    sum as spark_sum, avg as spark_avg, max as spark_max, min as spark_min,
    count, when, coalesce, expr, window, lag, lead,
    unix_timestamp, from_unixtime, round as spark_round
)
from pyspark.sql.types import *
from pyspark.sql.window import Window
from datetime import datetime, date, timedelta

spark = SparkSession.builder.getOrCreate()

# COMMAND ----------

# MAGIC %md ## Load Athlete Config (FTP, LTHR)

# COMMAND ----------

try:
    athlete_row = spark.table(f"{CATALOG}.silver.athletes") \
        .filter(col("athlete_id") == ATHLETE_ID) \
        .select("ftp_w", "lthr", "max_hr", "resting_hr") \
        .collect()

    if athlete_row:
        FTP = athlete_row[0].ftp_w or DEFAULT_FTP
        LTHR = athlete_row[0].lthr or DEFAULT_LTHR
        MAX_HR = athlete_row[0].max_hr
        RESTING_HR = athlete_row[0].resting_hr
    else:
        FTP = DEFAULT_FTP
        LTHR = DEFAULT_LTHR
        MAX_HR = None
        RESTING_HR = None

except Exception:
    FTP = DEFAULT_FTP
    LTHR = DEFAULT_LTHR
    MAX_HR = None
    RESTING_HR = None

print(f"FTP:        {FTP}W")
print(f"LTHR:       {LTHR} bpm")
print(f"Max HR:     {MAX_HR} bpm")
print(f"Resting HR: {RESTING_HR} bpm")

# COMMAND ----------

# MAGIC %md ## 1 — Compute TSS per Activity & Update silver.activities

# COMMAND ----------

# MAGIC %md
# MAGIC **TSS calculation logic:**
# MAGIC
# MAGIC If `normalized_power` is available (from Strava weighted_avg_watts):
# MAGIC   `TSS = (duration_sec * NP * (NP/FTP)) / (FTP * 3600) * 100`
# MAGIC   `     = duration_hours * IF^2 * 100`   where `IF = NP / FTP`
# MAGIC
# MAGIC If only `avg_power_w` available (no NP):
# MAGIC   Use avg power as a proxy: `TSS = duration_hours * (avg_power/FTP)^2 * 100`
# MAGIC
# MAGIC If no power data (heart rate fallback — hrTSS):
# MAGIC   `hrTSS = duration_hours * (avg_hr / LTHR)^2 * 100`
# MAGIC   This is an approximation — accuracy depends on how close LTHR is to true threshold.

# COMMAND ----------

df_acts = spark.table(f"{CATALOG}.silver.activities") \
    .filter(col("athlete_id") == ATHLETE_ID)

df_tss = df_acts.withColumn(
    "tss",
    when(
        col("normalized_power").isNotNull() & (col("normalized_power") > 0),
        # Power-based TSS using NP
        (col("duration_sec") / 3600.0) *
        (col("normalized_power") / FTP) *
        (col("normalized_power") / FTP) * 100.0
    ).when(
        col("avg_power_w").isNotNull() & (col("avg_power_w") > 0),
        # Avg power fallback
        (col("duration_sec") / 3600.0) *
        (col("avg_power_w") / FTP) *
        (col("avg_power_w") / FTP) * 100.0
    ).when(
        col("avg_hr").isNotNull() & (col("avg_hr") > 0),
        # hrTSS fallback
        (col("duration_sec") / 3600.0) *
        (col("avg_hr").cast("double") / LTHR) *
        (col("avg_hr").cast("double") / LTHR) * 100.0
    ).otherwise(
        # Last resort: duration-based estimate (50 TSS/hr as neutral)
        (col("duration_sec") / 3600.0) * 50.0
    )
).withColumn(
    "intensity_factor",
    when(
        col("normalized_power").isNotNull() & (col("normalized_power") > 0),
        col("normalized_power") / FTP
    ).when(
        col("avg_power_w").isNotNull() & (col("avg_power_w") > 0),
        col("avg_power_w") / FTP
    ).otherwise(lit(None))
)

# Write TSS back to silver.activities
df_tss.select("activity_id", "tss", "intensity_factor") \
    .createOrReplaceTempView("tss_updates")

spark.sql(f"""
MERGE INTO {CATALOG}.silver.activities AS target
USING tss_updates AS source
ON target.activity_id = source.activity_id
WHEN MATCHED THEN UPDATE SET
  target.tss = source.tss,
  target.intensity_factor = source.intensity_factor
""")

# Show TSS distribution for QA
df_tss.select(
    spark_avg("tss").alias("avg_tss"),
    spark_max("tss").alias("max_tss"),
    count("*").alias("total_rides")
).show()

print(f"✅ TSS computed for {ATHLETE_ID}")

# COMMAND ----------

# MAGIC %md ## 2 — gold.daily_training_load (CTL / ATL / TSB)

# COMMAND ----------

# MAGIC %md
# MAGIC CTL/ATL use exponentially weighted moving averages (EWMA).
# MAGIC This is an inherently sequential calculation — we use pandas for correctness.
# MAGIC
# MAGIC `CTL(d) = CTL(d-1) + (TSS(d) - CTL(d-1)) / 42`
# MAGIC `ATL(d) = ATL(d-1) + (TSS(d) - ATL(d-1)) / 7`
# MAGIC `TSB(d) = CTL(d) - ATL(d)`

# COMMAND ----------

# DBTITLE 1,Fix ValueError: NaT date range
# Aggregate TSS by date (sum if multiple activities per day)
df_daily_tss = spark.table(f"{CATALOG}.silver.activities") \
    .filter(col("athlete_id") == ATHLETE_ID) \
    .filter(col("tss").isNotNull()) \
    .groupBy(to_date(col("start_time")).alias("date")) \
    .agg(spark_sum("tss").alias("tss")) \
    .orderBy("date")

daily_pdf = df_daily_tss.toPandas()
daily_pdf["date"] = pd.to_datetime(daily_pdf["date"])
daily_pdf = daily_pdf.sort_values("date").reset_index(drop=True)

if len(daily_pdf) == 0 or daily_pdf["date"].isnull().all():
    print("⚠️  No TSS data found — check silver.activities has been populated and has valid dates")
else:
    # Fill in all days in range (days with no ride have TSS = 0)
    if pd.isnull(daily_pdf["date"].min()) or pd.isnull(daily_pdf["date"].max()):
        print("⚠️  No valid dates found in daily TSS — cannot compute training load.")
    else:
        full_date_range = pd.date_range(daily_pdf["date"].min(), daily_pdf["date"].max(), freq="D")
        daily_pdf = daily_pdf.set_index("date").reindex(full_date_range, fill_value=0.0).reset_index()
        daily_pdf.columns = ["date", "tss"]

        # Compute CTL/ATL iteratively
        ctl_values = []
        atl_values = []
        ctl = 0.0
        atl = 0.0

        for _, row in daily_pdf.iterrows():
            ctl = ctl + (row["tss"] - ctl) / 42.0
            atl = atl + (row["tss"] - atl) / 7.0
            ctl_values.append(round(ctl, 2))
            atl_values.append(round(atl, 2))

        daily_pdf["ctl"] = ctl_values
        daily_pdf["atl"] = atl_values
        daily_pdf["tsb"] = (daily_pdf["ctl"] - daily_pdf["atl"]).round(2)

        # Form classification
        def classify_form(tsb):
            if tsb > 25:    return "Very Fresh"
            elif tsb > 5:   return "Fresh"
            elif tsb > -10: return "Neutral"
            elif tsb > -30: return "Tired"
            else:           return "Overreached"

        daily_pdf["form"] = daily_pdf["tsb"].apply(classify_form)
        daily_pdf["athlete_id"] = ATHLETE_ID

        # Write to gold
        training_load_schema = StructType([
            StructField("date",       TimestampType(), True),
            StructField("tss",        DoubleType(),    True),
            StructField("ctl",        DoubleType(),    True),
            StructField("atl",        DoubleType(),    True),
            StructField("tsb",        DoubleType(),    True),
            StructField("form",       StringType(),    True),
            StructField("athlete_id", StringType(),    True),
        ])

        df_training_load = spark.createDataFrame(daily_pdf, schema=training_load_schema) \
            .withColumn("date", to_date("date"))

        df_training_load.write.format("delta") \
            .mode("overwrite") \
            .option("mergeSchema", "true") \
            .saveAsTable(f"{CATALOG}.gold.daily_training_load")

        # Show current form
        latest = daily_pdf.iloc[-1]
        print(f"\n✅ CTL/ATL/TSB computed for {len(daily_pdf)} days")
        print(f"\n📊 Current Training Load:")
        print(f"   CTL (Fitness)  : {latest.ctl:.1f}")
        print(f"   ATL (Fatigue)  : {latest.atl:.1f}")
        print(f"   TSB (Form)     : {latest.tsb:.1f}")
        print(f"   Form State     : {latest.form}")

# COMMAND ----------

# MAGIC %md ## 3 — gold.fitness_metrics (Power Curve)

# COMMAND ----------

try:
    df_streams = spark.table(f"{CATALOG}.silver.activity_streams") \
        .filter(col("activity_id").startswith("strava_")) \
        .filter(col("power_w").isNotNull())

    # Compute rolling average power for each duration window
    # We use pandas per-activity for window calculations
    durations = {
        "peak_5s_w":  5,
        "peak_30s_w": 30,
        "peak_1m_w":  60,
        "peak_5m_w":  300,
        "peak_20m_w": 1200,
        "peak_60m_w": 3600,
    }

    # Get all activity IDs that have power data
    act_ids_with_power = [r.activity_id for r in df_streams.select("activity_id").distinct().collect()]
    print(f"Activities with power streams: {len(act_ids_with_power)}")

    all_peaks = []

    for act_id in act_ids_with_power:
        try:
            act_pdf = df_streams.filter(col("activity_id") == act_id) \
                .select("time_offset", "power_w") \
                .orderBy("time_offset") \
                .toPandas()

            if len(act_pdf) < 5:
                continue

            act_pdf = act_pdf.sort_values("time_offset").reset_index(drop=True)
            power_series = act_pdf["power_w"].fillna(0).values

            peak_row = {"activity_id": act_id}
            for col_name, window_sec in durations.items():
                if len(power_series) >= window_sec:
                    rolling_avg = pd.Series(power_series).rolling(window=window_sec, min_periods=window_sec).mean()
                    peak_row[col_name] = int(rolling_avg.max()) if not np.isnan(rolling_avg.max()) else None
                else:
                    peak_row[col_name] = None

            all_peaks.append(peak_row)
        except Exception as e:
            continue

    if all_peaks:
        peaks_pdf = pd.DataFrame(all_peaks)

        # Overall power curve = max across all activities
        power_curve = {
            "athlete_id": ATHLETE_ID,
            "date": date.today(),
            "ftp_estimated_w": FTP,
            "aerobic_efficiency": None,
            "hr_drift_pct": None,
        }
        for col_name in durations.keys():
            power_curve[col_name] = int(peaks_pdf[col_name].max()) if peaks_pdf[col_name].notna().any() else None

        power_curve_schema = StructType([
            StructField("athlete_id",         StringType(),  True),
            StructField("date",               DateType(),    True),
            StructField("ftp_estimated_w",    IntegerType(), True),
            StructField("aerobic_efficiency", DoubleType(),  True),
            StructField("hr_drift_pct",       DoubleType(),  True),
            StructField("peak_5s_w",          IntegerType(), True),
            StructField("peak_30s_w",         IntegerType(), True),
            StructField("peak_1m_w",          IntegerType(), True),
            StructField("peak_5m_w",          IntegerType(), True),
            StructField("peak_20m_w",         IntegerType(), True),
            StructField("peak_60m_w",         IntegerType(), True),
        ])

        df_power_curve = spark.createDataFrame([power_curve], schema=power_curve_schema)
        df_power_curve.write.format("delta") \
            .mode("overwrite") \
            .option("mergeSchema", "true") \
            .saveAsTable(f"{CATALOG}.gold.fitness_metrics")

        print(f"\n✅ Power Curve:")
        for k, v in power_curve.items():
            if k.startswith("peak"):
                label = k.replace("peak_", "").replace("_w", "")
                print(f"   {label:>6}: {v}W")

except Exception as e:
    print(f"⚠️  Could not compute power curve: {e}")
    print("   This requires Strava stream data with power data — run notebook 01 first.")

# COMMAND ----------

# MAGIC %md ## 4 — gold.zone_distribution (per activity)

# COMMAND ----------

# MAGIC %md
# MAGIC Power zones based on FTP:
# MAGIC - Z1: < 55%  (Active Recovery)
# MAGIC - Z2: 56-75% (Endurance)
# MAGIC - Z3: 76-90% (Tempo)
# MAGIC - Z4: 91-105% (Threshold)
# MAGIC - Z5: 106-120% (VO2Max)
# MAGIC - Z6: 121-150% (Anaerobic)
# MAGIC - Z7: > 150%  (Neuromuscular)

# COMMAND ----------

try:
    df_streams_zones = spark.table(f"{CATALOG}.silver.activity_streams") \
        .filter(col("activity_id").startswith("strava_")) \
        .filter(col("power_w").isNotNull() & (col("power_w") > 0))

    # Classify each second into a zone
    z1_upper = FTP * 0.55
    z2_upper = FTP * 0.75
    z3_upper = FTP * 0.90
    z4_upper = FTP * 1.05
    z5_upper = FTP * 1.20
    z6_upper = FTP * 1.50

    df_zones = df_streams_zones.withColumn(
        "zone",
        when(col("power_w") < z1_upper, 1)
        .when(col("power_w") < z2_upper, 2)
        .when(col("power_w") < z3_upper, 3)
        .when(col("power_w") < z4_upper, 4)
        .when(col("power_w") < z5_upper, 5)
        .when(col("power_w") < z6_upper, 6)
        .otherwise(7)
    )

    # Count seconds per zone per activity
    df_zone_counts = df_zones.groupBy("activity_id").agg(
        count("*").alias("total_sec"),
        spark_sum(when(col("zone") == 1, 1).otherwise(0)).alias("z1_sec"),
        spark_sum(when(col("zone") == 2, 1).otherwise(0)).alias("z2_sec"),
        spark_sum(when(col("zone") == 3, 1).otherwise(0)).alias("z3_sec"),
        spark_sum(when(col("zone") == 4, 1).otherwise(0)).alias("z4_sec"),
        spark_sum(when(col("zone") == 5, 1).otherwise(0)).alias("z5_sec"),
        spark_sum(when(col("zone") == 6, 1).otherwise(0)).alias("z6_sec"),
        spark_sum(when(col("zone") == 7, 1).otherwise(0)).alias("z7_sec"),
    )

    # Convert to percentages, join with activity date
    df_acts_dates = spark.table(f"{CATALOG}.silver.activities") \
        .select("activity_id", to_date("start_time").alias("date"))

    df_zone_dist = df_zone_counts.join(df_acts_dates, on="activity_id", how="left") \
        .select(
            lit(ATHLETE_ID).alias("athlete_id"),
            col("activity_id"),
            col("date"),
            spark_round(col("z1_sec") / col("total_sec") * 100, 1).alias("zone_1_pct"),
            spark_round(col("z2_sec") / col("total_sec") * 100, 1).alias("zone_2_pct"),
            spark_round(col("z3_sec") / col("total_sec") * 100, 1).alias("zone_3_pct"),
            spark_round(col("z4_sec") / col("total_sec") * 100, 1).alias("zone_4_pct"),
            spark_round(col("z5_sec") / col("total_sec") * 100, 1).alias("zone_5_pct"),
            spark_round(col("z6_sec") / col("total_sec") * 100, 1).alias("zone_6_pct"),
            spark_round(col("z7_sec") / col("total_sec") * 100, 1).alias("zone_7_pct"),
            lit("power").alias("zone_basis"),
        )

    df_zone_dist.write.format("delta") \
        .mode("overwrite") \
        .option("mergeSchema", "true") \
        .saveAsTable(f"{CATALOG}.gold.zone_distribution")

    zone_count = spark.sql(f"SELECT COUNT(*) AS n FROM {CATALOG}.gold.zone_distribution").collect()[0].n
    print(f"✅ Zone distributions computed for {zone_count} activities")

    # Show a sample
    spark.sql(f"""
    SELECT activity_id, date, zone_1_pct, zone_2_pct, zone_3_pct, zone_4_pct, zone_5_pct
    FROM {CATALOG}.gold.zone_distribution
    ORDER BY date DESC
    LIMIT 5
    """).show()

except Exception as e:
    print(f"⚠️  Could not compute zone distributions: {e}")

# COMMAND ----------

# MAGIC %md ## 5 — gold.weekly_summary

# COMMAND ----------

# DBTITLE 1,Fix NOT NULL constraint for week_start in gold.weekly_summary
# Cast ride_count from bigint to int so it matches the destination table
from pyspark.sql.functions import col

df_weekly_fixed = df_weekly.withColumn('ride_count', col('ride_count').cast('int')) \
    .filter(col('week_start').isNotNull())

df_weekly_fixed.write.format("delta") \
    .mode("overwrite") \
    .saveAsTable(f"{CATALOG}.gold.weekly_summary")

weekly_count = spark.sql(f"SELECT COUNT(*) AS n FROM {CATALOG}.gold.weekly_summary").collect()[0].n
print(f"✅ Weekly summaries computed for {weekly_count} weeks")

spark.sql(f"""
SELECT week_start, total_hours, total_tss, total_distance_km, ride_count
FROM {CATALOG}.gold.weekly_summary
ORDER BY week_start DESC
LIMIT 8
""").show()

# COMMAND ----------

# MAGIC %md ## Summary

# COMMAND ----------

print("\n" + "="*50)
print("Gold Layer Summary")
print("="*50)

tables = [
    "gold.daily_training_load",
    "gold.fitness_metrics",
    "gold.zone_distribution",
    "gold.weekly_summary",
]
for t in tables:
    try:
        n = spark.sql(f"SELECT COUNT(*) AS n FROM {CATALOG}.{t}").collect()[0].n
        print(f"  {t}: {n:,} rows")
    except Exception as e:
        print(f"  {t}: error — {e}")
