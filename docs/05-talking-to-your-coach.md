# Talking to Your Coach

This page covers how to have useful coaching conversations — how to frame questions, what the coach is good at, what to expect, and a set of example conversations you can try directly.

---

## How to open a conversation

1. Open `notebooks/06_coaching_agent.py` in Databricks
2. Run all cells from the top down (pip install → configuration → tool modules → build agent)
3. Scroll to the chat cell near the bottom:

```python
question = "your question here"
answer = run_agent(question, verbose=True)
print(answer)
```

4. Change the question text and run the cell

You can run the chat cell as many times as you want without re-running the setup cells above. The agent resets between runs — it doesn't remember your previous questions in the same session (yet).

---

## What `verbose=True` shows you

When verbose mode is on, you'll see which tools the agent called before answering:

```
> Entering new AgentExecutor chain...
Invoking: `get_training_load` with {'athlete_id': 'athlete_1', 'days': 14}
Invoking: `get_fitness_snapshot` with {'athlete_id': 'athlete_1'}
> Finished chain.
```

This is useful for understanding what data the coach is basing its answer on. If it's giving you an answer you don't expect, look at which tools it called — did it check your HRV? Did it look at the right time period?

Turn it off with `verbose=False` for cleaner output.

---

## The kinds of questions it answers well

### Status and readiness
These are the fastest, most reliable answers because the coach just reads your current data.

- *"How am I doing right now? Give me a full overview."*
- *"What is my current fitness level?"*
- *"Should I train hard today or back off?"*
- *"How recovered am I?"*
- *"What does my HRV say about today?"*

### Ride analysis
The coach pulls detailed data from a specific ride and tells you whether it was appropriate, what zones you were in, and what it means for your training.

- *"How did my last ride go?"*
- *"Was my effort level appropriate yesterday?"*
- *"Did I go too hard on Thursday's ride?"*
- *"What zones was I in on my last ride?"*

### Workout planning
The coach looks at your current TSB, your training phase, your available time, and your imbalances before suggesting a session.

- *"What should I do today?"*
- *"Prescribe me a workout for this afternoon."*
- *"I have 90 minutes — what should I ride?"*
- *"Give me a full training plan for this week."*
- *"I'm doing a race in 3 weeks — what should my schedule look like?"*

### Trend analysis
These require more data and take slightly longer to answer, but the coach can trace your fitness trajectory.

- *"Is my fitness improving?"*
- *"How does this week compare to 4 weeks ago?"*
- *"Am I spending too much time in the wrong zones?"*
- *"Is my peak power getting better or worse?"*
- *"Have I been overtraining?"*

### Route and ride planning
If you have RideWithGPS connected, the coach can suggest specific routes from your library.

- *"Suggest a route for a 2-hour hilly ride today."*
- *"What's a good recovery route — flat, under 45 minutes?"*
- *"I want to do 80km this weekend — what route fits?"*

### Weather-based decisions
If OpenWeatherMap is connected and you include your city, the coach factors conditions into its advice.

- *"Should I ride outside today in London or do a Zwift session?"*
- *"What's the best time to ride tomorrow in Manchester?"*
- *"Is this week a good week for outdoor riding in my area?"*

---

## How to ask better questions

### Include context
The more context you give, the better the answer.

Instead of: *"What should I do today?"*
Try: *"I have 2 hours this morning and I'm feeling a bit tired. What should I do today?"*

Instead of: *"Am I overtraining?"*
Try: *"I've been training hard for 3 weeks straight. Am I overdoing it?"*

### Ask for specifics
The coach defaults to general advice unless you ask for specifics.

Instead of: *"Give me a workout."*
Try: *"Give me a specific interval workout for today with target power zones, duration, and structure."*

### Ask follow-up questions
The chat cell runs independently each time, so the coach doesn't remember the previous answer. But you can include context in the next question.

*"Based on my TSB being negative, what kind of sessions should I be doing this week?"*

*"My coach said I need more Z2 time. Does my training data support that?"*

### Tell it your constraints
- *"I can only ride indoors this week."*
- *"I have an event on Saturday — plan around that."*
- *"I don't have a power meter, use HR-based advice."*
- *"I'm coming back from 2 weeks off sick."*

---

## Example conversations

### Full status check

```
"How am I doing? Give me a complete picture of my current fitness,
 fatigue, form, and readiness."
```

**What to expect:** The coach pulls CTL/ATL/TSB, checks last night's sleep and HRV if Garmin is connected, looks at your training load trend over the last 2 weeks, and gives you a plain-English summary of where your fitness stands and what it means for training today.

