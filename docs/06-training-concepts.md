# Training Concepts

This page explains the training science concepts the coach uses — in plain language, without assuming a sports science background. You don't need to understand all of this to use the coach, but knowing what these terms mean will help you interpret what it tells you.

---

## FTP — Functional Threshold Power

**What it is:** The highest average power output (in watts) you can sustain for roughly one hour.

**Why it matters:** FTP is the foundation of everything. It defines your training zones, lets us calculate how hard a ride was (TSS), and tracks whether your fitness is improving over time.

**The number itself:** If your FTP is 250W, a ride where you averaged 250W for an hour was maximal effort. A 3-hour ride at 200W (80% of FTP) was steady endurance pace. A 20-minute interval at 300W (120% of FTP) was VO2max work.

**How to find yours:**
- Best method: a proper ramp test (available in Zwift, TrainerRoad, etc.)
- Common shortcut: ride as hard as you can hold for 20 minutes on a flat road or turbo, then multiply that average power by 0.95
- If you don't have a power meter: use heart rate at lactate threshold (roughly the HR you could hold for ~60 minutes at maximum sustainable effort)

**When to update it:** Every 4-8 weeks if you're training consistently, or after a training block when you feel noticeably fitter. Updating your FTP in `config/config.yaml` and re-running the pipeline will recalculate your zones and historical TSS automatically.

---

## Power Zones

Training is divided into zones based on intensity relative to FTP. This system uses 7 zones:

| Zone | Name | % of FTP | How it feels | Primary adaptation |
|------|------|-----------|--------------|-------------------|
| Z1 | Active Recovery | < 55% | Very easy, barely breathing harder | Recovery |
| Z2 | Endurance | 56-75% | Comfortable, conversational | Aerobic base, fat adaptation |
| Z3 | Tempo | 76-90% | Comfortably hard, harder to hold a full conversation | Aerobic capacity |
| Z4 | Lactate Threshold | 91-105% | Hard and uncomfortable, sustainable for ~60min | Lactate threshold |
| Z5 | VO2max | 106-120% | Very hard, 5-8 minutes sustainable | Maximal oxygen uptake |
| Z6 | Anaerobic Capacity | 121-150% | Extremely hard, 1-3 minutes | Anaerobic capacity |
| Z7 | Neuromuscular | > 150% | Sprint, all-out, seconds | Power, neuromuscular |

**The polarized training principle:** For most endurance cyclists, the ideal distribution is roughly 80% of training time in Z1-Z2 and 20% in Z4-Z7, with as little as possible in Z3. Zone 3 — the "grey zone" — is hard enough to accumulate fatigue but not intense enough to drive the adaptations you get from real threshold work. If the coach flags a training imbalance, this is usually what it's seeing.

**Heart rate zones vs power zones:** Power zones are instantaneous and accurate. HR zones lag 20-30 seconds behind effort and are affected by heat, caffeine, sleep, and hydration. If you have a power meter, the coach uses power zones. Without one, it estimates from heart rate using LTHR (lactate threshold HR) as the anchor point.

---

## TSS — Training Stress Score

**What it is:** A single number representing how hard a ride was, accounting for both intensity and duration.

**The formula:**
```
TSS = (duration in hours) × (Normalized Power / FTP)² × 100
```

**Reference points:**
- 50 TSS → easy 1-hour ride at Z2 pace
- 100 TSS → very hard 1-hour effort, or moderate 2-hour ride
- 200 TSS → long hard day (5+ hour ride at steady pace)
- 300+ TSS → epic day, significant recovery required

**What "Normalized Power" means:** Regular average power undercounts variable-effort rides (sprints, climbs, stopping). Normalized Power weights harder efforts more heavily to better represent physiological cost. A hilly 2-hour ride with lots of variation might average 180W but have NP of 220W — meaning your body worked as hard as if you'd held a steady 220W.

**Without a power meter:** TSS is estimated from heart rate using the ride's average HR relative to your LTHR. It's less precise but directionally correct.

---

## CTL — Chronic Training Load (Fitness)

**What it is:** A rolling 42-day exponentially weighted average of your daily TSS. This is your **fitness** number.

**How to read it:**
- CTL goes up when you train consistently over weeks
- CTL goes down when you rest or stop training
- Most amateur cyclists operate between CTL 30-80
- Elite cyclists can reach CTL 120-150+ during peak training

**Why the 42-day window:** It takes about 6 weeks of consistent training for an adaptation to fully express itself (blood volume increase, mitochondrial density, cardiac efficiency). The 42-day average reflects this physiological reality.

**What it tells you:** A CTL of 60 means you've been carrying significant training load consistently. A CTL of 25 means you've been training lightly or inconsistently. When the coach says "your fitness base is solid" or "your base is low for your goal event," it's reading CTL.

---

## ATL — Acute Training Load (Fatigue)

