# Databricks notebook source
# MAGIC %md
# MAGIC # 06 — AI Cycling Coach Agent
# MAGIC
# MAGIC A Databricks-native coaching agent using:
# MAGIC - **Databricks Foundation Models API** — Llama 3.3 70B (no external API keys needed)
# MAGIC - **LangChain tool-calling** — tools query your Delta tables directly
# MAGIC - **MLflow** — logs conversations and agent versions
# MAGIC
# MAGIC Tools are split into three modules loaded via `%run`:
# MAGIC - `lib/tools_data`     — 7 core data retrieval tools
# MAGIC - `lib/tools_analysis` — 4 enhanced performance analysis tools
# MAGIC - `lib/tools_planning` — 6 workout and ride planning tools
# MAGIC
# MAGIC **Run after:** notebooks 00–05 (full pipeline must have data)

# COMMAND ----------

# MAGIC %pip install databricks-langchain langchain-core mlflow -q

# COMMAND ----------

# MAGIC %restart_python

# COMMAND ----------

# MAGIC %md ## Configuration

# COMMAND ----------

CATALOG = "ai_coach"
ATHLETE_ID = "athlete_1"  # change to match your athlete_id from notebook 05

# Databricks Foundation Models endpoint — choose one:
#   "databricks-meta-llama-3-1-70b-instruct"  ← best for reasoning (recommended)
#   "databricks-meta-llama-3-3-70b-instruct"  ← latest Llama
#   "databricks-dbrx-instruct"                 ← Databricks' own model
#   "databricks-mixtral-8x7b-instruct"         ← faster, lighter
LLM_ENDPOINT = "databricks-meta-llama-3-3-70b-instruct"

print(f"Catalog:    {CATALOG}")
print(f"Athlete:    {ATHLETE_ID}")
print(f"LLM:        {LLM_ENDPOINT}")

# COMMAND ----------

# MAGIC %md ## Load Tool Modules

# COMMAND ----------

# MAGIC %run ./lib/tools_data

# COMMAND ----------

# MAGIC %run ./lib/tools_analysis

# COMMAND ----------

# MAGIC %run ./lib/tools_planning

# COMMAND ----------

# MAGIC %run ./lib/tools_strava_live

# COMMAND ----------

# Merge all tools into one list
coaching_tools = data_tools + analysis_tools + planning_tools + strava_live_tools

print(f"✅ {len(coaching_tools)} coaching tools registered:")
for t in coaching_tools:
    print(f"   • {t.name}")

# COMMAND ----------

# MAGIC %md ## Build the Coaching Agent

# COMMAND ----------

from databricks_langchain import ChatDatabricks
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
import mlflow

# Connect to Databricks Foundation Models API
llm = ChatDatabricks(
    endpoint=LLM_ENDPOINT,
    temperature=0.3,
    max_tokens=1500,
)

# Bind tools directly to the LLM — no langchain.agents needed
llm_with_tools = llm.bind_tools(coaching_tools)

# Tool lookup by name for execution
tool_registry = {t.name: t for t in coaching_tools}

SYSTEM_PROMPT = f"""You are an expert AI cycling coach with deep knowledge of training science, physiology, and competitive cycling. You are coaching athlete_id='{ATHLETE_ID}'.

Your coaching philosophy:
- Data-driven: always look at the numbers before giving advice
- Holistic: consider sleep, stress, and recovery — not just ride data
- Honest: tell the athlete what they need to hear, not just what they want to hear
- Specific: give concrete, actionable guidance — not vague platitudes

How you work:
- Use tools to fetch real data before answering any question about training, fitness, or rides
- Always call get_athlete_profile first in a new conversation to understand who you're coaching
- When analyzing rides, call analyze_last_ride or analyze_activity to get actual metrics
- For planning questions, call suggest_todays_workout or generate_weekly_plan
- For trend questions, call get_power_curve_trend or detect_training_imbalance
- Back every recommendation with data you've fetched

Tool selection guide:
- Fitness/fatigue/form → get_training_load, get_fitness_snapshot
- Recent rides → get_recent_activities
- Last ride feedback → analyze_last_ride
- Specific ride feedback → analyze_activity (needs activity_id)
- Power curve / strengths → get_power_curve, get_power_curve_trend
- Weekly review → get_weekly_summary
- Training balance → detect_training_imbalance
- Repeated route progress → compare_route_performances
- Today's workout → suggest_todays_workout
- This week's plan → generate_weekly_plan
- Saved training plan → get_saved_training_plan
- Route suggestion → suggest_route
- TSS estimation → estimate_ride_tss
- Pacing for a target TSS → plan_ride_pacing

Live Strava data (use when asking about today/this week or data not yet in Delta):
- Fresh recent rides → strava_get_recent_activities
- Full detail on a specific ride → strava_get_activity_detail
- Raw power/HR stream analysis → strava_get_activity_streams
- Lifetime/YTD volume stats → strava_get_athlete_stats

What you never do:
- Give generic cookie-cutter advice
- Ignore recovery signals (sleep, body battery, HRV)
- Recommend intensity when TSB is below -30
- Praise a ride without looking at the data first

Format:
- Be concise but specific — a good coach doesn't ramble
- Lead with the key insight, then support it with the numbers
- Use plain language, not jargon (explain W/kg, TSS etc if the athlete seems unfamiliar)
- End actionable responses with a clear "Next:" recommendation
"""


