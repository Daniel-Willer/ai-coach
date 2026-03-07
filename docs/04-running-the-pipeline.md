# Running the Pipeline

The pipeline is how your data stays fresh. It pulls new rides and wellness data from your connected sources, processes them through bronze → silver → gold, and updates the feature table the coach reads from.

This page explains when to run it, what order the notebooks go in, and what to do when something fails.

---

## The notebook order

Always run notebooks in this sequence:

```
00b_garmin_bronze_v2.py   ← pull new Garmin data (sleep, HRV, body battery)
01_strava_bronze.py       ← pull new Strava rides
02_bronze_to_silver.py    ← clean and unify all activity data
03_silver_to_gold.py      ← calculate CTL/ATL/TSB, power zones, power curves
04_feature_refresh.py     ← build the AI's feature table
```

You don't need to run `00_setup_catalog.py` again — that was a one-time setup.
You don't need to run `05_athlete_setup.py` again unless you're updating your FTP, weight, or goals.

**Each notebook depends on the previous one.** Don't skip steps. If you only run notebook 01 and 03, the silver table will be out of date and gold will have gaps.

---

## How often to run it

**Recommended: once a week**, before your next coaching conversation.

Running it more often is fine — there's no harm in running it daily. The notebooks detect what's already been imported and only pull new data, so re-running is safe and fast.

**When you definitely want to run it:**
- Before asking the coach for a weekly training plan (you want it based on current data)
- After a block of heavy training where you want to check your TSB
- After a rest week to see your CTL/ATL numbers updated
- Before a goal event when you're checking form

**You don't need to run it every time you chat.** The coach also has live tools that can pull your most recent Strava activity and Garmin data directly from the API, without the pipeline. But the pipeline gives the coach historical depth — CTL trends over 8 weeks, your power curve across all time, zone distribution patterns.

---

## What each notebook does

### `00b_garmin_bronze_v2.py` — Garmin import

Pulls from Garmin Connect:
- Daily wellness stats (HRV, body battery, resting HR, stress, steps) for the last 30 days
- Sleep data for the last 30 days
- Activities (if you have a Garmin head unit or watch that records rides)

Takes 1-3 minutes. You'll see progress printed as it pulls each day.

**Output:** rows added to `bronze.garmin_wellness`, `bronze.garmin_sleep`, `bronze.garmin_activities`

---

### `01_strava_bronze.py` — Strava import

Pulls your Strava activities. On first run, it goes back 10 years. On subsequent runs, it picks up where it left off based on the most recent activity already stored.

Takes 1-5 minutes for a weekly refresh (depending on how many new rides).

**Output:** rows added to `bronze.strava_activities`

