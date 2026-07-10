
import streamlit as st
import time
from datetime import datetime, timezone

from Home import setup
from utils.mongodb import get_latest_transcript_since
from utils.voice_bot_launcher import (
    BOT_HOST,
    ensure_voice_bot_process,
    request_voice_bot_hangup_async,
    stop_voice_bot_process,
    finish_voice_handover,
    initialise_voice_bot_page,
)
from utils.streamlit_utils import render_timer_panel, computer_screen_display

# The voice bot runs as a SEPARATE process (a Pipecat WebRTC server), not inside
# Streamlit. The browser connects to it directly to reach the microphone; this
# page just launches that process and embeds its prebuilt client UI.


client = setup()

PAGE_INIT_KEY = "patient_interaction"
initialise_voice_bot_page(PAGE_INIT_KEY)


# --- Start ---

if not bool(st.session_state.get("user_identifier", "").strip()):
    st.error("Please enter your identifier on the Home page before starting the conversation.")
    st.stop()
elif st.session_state.patient_interaction_finished:
    st.success("Patient assessment completed, proceed to Supervisor Handover page.")
    st.stop()

st.title("Patient Assessment")

# Create Computer display
computer_screen_display("patient_medical_history")



st.markdown(
    "When you click **Start Voice Chat** the bot will take 10-15 seconds to load. The first response "
    "from the bot may be slow, but after that, the conversation should flow. Using your "
    "microphone, conduct your patient assessment with the bot. Click **Finish Conversation** when done."
)

if st.button(
    "Restart Voice Chat" if st.session_state.conversation_active else "Start Voice Chat",
    disabled=st.session_state.patient_interaction_finished,
):
    stop_voice_bot_process()
    try:
        st.session_state.bot_process = ensure_voice_bot_process(stage="patient_interaction")
        st.session_state.conversation_active = True
        st.session_state.patient_interaction_started_at_utc = datetime.now(timezone.utc)
        st.rerun()
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
            "Allow microphone access when prompted, then just speak. "
        )

# --- Finish ---
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    if not st.session_state.patient_interaction_finished and st.session_state.conversation_active:
        if st.button("Finish Conversation", key="finish_patient_interaction", use_container_width=True):
            st.markdown(
                "Finishing the conversation. Please wait until the page says success while the bot processes the transcript."
            )
            finish_voice_handover(stage="patient_interaction", trigger="manual")
            st.rerun()


# if st.session_state.conversation_active:
#     time.sleep(1)
#     st.rerun()