**What it is:** A rolling 7-day exponentially weighted average of your daily TSS. This is your **fatigue** number.

**How it moves:**
- ATL responds quickly — a big training day spikes it fast
- ATL also drops fast — 4-5 easy days can bring it back down significantly
- ATL is always more volatile than CTL

**What it tells you:** High ATL means you've been training hard recently and are accumulated fatigued. Low ATL means you've been resting (or not training). You want ATL high during a build phase and deliberately lowered before an important event.

---

## TSB — Training Stress Balance (Form)

**What it is:** CTL minus ATL. This is your **form** — how fresh or fatigued you are right now.

```
TSB = CTL − ATL
```

**How to interpret it:**

| TSB | State | What it means |
|-----|-------|--------------|
| +15 to +25 | Peak form | Very fresh, ready to perform. Could be losing fitness if sustained too long. |
| 0 to +15 | Fresh | Good condition for hard training or events |
| -10 to 0 | Optimal training zone | Some fatigue but still adapting well |
| -10 to -30 | Functional overreaching | Significant fatigue — still productive if recovery planned |
| Below -30 | Non-functional overreaching | Risk zone — performance will decline, recovery needed |

**The paradox:** To build fitness (raise CTL), you have to train hard enough that ATL rises, which drives TSB negative. You can't get fitter without spending time in negative TSB. The goal is to manage how negative you go and when — training hard during a build block, then easing off to let TSB rise before an important event.

**Before a goal event:** Ideally arrive with TSB between +5 and +20. This means your fitness (CTL) is high from weeks of training, but you've backed off recently enough that fatigue has cleared. This is called "tapering."

---

## The CTL/ATL/TSB System in Practice

A typical training block looks like this over 8 weeks:

```
Weeks 1-3: Build block
  → Training hard, ATL rises, TSB goes to -20 to -30
  → CTL slowly rising (takes weeks to move)
  → You feel tired but this is expected

Week 4: Recovery week
  → Volume cut 30-40%, ATL drops rapidly
  → TSB recovers to near 0 or slightly positive
  → CTL continues to rise slightly (delayed response)
  → You feel fresh — this is when CTL is actually growing

Weeks 5-7: Second build block
  → Repeat pattern, CTL now higher than before

Week 8: Taper (before goal event)
  → Volume cut significantly, ATL drops fast
  → TSB rises to +10 to +20
  → CTL dips slightly (unavoidable in taper)
  → You feel "race ready"
```

The coach models this cycle and uses it to tell you where in the pattern you are and what you should be doing.

---

## HRV — Heart Rate Variability

**What it is:** The variation in time between consecutive heartbeats. Counter-intuitively, more variation is better.

**The science:** Your heart doesn't beat like a metronome — the time between beats varies slightly. This variation is controlled by your autonomic nervous system. When you're well-recovered, your parasympathetic system (rest-and-digest) dominates and HRV is high. When you're stressed — physically or mentally — your sympathetic system (fight-or-flight) dominates and HRV drops.

**How Garmin measures it:** During sleep (typically between 2-6 AM when it's most stable), the watch measures beat-to-beat intervals. It reports this as RMSSD (root mean square of successive differences), measured in milliseconds, averaged over the night.

**Your baseline:** HRV is highly individual — a reading of 65ms might be excellent for one person and poor for another. What matters is your personal baseline and deviations from it. The coach tracks your 7-day and 30-day average and flags readings that are significantly below baseline.

**What a low HRV reading means:** Your nervous system hasn't fully recovered. This could be from hard training, poor sleep, alcohol, illness, high stress, or dehydration. It doesn't always mean "don't train" — but it's a signal to be more conservative about intensity.

---

## Body Battery

**Garmin's composite readiness score**, running from 0-100. It combines:
- Overnight HRV quality
- Sleep duration and quality
- Daytime stress (measured from HRV during the day)
- Activity level during the day

**Reference points:**
- 75-100 in the morning → well recovered, ready for hard training
- 50-75 → moderate recovery, normal training fine
- 30-50 → some fatigue, moderate training only
- Below 30 → significantly depleted, recovery session or rest day recommended

Body battery charges while you sleep and drains through the day. It's most useful as a morning reading before you've done anything — by afternoon it's already been drained by daily activity.

---

## Putting it all together

When you ask the coach "should I train hard today?", it's weighing all of this simultaneously:

1. **TSB** — are you fresh or fatigued from a training load perspective?
2. **HRV** — is your nervous system recovered?
3. **Body battery** — does Garmin's composite score confirm recovery?
4. **Sleep quality** — did you actually sleep enough and well?
5. **Training phase** — is this a build week where fatigue is expected, or a recovery week?
6. **Days to goal** — how close is your next important event?

All six can point the same direction (clear "train hard" or clear "rest day") or they can conflict (TSB positive but HRV low). The coach handles these conflicts explicitly rather than defaulting to one metric — which is what makes it different from a generic training app.