def run_agent(question: str, chat_history: list = [], verbose: bool = True) -> str:
    """
    Tool-calling agent loop using bind_tools() — no langchain.agents dependency.
    Calls tools until the LLM produces a final text response (no more tool calls).
    """
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + chat_history + [HumanMessage(content=question)]

    for iteration in range(8):  # max 8 tool-call rounds (more tools = may need more)
        response = llm_with_tools.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            # LLM is done — return the final answer
            return response.content

        # Execute each tool call and feed results back
        for tc in response.tool_calls:
            tool_name = tc["name"]
            tool_args = tc["args"]

            if verbose:
                print(f"  → calling {tool_name}({tool_args})")

            if tool_name in tool_registry:
                result = tool_registry[tool_name].invoke(tool_args)
            else:
                result = f"Tool '{tool_name}' not found."

            messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))

    return "Agent reached max iterations without a final response."


print("✅ Coaching agent ready")

# COMMAND ----------

# MAGIC %md ## Log Agent to MLflow

# COMMAND ----------

mlflow.set_experiment("/Shared/ai-cycling-coach")

with mlflow.start_run(run_name="coaching-agent-v2"):
    mlflow.log_params({
        "llm_endpoint": LLM_ENDPOINT,
        "athlete_id": ATHLETE_ID,
        "num_tools": len(coaching_tools),
        "tool_names": str([t.name for t in coaching_tools]),
    })
    mlflow.set_tag("phase", "2-coaching-agent-modular")
    print("✅ Agent logged to MLflow")

# COMMAND ----------

# MAGIC %md ## Chat with Your Coach
# MAGIC
# MAGIC Run the cell below to start a conversation. Change the question and re-run to ask anything.
# MAGIC The agent will automatically call the right tools to get your data.

# COMMAND ----------

# ── ASK YOUR COACH ANYTHING ─────────────────────────────────────────────────
question = "How am I doing? Give me a full overview of where my fitness is at right now."
# ─────────────────────────────────────────────────────────────────────────────

answer = run_agent(question, verbose=True)
print("\n" + "="*60)
print("COACH:")
print("="*60)
print(answer)

# COMMAND ----------

# MAGIC %md ## Multi-turn Conversation (with memory)
# MAGIC
# MAGIC Use this cell for a back-and-forth conversation that remembers context.

# COMMAND ----------

from langchain_core.messages import HumanMessage, AIMessage

chat_history = []


def ask_coach(question: str) -> str:
    """Send a message to the coach and maintain conversation history."""
    answer = run_agent(question, chat_history=chat_history, verbose=False)

    # Update history
    chat_history.append(HumanMessage(content=question))
    chat_history.append(AIMessage(content=answer))

    return answer


def save_conversation_to_delta():
    """Persist the conversation to coach.coaching_conversations for future reference."""
    import uuid
    from datetime import datetime
    from pyspark.sql.types import StructType, StructField, StringType, TimestampType
    from pyspark.sql import SparkSession

    spark = SparkSession.builder.getOrCreate()
    rows = []
    for msg in chat_history:
        rows.append({
            "conversation_id": str(uuid.uuid4()),
            "athlete_id": ATHLETE_ID,
            "ts": datetime.now(),
            "role": "user" if isinstance(msg, HumanMessage) else "coach",
            "content": msg.content,
            "context_json": None,
        })

    schema = StructType([
        StructField("conversation_id", StringType(),    False),
        StructField("athlete_id",      StringType(),    True),
        StructField("ts",              TimestampType(), True),
        StructField("role",            StringType(),    True),
        StructField("content",         StringType(),    True),
        StructField("context_json",    StringType(),    True),
    ])

    df = spark.createDataFrame(rows, schema=schema)
    df.write.format("delta").mode("append").saveAsTable(f"{CATALOG}.coach.coaching_conversations")
    print(f"✅ Saved {len(rows)} messages to coach.coaching_conversations")

# COMMAND ----------

# Example multi-turn conversation — run each ask_coach() call to continue the conversation

response1 = ask_coach("How am I doing overall? Fitness, fatigue, form.")
print("COACH:", response1)

# COMMAND ----------

response2 = ask_coach("How did my last ride go? Give me real feedback.")
print("COACH:", response2)

# COMMAND ----------

response3 = ask_coach("What should I do tomorrow given my current form? Look a little further back in my data - look specifically at rides that were at least an hour. The short ones are just commutes. There should be some zwift rides in the data too")
print("COACH:", response3)

# COMMAND ----------

# Save conversation to Delta for future reference
save_conversation_to_delta()

# COMMAND ----------

# MAGIC %md ## Example Questions to Try
# MAGIC
# MAGIC Copy any of these into `ask_coach()` above:
# MAGIC
# MAGIC **Training load & fitness:**
# MAGIC - "Am I overtraining? My legs feel heavy."
# MAGIC - "How has my fitness changed over the last 8 weeks?"
# MAGIC - "What's my current form and should I race this weekend?"
# MAGIC
# MAGIC **Ride analysis:**
# MAGIC - "Give me detailed feedback on my last ride."
# MAGIC - "Was my heart rate too high on my last long ride?"
# MAGIC - "How did my ride on [date] go?" (agent will look up the activity_id)
# MAGIC
# MAGIC **Planning:**
# MAGIC - "What should I do today?"
# MAGIC - "Generate a training plan for this week."
# MAGIC - "I have 8 hours this week — how should I distribute the training?"
# MAGIC - "I'm racing in 10 days. What should my week look like?"
# MAGIC - "I slept terribly last night. Should I do my intervals today?"
# MAGIC
# MAGIC **Progress & trends:**
# MAGIC - "Is my FTP improving? Show me my power curve trend."
# MAGIC - "Am I training in the right zones? Check for imbalances."
# MAGIC - "Am I getting faster on my usual Zwift routes?"
# MAGIC
# MAGIC **Ride planning:**
# MAGIC - "Suggest a 90-minute hilly route for today."
# MAGIC - "If I ride 75 minutes at 200W, what TSS will I get?"
# MAGIC - "I want 80 TSS in 60 minutes — what power should I target?"
