# Setup Guide

This guide walks through the complete first-time setup. Do this once and you're done — after this you just run the pipeline to refresh data and open notebook 06 to chat.

**Time required:** 45-60 minutes

---

## Step 1 — Get the code into Databricks

In your Databricks workspace:

1. Go to **Repos** in the left sidebar
2. Click **Add Repo**
3. Enter the repository URL: `https://github.com/Daniel-Willer/ai-coach`
4. Click **Create Repo**

The full project will appear in your workspace under `/Repos/your-username/ai-coach/`.

---

## Step 2 — Create your catalog

This creates all the Delta tables the pipeline will write to.

1. Open `notebooks/00_setup_catalog.py`
2. Run all cells (click **Run All** at the top)
3. You should see output confirming each table was created

> **If you see "catalog already exists"** — that's fine, it means you've run this before.

---

## Step 3 — Store your API credentials as Databricks secrets

The notebooks never store passwords in code. Everything is kept in Databricks Secrets, which is a secure vault built into the platform.

### What are Databricks Secrets?
Think of them as a password manager built into Databricks. You store a value once, and the notebooks retrieve it securely without ever showing it in plain text.

### How to store a secret

**Option A — Databricks CLI** (if you have it installed):
```bash
databricks secrets create-scope strava          # create the scope first
databricks secrets put --scope strava --key client_id --string-value "YOUR_VALUE"
```

**Option B — Databricks UI**:
1. Go to `https://YOUR-WORKSPACE.azuredatabricks.net/#secrets/`
2. Click **Create Scope** to create a new scope
3. Add keys one at a time

### Secrets you need to create

Work through each section below. You only need to set up the sources you actually use.

---

### Strava secrets (required)

**Scope name:** `strava`

| Key | Where to find it |
|-----|-----------------|
| `client_id` | strava.com → Settings → API → Your App → Client ID |
| `client_secret` | strava.com → Settings → API → Your App → Client Secret |
| `refresh_token` | See instructions below |

**Getting the Strava refresh token with `activity:read_all` scope:**

This is a one-time process. Strava requires you to authorize through a browser to get a token that can read your activities.

1. Go to strava.com → **Settings** → **API** → create an app if you haven't (name it anything, set website to `localhost`)

2. Open this URL in your browser (replace `YOUR_CLIENT_ID` with your actual Client ID):
   ```
   https://www.strava.com/oauth/authorize?client_id=YOUR_CLIENT_ID&redirect_uri=http://localhost&response_type=code&scope=read,activity:read_all
   ```

3. Click **Authorize** on the Strava page

