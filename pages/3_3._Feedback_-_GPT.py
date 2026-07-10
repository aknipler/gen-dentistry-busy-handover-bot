import streamlit as st
from Home import setup
from pathlib import Path
from utils.mongodb import log_transcript, get_transcript
from anthropic import Anthropic



if not bool(st.session_state.get("user_identifier", "").strip()):
    st.error("Please enter your identifier on the Home page before starting the conversation.")
    st.stop()
elif not st.session_state.supervisor_handover_finished and not st.session_state.patient_interaction_finished:
    st.error("Please complete the Patient Interaction AND the Supervisor handover first.")
    st.stop()


MAXIMUM_RESPONSES = 1000

client = setup()

avatar_image_path = " "
TRANSPARENT_AVATAR = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="

# st.session_state.feedback_chat_history = None
if st.session_state.feedback_chat_history is None or len(st.session_state.feedback_chat_history) == 0:
    st.title("Generating feedback...")

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

        # The feedback prompt asks for a 7-section written review (summary, SBAR
        # breakdown, communication, information gathering, strengths, improvements,
        # safety note) - that routinely runs well past a couple thousand tokens.
        # Use a generous, dedicated budget for this long-form report rather than
        # the smaller value used elsewhere, and surface it clearly if the model
        # still hits the limit so a truncated report is never silently mistaken
        # for a complete one.
        FEEDBACK_MAX_TOKENS = 6144

        response = client.messages.create(
            model="claude-sonnet-5",
            system=initial_prompt,
            messages=[
                {"role": "user", "content": "patient interaction transcript: " + str(patient_interaction_transcript)
                + "\n" +
                "supervisor handover transcript: " + str(supervisor_handover_transcript)},
            ],
            max_tokens=FEEDBACK_MAX_TOKENS
        )

        if response.stop_reason == "max_tokens":
            st.warning(
                "The feedback response was cut off because it reached the model's "
                "token limit. Consider increasing FEEDBACK_MAX_TOKENS further."
            )

        for block in response.content:
            if block.type == "text":
                st.session_state.feedback_chat_history = block.text

                # Use a dedicated key rather than the shared "session_id" -
                # patient_transcript_id/supervisor_transcript_id above fall back
                # to session_id, so overwriting it here would break that
                # fallback if this page reruns before those keys are read again.
                st.session_state.feedback_transcript_id = log_transcript(
                    st.session_state["mongodb_uri"],
                    "feedback",
                    st.session_state.feedback_chat_history,
                    "feedback_transcripts"
                )

    # Only rerun once, now that generation is done, so the page redraws showing
    # the saved feedback via the branch below instead of regenerating again.
    st.rerun()
else:
    st.markdown(st.session_state.feedback_chat_history)