---

### Workout prescription

```
"I have 75 minutes this morning. What workout should I do given my current form?"
```

**What to expect:** The coach checks your TSB (positive → quality session; negative → recovery/moderate), your zone distribution over the last 3 weeks (to identify gaps), and your goal event timeline. It prescribes a specific session: type, target zones, duration, structure (e.g., 15min warm-up, 3x10min threshold, 15min cool-down), and target TSS.

---

### Last ride review

```
"How did my ride yesterday go? Was it appropriate given where I am in training?"
```

**What to expect:** The coach pulls your most recent activity, checks which zones you were in, calculates your intensity factor, compares it to your FTP, and tells you whether the effort was easy/moderate/hard and whether that was right given your current TSB and training phase.

---

### Weekly plan

```
"Generate a training plan for this week. I have about 8 hours available and
 I want to build fitness without digging myself too deep."
```

**What to expect:** A 7-day schedule with each day's workout type, target duration, target TSS, and brief description. The coach assigns rest days, builds in intensity on appropriate days, and keeps the week's total TSS within a range that won't tank your form too badly.

---

### Training imbalance check

```
"Am I training in the right zones? I feel like I'm always going moderate pace
 and never really hard or easy."
```

**What to expect:** The coach looks at your zone distribution over the last 4 weeks and tells you exactly what % of time you've spent in each zone. If you're spending too much time in Z3 (the "grey zone" — too hard to be real recovery, too easy to drive real adaptation), it will flag this and suggest how to restructure your riding.

---

### Race prep

```
"I have a gran fondo in 3 weeks. What should my training look like between now and then?"
```

**What to expect:** The coach calculates the weeks to event, identifies your current CTL and TSB, and designs a taper. Usually: one more quality week, then a reduced volume week, then race week. It'll tell you specifically what to do in each week and why.

---

### Recovery check with conflicting signals

```
"My TSB says I'm fresh but I feel terrible and slept badly last night. Should I train?"
```

**What to expect:** This is where the Garmin integration shines. The coach checks your HRV, body battery, and sleep quality from last night. If those are poor despite positive TSB, it overrides the numbers and recommends backing off. Real coaches know that metrics and subjective feel tell different stories — and the subjective signal often wins.

---

### Power trend

```
"Is my 20-minute power improving? I've been doing structured intervals for 6 weeks."
```

**What to expect:** The coach pulls your power curve data and compares your best 20-minute power across 30/60/90-day windows. If it's trending up, it confirms the intervals are working. If it's flat or down, it investigates possible causes (too much fatigue, not enough recovery, wrong zone targeting).

---

## What the coach doesn't do (yet)

- **Remember conversation history** — each question is independent. If you want continuity, include context in your question.
- **Look at your Garmin workout calendar** — it reads wellness data but not scheduled workouts you've added in Garmin Connect.
- **Connect to Wahoo, TrainingPeaks, or other platforms** — currently only Strava, Garmin, RideWithGPS, and Intervals.icu.
- **Automatically send you messages** — you have to open notebook 06 and ask. There's no push notification or daily digest (yet).
- **Coach non-cycling activities** — running, swimming, strength training are visible if logged on Strava but the analysis is cycling-specific.

---

## Understanding the coach's answers

### When it says "push hard today"
It has checked: TSB is positive (you're fresh), HRV is at or above baseline, sleep was decent, and you're in a build phase relative to your goal event. These signals all point the same direction.

### When it says "take it easy"
One or more of: TSB is deeply negative (you're accumulated too much fatigue), HRV is suppressed, body battery is low, or you're in a taper/recovery week before an event.

### When it hedges
If the coach says "moderate training is appropriate" without a strong recommendation either way, it usually means signals are mixed — your TSB looks ok but your sleep was poor, or your HRV is borderline. Take this as "listen to your body" advice grounded in data.

### When it says it can't answer
If it says it doesn't have data for something, it's because that data source isn't connected or the pipeline hasn't been run recently. Check which data sources are active in your setup.

---

## Tips for getting the most out of it

- **Run the pipeline weekly** so the coach has current data to work from
- **Ask the same question two ways** if the first answer feels vague — rephrasing often triggers different tool usage
- **Ask it to explain its reasoning** — "why are you recommending this?" usually produces a more detailed breakdown
- **Use it before hard sessions** — "is this a good day to do my VO2max intervals?" takes 30 seconds and can save a wasted hard session
- **Use it for retrospectives** — "how did last week go overall?" is a great Monday morning question