4. You'll be redirected to `http://localhost?state=&code=XXXXXXXX&scope=read,activity:read_all`
   — the browser will show an error (that's expected). Copy the `code` value from the URL — it's the part between `code=` and `&scope`

5. Open a Databricks notebook and run this cell to exchange the code for a refresh token:
   ```python
   import requests
   r = requests.post("https://www.strava.com/oauth/token", data={
       "client_id":     "YOUR_CLIENT_ID",
       "client_secret": "YOUR_CLIENT_SECRET",
       "code":          "PASTE_CODE_HERE",
       "grant_type":    "authorization_code",
   })
   print(r.json().get("refresh_token"))
   ```

6. Copy the `refresh_token` value printed and store it as a secret:
   ```bash
   databricks secrets put --scope strava --key refresh_token --string-value "THE_TOKEN"
   ```

> **Important:** The `code` from step 4 is single-use and expires in ~10 minutes. Run the exchange immediately after copying it.

---

### Garmin secrets (recommended)

**Scope name:** `garmin`

| Key | Value |
|-----|-------|
| `username` | Your Garmin Connect email address |
| `password` | Your Garmin Connect password |

```bash
databricks secrets create-scope garmin
databricks secrets put --scope garmin --key username --string-value "your@email.com"
databricks secrets put --scope garmin --key password --string-value "yourpassword"
```

---

### RideWithGPS secrets (optional)

**Scope name:** `rwgps`

| Key | Where to find it |
|-----|-----------------|
| `auth_token` | ridewithgps.com → Account → API access → auth token |
| `user_id` | Your numeric ID from your profile URL: `ridewithgps.com/users/XXXXXX` |

```bash
databricks secrets create-scope rwgps
databricks secrets put --scope rwgps --key auth_token --string-value "YOUR_TOKEN"
databricks secrets put --scope rwgps --key user_id --string-value "123456"
```

---

### Intervals.icu secrets (optional)

**Scope name:** `intervals`

| Key | Where to find it |
|-----|-----------------|
| `api_key` | intervals.icu → Settings (bottom of page) → API key |
| `athlete_id` | Your ID from your profile URL: `intervals.icu/athletes/iXXXXXX` — include the `i` prefix |

```bash
databricks secrets create-scope intervals
databricks secrets put --scope intervals --key api_key --string-value "YOUR_API_KEY"
databricks secrets put --scope intervals --key athlete_id --string-value "i123456"
```

---

### OpenWeatherMap secrets (optional)

**Scope name:** `openweathermap`

Get a free API key at [openweathermap.org](https://openweathermap.org/api) — sign up, go to API keys, and copy the default key.

```bash
databricks secrets create-scope openweathermap
databricks secrets put --scope openweathermap --key api_key --string-value "YOUR_API_KEY"
```

---

## Step 4 — Set up your athlete profile

This is where you tell the system who you are — your FTP, weight, training goal, and upcoming events.

### Edit your profile

Open `config/config.yaml` in the repo. Edit the values to match you:

```yaml
athlete_id: athlete_1        # keep this as-is
name: Your Name
ftp_watts: 250               # your current FTP in watts (see below if you don't know this)
weight_kg: 75.0
birth_year: 1990
gender: Male                 # Male or Female
available_hours: 8           # realistic training hours per week
max_hr: 185                  # your maximum heart rate
resting_hr: 52               # your resting heart rate
lthr: 158                    # lactate threshold HR (roughly 85-90% of max)
training_goal: "Build base fitness for summer century ride"
injury_history: None
```

**Don't know your FTP?** A rough estimate is fine to start. Common approach: ride as hard as you can hold for 20 minutes, then multiply that average power by 0.95. If you don't have a power meter, use 200W as a placeholder and update it after your first data import.

### Edit your goal events

Open `config/event-goal-config.yaml`:

```yaml
- event_name: My Century Ride
  event_date: "2026-07-20"    # YYYY-MM-DD format
  priority: A                  # A = main goal, B = secondary, C = low priority
  event_type: Solo Ride
  target: "Finish under 5 hours"
  notes: "Main season goal"
```

Add as many events as you like. The coach uses your goal dates to calculate how far out you are and adjust training phase accordingly.

### Run the athlete setup notebook

1. Open `notebooks/05_athlete_setup.py`
2. Run all cells
3. You should see: `✅ Athlete profile saved` and your goal events listed

---

## Step 5 — Run the initial data import

Now import all your historical data. This runs once and can take 10-30 minutes depending on how many rides you have.

Run these notebooks in order:

### 1. Import Strava data
Open `notebooks/01_strava_bronze.py` and run all cells.

This imports all your rides going back 10 years (set by `DAYS_BACK = 3650`). Watch the output — it will print progress as it pages through your activities.

### 2. Import Garmin data (if you set up Garmin secrets)
Open `notebooks/00b_garmin_bronze_v2.py` and run all cells.

This imports activities, daily wellness stats, and sleep data.

### 3. Process the data
Run these in order, one at a time:

```
02_bronze_to_silver.py   ← unifies all activities into one clean table
03_silver_to_gold.py     ← calculates CTL/ATL/TSB, power zones, power curves
04_feature_refresh.py    ← builds the AI feature table
```

Each notebook prints a summary at the end when it succeeds.

---

## Step 6 — Have your first coaching conversation

1. Open `notebooks/06_coaching_agent.py`
2. Run the first three cells (pip install, restart, configuration)
3. Run all the "Load Tool Modules" cells
4. Run the "Build the Coaching Agent" cell
5. Scroll to the chat cell and run it:

```python
question = "How am I doing? Give me a full overview of where my fitness is at right now."
answer = run_agent(question, verbose=True)
print(answer)
```

You should see the agent calling tools and then producing a personalized response based on your actual data.

> **Tip:** `verbose=True` shows you which tools the agent is calling — useful to understand what data it's fetching to answer your question.

---

## You're set up

From here:
- Run notebooks 01-04 weekly to refresh your data (or whenever you want)
- Open notebook 06 anytime to chat with your coach
- See [Talking to Your Coach](05-talking-to-your-coach.md) for guidance on getting the best answers

---

## Quick reference — secret scopes

| Scope | Keys | Required |
|-------|------|----------|
| `strava` | `client_id`, `client_secret`, `refresh_token` | Yes |
| `garmin` | `username`, `password` | Recommended |
| `rwgps` | `auth_token`, `user_id` | Optional |
| `intervals` | `api_key`, `athlete_id` | Optional |
| `openweathermap` | `api_key` | Optional |
