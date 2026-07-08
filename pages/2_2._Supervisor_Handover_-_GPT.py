import streamlit as st

from Home import setup
from utils.mongodb import get_latest_transcript
from utils.voice_bot_launcher import (
    BOT_HOST,
    ensure_voice_bot_process,
    is_voice_bot_running,
    stop_voice_bot_process,
)

# The voice bot runs as a SEPARATE process (a Pipecat WebRTC server), not inside
# Streamlit. The browser connects to it directly to reach the microphone; this
# page just launches that process and embeds its prebuilt client UI.


if not bool(st.session_state.get("user_identifier", "").strip()):
    st.error("Please enter your identifier on the Home page before starting the conversation.")
    st.stop()

client = setup()

if "conversation_active" not in st.session_state:
    st.session_state.conversation_active = False
if "bot_process" not in st.session_state:
    st.session_state.bot_process = None
if "bot_port" not in st.session_state:
    st.session_state.bot_port = None

st.title("Supervisor Handover")

st.markdown(
    "Click **Start Voice Chat**, then use the panel below to connect your "
    "microphone and speak your handover. Click **Finish Conversation** when done."
)

# --- Start ---
if st.button(
    "Start Voice Chat",
    disabled=st.session_state.supervisor_handover_finished or st.session_state.conversation_active,
):
    stop_voice_bot_process()
    try:
        st.session_state.bot_process = ensure_voice_bot_process()
        st.session_state.conversation_active = True
        st.success("Bot starting... give it a few seconds, then connect below.")
    except RuntimeError as exc:
        st.error(str(exc))
        st.session_state.conversation_active = False

# --- Embedded voice client ---
if st.session_state.conversation_active:
    process = st.session_state.get("bot_process")
    if process is not None and process.poll() is not None:
        st.error(
            "The voice bot process exited unexpectedly. Please click "
            "**Start Voice Chat** again."
        )
        st.session_state.conversation_active = False
    else:
        client_url = f"http://{BOT_HOST}:{st.session_state.bot_port}/simple"
        st.iframe(client_url, height=240)
        st.caption(
            "Allow microphone access when prompted, then just speak. The timer will start when you press start Voice Chat. "
        )

# --- Finish ---
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    if not st.session_state.supervisor_handover_finished and st.session_state.conversation_active:
        if st.button("Finish Conversation", key="finish_supervisor_handover", use_container_width=True):
            stop_voice_bot_process()

            # The bot writes the transcript to MongoDB on hangup; read it back so
            # the feedback stage can pick it up.
            transcript = get_latest_transcript(
                st.session_state["mongodb_uri"],
                st.session_state["mongodb_database_name"],
                "supervisor_handover_transcripts",
                st.session_state["user_identifier"],
            )

            if transcript is not None:
                st.session_state.supervisor_handover_chat_history = transcript.get("messages", [])
                st.session_state.session_id = str(transcript["_id"])
                st.session_state.supervisor_handover_finished = True
                st.rerun()
            else:
                st.warning(
                    "No transcript was saved yet. Make sure you connected and "
                    "spoke before finishing."
                )