> **If this fails with a 401 error:** your Strava token needs to be refreshed. See [Troubleshooting](07-troubleshooting.md#strava-401-error).

---

### `02_bronze_to_silver.py` — Bronze to Silver

Reads all activities from both Strava and Garmin bronze tables, normalizes column names, resolves duplicates (Strava and Garmin sometimes have the same ride), and writes a clean unified `silver.activities` table.

Also processes:
- Routes from RideWithGPS → `silver.routes`
- Athlete profile → `silver.athletes`

Takes 1-3 minutes.

**Output:** `silver.activities` refreshed with all cleaned activities

---

### `03_silver_to_gold.py` — Silver to Gold

This is the most computationally intensive step. It:
- Calculates TSS for each activity (using power if available, HR-based estimate otherwise)
- Runs the CTL/ATL/TSB calculation for every day in your history
- Computes your power zones for each ride based on your current FTP
- Builds your power curve (best power at 5s, 1m, 5m, 20m, 60m across all rides)
- Detects zone distribution for each ride

Takes 2-8 minutes depending on how much history you have.

**Output:** `gold.daily_training_load`, `gold.fitness_metrics`, `gold.zone_distribution`, `gold.power_curve`

---

### `04_feature_refresh.py` — Feature table

Builds a single daily snapshot table that the coaching agent reads from. It joins gold metrics, athlete profile, recent sleep/HRV, and upcoming goal events into one row per day.

This is what the coach queries when you ask "how am I doing?" — it gets the full picture from one optimized table instead of joining 6 tables in real time.

Takes under 1 minute.

**Output:** `features.daily_athlete_snapshot`

---

## Running the full pipeline

To run a notebook in Databricks:

1. Open the notebook from the file browser (left sidebar → **Workspace** → your repo folder)
2. Click **Run all** at the top of the notebook
3. Wait for all cells to complete (green checkmarks)
4. If any cell shows a red error, stop and check [Troubleshooting](07-troubleshooting.md) before continuing

Don't move to the next notebook until the current one finishes without errors.

---

## Scheduling the pipeline (optional)

Instead of running notebooks manually, you can schedule them to run automatically in Databricks Jobs.

### Creating a job

1. In Databricks, go to **Workflows** in the left sidebar
2. Click **Create job**
3. Name it something like "Weekly Training Data Refresh"
4. Add tasks in order:
   - Task 1: `00b_garmin_bronze_v2`
   - Task 2: `01_strava_bronze` (depends on Task 1)
   - Task 3: `02_bronze_to_silver` (depends on Task 2)
   - Task 4: `03_silver_to_gold` (depends on Task 3)
   - Task 5: `04_feature_refresh` (depends on Task 4)
5. Set the schedule — Sunday night (e.g., 23:00) works well so data is fresh for Monday planning
6. Set the cluster — use the smallest available cluster to keep costs low

### Cost consideration

Running notebooks costs compute time. For a weekly refresh on Databricks Community Edition, this is free. On a paid workspace:
- The full pipeline takes roughly 10-15 minutes
- Use a single-node cluster (e.g., `Standard_DS3_v2` or equivalent) to minimize cost
- Scheduled jobs are cheaper than interactive notebook runs because they use job clusters that spin down automatically

---

## What "incremental" means

The pipeline is incremental — each run only processes what's new:

- Strava import: checks the timestamp of the most recent activity already in bronze, only fetches rides after that date
- Garmin import: always pulls the last 30 days (Garmin API doesn't support incremental by timestamp easily, but re-processing the same days is fast and idempotent)
- Bronze to Silver: uses `MERGE INTO` to upsert — existing rows are updated if changed, new rows are inserted
- Silver to Gold: recalculates from the earliest "dirty" date forward (any day where a new activity was added)
- Feature refresh: always rebuilds the last 90 days of the snapshot table

This means you can safely re-run any notebook and it won't create duplicate data.

---

## Running individual notebooks

Sometimes you only need to refresh part of the pipeline.

**Just added new routes to RideWithGPS?**
Run `02_bronze_to_silver.py` — it will pick up the new routes without needing to re-import Strava.

**Updated your FTP in the athlete profile?**
Run `03_silver_to_gold.py` — it recalculates zones and TSS from the new FTP.
Then run `04_feature_refresh.py` to propagate the change to the feature table.

**Only want to check recent sleep/HRV without importing all rides?**
Run `00b_garmin_bronze_v2.py` and `04_feature_refresh.py`.

---

## Checking that the pipeline ran successfully

After running the full pipeline, you can verify it worked by opening notebook 06 and running:

```python
question = "What is my current CTL, ATL, and TSB? When was my last ride?"
answer = run_agent(question)
print(answer)
```

If the coach returns current numbers with recent dates, the pipeline is working. If it returns very old dates or says it can't find data, something in the pipeline failed — go back and check each notebook's output for errors.

---

## After updating your athlete profile

If you change your FTP, weight, or training goal in `config/config.yaml`, run these after saving the file:

```
05_athlete_setup.py      ← re-saves your profile to the Delta tables
03_silver_to_gold.py     ← recalculates zones and TSS with new FTP
04_feature_refresh.py    ← updates the feature table
```

FTP changes affect TSS calculations for all your historical rides (a higher FTP means lower TSS per ride). This is expected — the coach will reflect the recalculated numbers after step 3.
