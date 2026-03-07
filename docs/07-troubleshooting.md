# Troubleshooting

Common errors and how to fix them. Organized by where the error occurs.

---

## Strava errors

### Strava 401 Unauthorized (Cell 10 fails, Cell 8 works) {#strava-401-error}

**What it looks like:**
```
Cell 8 (athlete endpoint) — succeeds, returns your name
Cell 10 (activities endpoint) — 401 Unauthorized
```

**Root cause:** Your refresh token was authorized with only the `read` scope, which lets Strava confirm your identity but not read your activities. Activities require the `activity:read_all` scope.

**Fix:** Re-authorize with the correct scope. Open notebook `01_strava_bronze.py` and run the diagnostic cell — it will print the exact URL you need to visit and step-by-step instructions.

In short, you'll:
1. Visit a Strava authorization URL in your browser (the notebook prints it)
2. Click Authorize
3. Copy the `code` from the redirect URL
4. Run a small Python snippet to exchange it for a new refresh token
5. Store the new refresh token as a Databricks secret

After this is done, run the notebook again and Cell 10 should succeed.

---

### Strava token expired mid-run

**What it looks like:** Runs succeed for a while then fail with 401 partway through a large import.

**Why it happens:** Strava access tokens expire after 6 hours. If you're importing 10 years of rides, the token can expire during the run.

**Fix:** The notebook refreshes the token automatically using your stored refresh token. If this is still failing, the refresh token itself may have been revoked (this happens if you deauthorize the app in Strava settings or if the token was never stored with the right scope — see above).

---

### Strava returns empty activities list

**What it looks like:** The notebook completes without errors but imports 0 activities.

**Possible causes:**
1. Your Strava account has no activities — confirm you have rides on strava.com
2. The date range is wrong — the notebook imports the last 3650 days by default
3. The activities are private — Strava's API returns private activities only if the token has `activity:read_all` scope (same fix as the 401 issue above)

---

## Garmin errors

### Garmin login failure / 2FA block

**What it looks like:**
```
GarminConnectAuthenticationError: Authentication error
```
or
```
GarminConnectTooManyRequestsError
```

**Root cause:** Garmin Connect blocks automated login attempts if:
- Your password is wrong in Databricks secrets
- Garmin detects the login as suspicious (new IP address, VPN)
- You've recently changed your password
- Garmin is enforcing multi-factor authentication

**Fix:**
1. Verify your credentials are correct:
   ```bash
   databricks secrets list --scope garmin
   ```
2. Log into Garmin Connect manually in a browser to confirm the password works
3. If Garmin sent a verification email/SMS, complete that verification in the browser first — this "trains" Garmin to trust the login pattern
4. Wait 15-30 minutes before retrying (Garmin rate-limits failed attempts aggressively)

**Note on MFA:** If your Garmin account has two-factor authentication enabled, automated login will fail. The `garminconnect` library handles the MFA challenge but it requires interactive input — which doesn't work in a scheduled Databricks job. Disable 2FA on your Garmin Connect account if you want automated data import.

---

### Garmin returns no data for recent days

**What it looks like:** The notebook runs without errors but the last 3-5 days are missing.

**Why it happens:** Garmin Connect typically has a 24-48 hour lag on syncing processed data (especially sleep stages and HRV). Raw data syncs quickly, but processed metrics can be delayed.

