import streamlit as st
from Home import setup
from pathlib import Path
from utils.mongodb import log_transcript, get_transcript
from anthropic import Anthropic


if not bool(st.session_state.get("user_identifier", "").strip()):
    st.error("Please enter your identifier on the Home page before starting the conversation.")
    st.stop()

MAXIMUM_RESPONSES = 1000

client = setup()

avatar_image_path = " "
TRANSPARENT_AVATAR = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="

st.title("Feedback")

    
with st.chat_message("assistant", avatar=TRANSPARENT_AVATAR):
    initial_prompt = st.session_state["feedback_prompt"]
    patient_transcript_id = (
        st.session_state.get("patient_transcript_id")
        or st.session_state.get("session_id")
    )
    supervisor_transcript_id = (
        st.session_state.get("supervisor_transcript_id")
        or st.session_state.get("session_id")
    )
    if not patient_transcript_id or not supervisor_transcript_id:
        st.error("Missing transcript references. Please complete Patient Interaction and Supervisor Handover first.")
        st.stop()
    patient_interaction_transcript = get_transcript(
        st.session_state["mongodb_uri"],
        st.session_state["mongodb_database_name"],
        "patient_interaction_transcripts",
        patient_transcript_id,
    )
    supervisor_handover_transcript = get_transcript(
        st.session_state["mongodb_uri"],
        st.session_state["mongodb_database_name"],
        "supervisor_handover_transcripts",
        supervisor_transcript_id,
    )

    response = client.messages.create(
        model="claude-sonnet-5",
        system=initial_prompt,
        messages=[
            {"role": "user", "content": "patient interaction transcript: " + str(patient_interaction_transcript)
            + "\n" +
            "supervisor handover transcript: " + str(supervisor_handover_transcript)},
        ],
        max_tokens=st.session_state["max_tokens"]
    )

for block in response.content:
    if block.type == "text":
        st.session_state.feedback_chat_history = block.text
        st.markdown(block.text)

session_id = log_transcript(
                st.session_state["mongodb_uri"],
                "feedback",
                st.session_state.feedback_chat_history,
                "feedback_transcripts"
            )

st.session_state.session_id = session_id