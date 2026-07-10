import streamlit as st
import time
from datetime import datetime, timezone

from Home import setup
from utils.mongodb import get_latest_transcript_since
from utils.voice_bot_launcher import (
    ensure_voice_bot_process,
    request_voice_bot_hangup_async,
    stop_voice_bot_process,
    finish_voice_handover,
    initialise_voice_bot_page,
)
from utils.streamlit_utils import render_timer_panel

# The voice bot runs as a SEPARATE process (a Pipecat + Daily server), not
# inside Streamlit. This page launches that process, has it create a Daily
# room, and embeds that room's URL - the student's browser connects to Daily
# directly (never to this container) to reach the microphone.


client = setup()

PAGE_INIT_KEY = "supervisor_handover"
initialise_voice_bot_page(PAGE_INIT_KEY)


if not bool(st.session_state.get("user_identifier", "").strip()):
    st.error("Please enter your identifier on the Home page before starting the conversation.")
    st.stop()
elif not st.session_state.patient_interaction_finished:
    st.error("Please complete the Patient Interaction first.")
    st.stop()
elif st.session_state.supervisor_handover_finished:
    st.success("Supervisor handover completed, proceed to Feedback page.")
    st.stop()





# --- Start ---
st.title("Supervisor Handover")

if st.button(
    "Restart Voice Chat" if st.session_state.conversation_active else "Start Voice Chat",
    disabled=st.session_state.supervisor_handover_finished,
):
    stop_voice_bot_process()
    try:
        st.session_state.bot_process = ensure_voice_bot_process(stage="supervisor_handover")
        st.session_state.conversation_active = True
        st.session_state.handover_timer_started_at = time.time()
        st.session_state.handover_started_at_utc = datetime.now(timezone.utc)
        st.rerun()
    except RuntimeError as exc:
        st.error(str(exc))
        st.session_state.conversation_active = False

# if (
#     st.session_state.conversation_active
#     and st.session_state.handover_timer_started_at is not None
#     and (time.time() - st.session_state.handover_timer_started_at)
#     >= st.session_state.handover_timer_duration_seconds
# ):
#     finish_voice_handover(stage="supervisor_handover", trigger="timer")
#     st.rerun()

co1, co2 = st.columns([3, 1])
with co1:
    st.markdown(
        "This conversation is timed. When you click **Start Voice Chat** the timer will begin. Using your "
        "microphone, conduct your handover with the bot. Click **Finish Conversation** when done."
    )
with co2:
    render_timer_panel()

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
        st.iframe(st.session_state.bot_room_url, height=500)
        st.caption(
            "Allow microphone access when prompted, then just speak. The timer will start when you press start Voice Chat. "
        )

# --- Finish ---
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    if not st.session_state.supervisor_handover_finished and st.session_state.conversation_active:
        if st.button("Finish Conversation", key="finish_supervisor_handover", use_container_width=True):
            finish_voice_handover(stage="supervisor_handover", trigger="manual")
            st.rerun()

if st.session_state.supervisor_handover_finished:
    st.success("Handover completed, proceed to Feedback page.")

if st.session_state.conversation_active:
    time.sleep(1)
    st.rerun()
