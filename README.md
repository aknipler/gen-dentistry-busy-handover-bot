# Rapid Handover to a Busy Clinical Supervisor

Note: This project won't work locally on a Windows machine because of the pipecat[daily] requirement. It works fine on Linux and Mac, and on Streamlit Community Cloud.

A Streamlit teaching activity for dental students. Students play a clinician
who must interview a simulated patient, then hand the case over to a busy
supervisor voice bot under time pressure, and finally receive AI-generated
written feedback on their performance.

The activity has three linear stages, each its own Streamlit page:

1. **Patient Interaction** — the student interviews a simulated patient
   (voice conversation) to gather any information not already in the chart.
2. **Supervisor Handover** — the student gives a timed, spoken handover (SBAR
   style) to a simulated supervisor and answers follow-up questions.
3. **Feedback** — Claude reviews both transcripts and produces a structured,
   educational written report (summary, SBAR review, communication under
   pressure, strengths/improvements, clinical safety notes).

Students can only reach a stage once the previous one is marked finished
(`patient_interaction_finished` / `supervisor_handover_finished` in session
state), and every transcript is stored in MongoDB keyed by the student's
identifier so it can be reviewed later.


## Project structure

```
Home.py                              # Landing page: identifier entry, session_state setup()
pages/
├── 1_1._Patient_Interaction_-_GPT.py # Stage 1: voice bot, patient interview
├── 2_2._Supervisor_Handover_-_GPT.py # Stage 2: voice bot, timed handover
└── 3_3._Feedback_-_GPT.py           # Stage 3: Claude-generated written feedback
utils/
├── voice_bot.py                     # The Pipecat bot itself (runs as its own process)
├── voice_bot_launcher.py            # Starts/stops/monitors the bot process from Streamlit
├── streamlit_utils.py               # Shared UI helpers (timer panel, patient chart display)
└── mongodb.py                       # Transcript + identifier persistence
prompts/
├── patient_interaction_prompt.txt   # Patient roleplay system prompt
├── patient_medical_history.txt      # Patient chart shown to the student
├── supervisor_handover_prompt.txt   # Supervisor roleplay system prompt
└── feedback_prompt.txt              # Feedback report structure/instructions
scripts/
├── generate_and_load_identifiers.py # Create + upload student identifiers
├── load_identifiers.py              # Upload an existing identifier CSV
├── create_index.py                  # MongoDB index setup
└── measure_latency.sh               # Ad-hoc voice bot latency measurement
logs/                                 # Per-process voice bot logs (gitignored)
```

## Setup

### 1. Environment

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Requires Python with access to a microphone-capable browser for testing.
Voice bots connect the student's browser to a Daily room (see Secrets below);
this is what makes them reachable when hosted on Streamlit Community Cloud,
which does not expose subprocess ports to the internet.

### 2. Secrets

Create `.streamlit/secrets.toml`:

```toml
ANTHROPIC_API_KEY = "your_anthropic_api_key"
OPENAI_API_KEY = "your_openai_api_key"
DAILY_CO_API_KEY = "your_daily_co_api_key"
MONGODB_CONNECTION_STRING = "your_mongodb_connection_string"
MONGODB_DATABASE_NAME = "your_database_name"
```

- **Anthropic** powers both the patient/supervisor bots (Claude) and the
  feedback generation.
- **OpenAI** powers realtime speech-to-text and text-to-speech for the voice
  bots.
- **Daily** hosts the WebRTC room each voice bot session connects the
  student's browser and the bot to (get a key at
  [dashboard.daily.co](https://dashboard.daily.co)).
- **MongoDB** stores valid student identifiers and every stage's transcript.

### 3. Student identifiers

Create a CSV with student information (e.g. `students.csv`):

```csv
order_id,
0,
1,
2,
```

Generate identifiers and load them into MongoDB:

```powershell
python scripts/generate_and_load_identifiers.py
```

Gives:

```csv
order_id, unique_id
0, EXAMPLE-DLVNEI
1, EXAMPLE-ABC123
2, EXAMPLE-XYZ789
```

This creates unique identifiers, saves a mapping CSV locally 
and uploads only the identifiers themselves to the `valid_identifiers`
collection in MongoDB.

### 4. Running the app

```powershell
streamlit run Home.py
```

Open the app, enter a valid identifier on the Home page, then proceed through
the three stages in order.

## Troubleshooting

- **Transcript not saving / can't progress to the next stage** — the
  transcript is written by the bot process on `/hangup`, then read back by
  `finish_voice_handover()` filtering on a start timestamp. If MongoDB is
  slow to connect (e.g. a cold Atlas connection), the bot warms up its
  MongoDB connection at startup precisely to avoid this; check the relevant
  `logs/voice_bot_<port>.log` for "Saved transcript" or connection errors.
- **Feedback looks truncated** — check for a "cut off because it reached the
  model's token limit" warning on the Feedback page; increase
  `FEEDBACK_MAX_TOKENS` in `pages/3_3._Feedback_-_GPT.py` if needed.

## Security considerations

- Never commit `.env`, `.streamlit/secrets.toml`, or any CSV containing
  student-identifier mappings.
- Only opaque identifiers (no personal information) are stored in MongoDB.
- Regular database backups are recommended.
