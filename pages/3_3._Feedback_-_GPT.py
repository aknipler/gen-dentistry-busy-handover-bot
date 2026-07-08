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
# avatar_image_path = Path(__file__).parent / "images" / "Supervisor Icon.png"

st.title("Feedback")


# st.markdown(
#     "## Feedback on patient interaction"
# )
    
with st.chat_message("assistant", avatar=TRANSPARENT_AVATAR):
    initial_prompt = st.session_state["feedback_prompt"]
    patient_interaction_transcript = get_transcript(st.session_state["mongodb_uri"], st.session_state["mongodb_database_name"], "patient_interaction_transcripts", st.session_state.session_id)
    supervisor_handover_transcript = get_transcript(st.session_state["mongodb_uri"], st.session_state["mongodb_database_name"], "supervisor_handover_transcripts", st.session_state.session_id)

    response = client.chat.completions.create(
        model=st.session_state["model"],
        messages=[
            {"role": "system", "content": initial_prompt},
            {"role": "system", "content": "patient interaction transcript: " + str(patient_interaction_transcript)},
            {"role": "system", "content": "supervisor handover transcript: " + str(supervisor_handover_transcript)},
        ]
    )

message = {"content": response.choices[0].message.content, "role": "assistant"}
st.session_state.feedback_chat_history.append(message)
st.markdown(message["content"])

session_id = log_transcript(
                st.session_state["mongodb_uri"],
                "feedback",
                st.session_state.feedback_chat_history,
                "feedback_transcripts"
            )
st.session_state.session_id = session_id
# st.rerun()

# st.markdown(
#     "## Feedback on supervisor handover"
# )
    
# with st.chat_message("assistant", avatar=avatar_image_path):
#     initial_prompt = st.session_state["feedback_prompt"]
#     supervisor_handover_transcript = st.database.get_collection("supervisor_handover_transcripts").find_one({"_id": st.session_state.session_id})

#     response = client.chat.completions.create(
#         model=st.session_state["model"],
#         messages=[
#             {"role": "system", "content": initial_prompt},
#             {"role": "system", "content": supervisor_handover_transcript},
#         ]
#     )

#     message = {"content": response.choices[0].message.content, "role": "assistant"}
#     st.session_state.feedback_chat_history.append(message)
#     st.markdown(message["content"])

