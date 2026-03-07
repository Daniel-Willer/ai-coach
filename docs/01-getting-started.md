# Getting Started

## What is this?

This is a personal AI cycling coach that lives in your own Databricks environment. It connects to your training data — Strava, Garmin, RideWithGPS — and lets you have real coaching conversations grounded in your actual numbers.

Unlike generic training apps, this coach knows your specific FTP, your sleep last night, your body battery right now, how your CTL has trended over 8 weeks, and what your power curve looks like. When it tells you to take a rest day, it's because your TSB is -35 and your HRV is low — not because a generic algorithm said so.

---

## How it works — the big picture

```
Your Data Sources              Databricks Pipeline           AI Coach
─────────────────              ───────────────────           ────────
Strava (rides)      ──────►   Bronze tables
Garmin (sleep/HRV)  ──────►   Silver tables    ──────────►  Notebook 06
RideWithGPS         ──────►   Gold tables                   (chat here)
Intervals.icu       ──────►   Feature table
```

1. **Data ingestion** — Notebooks 00-01 pull your raw data from each source into Databricks
2. **Processing** — Notebooks 02-04 clean it, unify it, and calculate training load metrics
3. **Chat** — Notebook 06 is where you talk to the coach; it queries your data in real time to answer your questions

The coach never guesses. When you ask "how is my fitness?", it runs a SQL query against your gold tables before it answers.

---

## What the coach can do

### Analyze your training
- Review any specific ride — zones, HR drift, intensity factor, whether it was appropriate
- Spot whether you're spending too much time in the "grey zone" (moderate intensity that's neither easy nor hard enough)
- Track whether your peak power at 5min or 20min is improving over time

### Assess your readiness
- Check your current CTL (fitness), ATL (fatigue), TSB (form)
- Factor in last night's sleep, this morning's HRV, and body battery
- Tell you whether today is a day to push hard or back off

### Plan your training
- Prescribe a specific workout for today based on your current state
- Generate a full 7-day training week with target TSS per day
- Build a multi-week periodized training plan toward your goal event
- Suggest routes from your RideWithGPS library that match a target duration

### Answer training questions
- "Am I overtraining?"
- "How does this week compare to last month?"
- "I have 8 hours this week — how should I spread them?"
- "Should I do my intervals today or is the weather better tomorrow?"

---

## What you need before starting

### Required
- **Strava account** with your rides logged (the more history the better)
- **Databricks workspace** — this is where everything runs. If you're at a company that uses Databricks, you may already have access. Otherwise, Databricks has a Community Edition that works for this.

### Strongly recommended
- **Garmin device** (watch or head unit) with Garmin Connect account — provides sleep, HRV, body battery, and resting HR, which are critical for recovery-based recommendations
- **Power meter** — the coaching is significantly better with power data. Without power, the coach works from HR and pace instead.

### Optional
- **RideWithGPS account** — only needed if you want route suggestions
- **Intervals.icu account** — free platform that provides another source of training load data
- **OpenWeatherMap API key** — free, enables weather-based recommendations

### Technical requirements
- You'll need to be comfortable navigating Databricks notebooks (basic cell execution)
- You don't need to understand the code — just run cells in order
- A basic understanding of cycling training metrics helps but isn't required — see [Training Concepts](06-training-concepts.md) if you want to learn

---

## Time investment

| Task | Time |
|------|------|
| First-time setup | 45-60 minutes |
| Initial data backfill (all your history) | 10-30 minutes (runs unattended) |
| Weekly pipeline refresh | 5 minutes |
| A coaching conversation | As long as you want |

---

## Next step

→ [Setup Guide](02-setup.md) — complete step-by-step first-time configuration