**Fix:** This is normal. Run the Garmin notebook again tomorrow and the missing days will appear. For real-time data (today's body battery, current HRV), use the live Garmin tools in the coaching agent — they query the API directly.

---

## Delta table errors

### `DELTA_FAILED_TO_MERGE_FIELDS` — schema mismatch

**What it looks like:**
```
AnalysisException: DELTA_FAILED_TO_MERGE_FIELDS
Failed to merge fields 'duration_min' due to data type mismatch detected.
```

**Root cause:** A table was created in a previous run with one column type (e.g., `INT`) but the current code is trying to write a different type (`DOUBLE`). The `CREATE TABLE IF NOT EXISTS` statement skips recreation if the table already exists, so the type never gets corrected.

**Fix:** Drop the table and let the notebook recreate it:

In a new Databricks notebook cell:
```python
spark.sql("DROP TABLE IF EXISTS ai_coach.coach.planned_workouts")
spark.sql("DROP TABLE IF EXISTS ai_coach.coach.training_plans")
```

Then re-run `07_training_planner.py` from the top.

**Note:** Dropping these tables only loses saved training plans, not your ride data or pipeline tables.

---

### Table doesn't exist error during pipeline

**What it looks like:**
```
AnalysisException: Table or view not found: ai_coach.bronze.strava_activities
```

**Root cause:** The catalog setup notebook hasn't been run, or it failed partway through.

**Fix:** Run `00_setup_catalog.py` from the top. It creates all tables with `CREATE TABLE IF NOT EXISTS`, so running it again is safe even if some tables already exist.

---

### `CREATE TABLE` succeeds but data never writes

**What it looks like:** The pipeline runs without errors and reports 0 rows written, but the table exists in the catalog.

**Why it happens:** Usually a filter in the pipeline is too restrictive. For example, if `DAYS_BACK` in the Strava notebook is set to 7 but your most recent Strava activity is older than 7 days (e.g., you haven't ridden in 2 weeks), no activities will be in range.

**Fix:** In `01_strava_bronze.py`, temporarily increase `DAYS_BACK`:
```python
DAYS_BACK = 365   # pull last year instead of last week
```

Run the notebook, then set it back to your preferred value.

---

## Databricks Secrets errors

### `SecretDoesNotExist`

**What it looks like:**
```
com.databricks.backend.manager.util.UnknownSecretScopeException:
Secret does not exist with scope: strava and key: client_id
```

**Fix:** The secret either wasn't created or is in a different scope than expected. Check what scopes and keys you have:

```bash
databricks secrets list-scopes
databricks secrets list --scope strava
```

Then create any missing ones:
```bash
databricks secrets put --scope strava --key client_id --string-value "YOUR_VALUE"
```

---

### `SecretScopeAlreadyExists`

**What it looks like:**
```
Error: Secret scope 'strava' already exists.
```

**This is not an error.** If the scope already exists, you can go straight to adding keys to it. Skip the `create-scope` command and just run `put`.

---

## Coaching agent errors

### Agent produces "I don't have access to that data"

**What it means:** The tool returned an error or empty result, and the agent is being honest about it.

**Debug steps:**
1. Turn on verbose mode: `run_agent(question, verbose=True)` — this shows which tools were called
2. Look at which tool returned the error
3. Go to the relevant lib file and check the tool's SQL query or API call directly
4. Common causes:
   - Pipeline hasn't been run recently (tables are empty or stale)
   - The data source isn't connected (missing secrets)
   - The question references data that doesn't exist (e.g., a route that's not in RideWithGPS)

---

### Agent loops or times out

**What it looks like:** The agent calls tools repeatedly and never produces a final answer, or throws `max_iterations exceeded`.

**Why it happens:** The agent got confused about which tool to call or the tool returned an unexpected format that it couldn't interpret.

**Fix:**
1. The agent has a max iteration limit (set to 8 in `06_coaching_agent.py`). If this is regularly hit, increase it — but first check if the question is too complex
2. Break complex questions into simpler ones: instead of "compare my last 3 months to the same period last year and suggest changes," ask about each piece separately
3. Restart the Python kernel and re-run all setup cells — occasionally a stale variable causes loops

---

### `%run` error when loading lib modules

**What it looks like:**
```
Exception: The %run magic requires a path argument
```
or
```
ModuleNotFoundError when importing from lib
```

**Root cause:** The `%run` path in `06_coaching_agent.py` is relative to the notebook location. If you've moved the notebook or cloned the repo to a different path, the relative path breaks.

**Fix:** Check the `%run` lines at the top of `06_coaching_agent.py`. They should look like:
```python
# MAGIC %run ./lib/tools_data
```

The `./lib/` path assumes `tools_data.py` is in a `lib/` subfolder in the same directory as the notebook. If your folder structure is different, update these paths.

---

### LLM returns generic advice, not personalized

**What it looks like:** The coach gives advice like "you should train consistently and make sure to recover" without referencing your actual numbers.

**Why it happens:** The tools returned empty or error results, so the agent fell back to general knowledge without data.

**Debug steps:**
1. Check that the pipeline has been run recently (within the last week)
2. Verify the catalog name in `06_coaching_agent.py` matches your actual catalog:
   ```python
   CATALOG = "ai_coach"   # must match what 00_setup_catalog.py created
   ```
3. Run the athlete profile check: `question = "What is my FTP?"` — if this fails to return a number, the athlete table is missing or the catalog name is wrong

---

## Git and sync issues

### My changes in Databricks aren't showing locally (or vice versa)

**Why it happens:** Databricks has a built-in AI assistant that sometimes auto-commits changes to the same branch you're working on locally. This creates diverged histories.

**Safe resolution:**
```bash
git fetch origin
git pull --no-rebase -X ours
```

The `-X ours` flag means: if there's a conflict, keep your local version. This is appropriate here because your local code is canonical and the Databricks assistant's changes are usually incorrect schema modifications.

If the pull still fails with conflicts:
```bash
git checkout --ours notebooks/07_training_planner.py   # keep your version
git add notebooks/07_training_planner.py
git rebase --continue   # or git commit if not rebasing
```

**Prevention:** In Databricks, go to **Settings** → **Workspace Settings** → disable the Databricks Assistant auto-commit feature if available. Alternatively, push your local changes first before opening the notebook in Databricks.

---

## Performance issues

### Pipeline is slow / times out

**For the initial import (first run):** This is expected. Importing 10 years of Strava data, computing CTL/ATL/TSB for every day, and building power curves is real work. Give it 20-30 minutes.

**For subsequent weekly runs:** Should complete in under 10 minutes. If it's slower:
- Check if the cluster has enough memory (use at least 8GB RAM)
- Look for inefficient queries in the notebook output — some SQL operations on large tables can be slow
- Consider increasing the cluster size temporarily for pipeline runs, then scaling back down

**For the coaching agent:** Tool calls typically complete in 1-3 seconds. The full agent response (including LLM time) usually takes 10-30 seconds. If it's taking 2+ minutes, check network connectivity to the Databricks SQL warehouse.

---

## Still stuck?

If none of the above fixes your issue:

1. **Check the error message carefully** — Databricks error messages are usually specific. Copy the exact error and search for it.

2. **Check the cell that failed** — run each cell individually rather than "Run All" so you can identify exactly where it breaks.

3. **Check data exists** — open a new notebook and run:
   ```python
   spark.sql("SHOW TABLES IN ai_coach.bronze").show()
   spark.sql("SELECT COUNT(*) FROM ai_coach.bronze.strava_activities").show()
   ```
   This tells you whether the tables exist and have data.

4. **Reset and re-run** — for persistent issues, sometimes the cleanest fix is:
   ```python
   spark.sql("DROP TABLE IF EXISTS ai_coach.silver.activities")
   spark.sql("DROP TABLE IF EXISTS ai_coach.gold.daily_training_load")
   ```
   Then re-run notebooks 02 and 03. Your bronze data is still intact — you're only dropping the processed tables.
