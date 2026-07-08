import streamlit as st
from Home import setup
from pathlib import Path
from utils.mongodb import log_transcript
from anthropic import Anthropic


if not bool(st.session_state.get("user_identifier", "").strip()):
    st.error("Please enter your identifier on the Home page before starting the conversation.")
    st.stop()

MAXIMUM_RESPONSES = 1000

client = setup()
avatar_image_path = None
# avatar_image_path = Path(__file__).parent / "images" / "Patient Icon.png"

st.title("Patient Assessment")

screen_css = """
<style>
    /* 1. Target ONLY the top-level block holding your unique key wrapper */
    .st-key-computer_screen {
        background-color: #2b2b2b !important;
        padding: 24px !important;
        border-radius: 25px !important;
        box-shadow: 0 15px 30px rgba(0,0,0,0.7), inset 0 0 15px rgba(0,0,0,0.6) !important;
        max-width: 800px;
        margin: 20px auto !important;
        position: relative;
    }
    
    /* 2. Target ONLY the inner direct scrollable block of this specific container */
    .st-key-computer_screen > div[data-testid="stContainerBlock"] {
        background-color: #121212 !important;
        border: 14px solid #1a1a1a !important; /* Thick screen bezel */
        border-radius: 12px !important;
        box-shadow: inset 0 0 20px rgba(0,255,0,0.03) !important;
        padding: 15px !important;
    }

    /* 3. Drop the glossy reflection layer safely over just this container monitor */
    .st-key-computer_screen::before {
        content: "";
        position: absolute;
        top: 24px;
        left: 24px;
        right: 24px;
        height: 35%;
        background: linear-gradient(rgba(255,255,255,0.06), transparent);
        pointer-events: none;
        z-index: 10;
        border-radius: 4px 4px 0 0;
    }

    /* Target regular text, headers, and markdown inside the container */
    .st-key-computer_screen [data-testid="stMarkdownContainer"] p,
    .st-key-computer_screen [data-testid="stMarkdownContainer"] h1,
    .st-key-computer_screen [data-testid="stMarkdownContainer"] h2,
    .st-key-computer_screen [data-testid="stMarkdownContainer"] h3,
    .st-key-computer_screen [data-testid="stMarkdownContainer"] li {
        color: #ffffff !important;
    }

    /* Target plain text blocks (st.text) */
    .st-key-computer_screen pre {
        color: #ffffff !important;
        background-color: #1a1a1a !important;
        border-color: #333333 !important;
    }

    /* Target code snippets (st.code) background to match terminal aesthetics */
    .st-key-computer_screen code {
        color: #ffffff !important;
        background-color: #1e1e1e !important;
    }
</style>
"""
# 2. Inject global application style layout rules
st.html(screen_css)

# 3. Instantiate the standard Streamlit container layout component
with st.container(height=380, border=True, key="computer_screen"):
    st.markdown("## 🖥️ Patient Medical History Database")
    st.write(str(st.session_state.get("patient_medical_history", "No medical history provided.")))




st.markdown(
    "Start Patient Assessment by clicking the 'Start Voice Chat' button below."
)

# Bot initiates the conversation
if not st.session_state.patient_interaction_chat_history:
    
    with st.chat_message("assistant", avatar=avatar_image_path):
        initial_prompt = st.session_state["patient_interaction_prompt"]

        response = client.messages.create(
            max_tokens=st.session_state["max_tokens"],
            model=st.session_state["model"],
            system=initial_prompt,
            messages=[{"role": "user", "content": "Ignore this initial message. Start the conversation."}]
        )

        message = {"content": response.content[0].text, "role": "assistant"}
        st.session_state.patient_interaction_chat_history.append(message)
        st.markdown(message["content"])


else:
    # Write chat history
    for message in st.session_state.patient_interaction_chat_history:

        if message["role"]=='assistant': avatar=avatar_image_path
        else: avatar=None

        with st.chat_message(message["role"], avatar=avatar):
            st.markdown(message["content"])

# Chat logic
if prompt := st.chat_input(
    "Write a response here",
    disabled=st.session_state.patient_interaction_finished or st.session_state.response_counter >= MAXIMUM_RESPONSES
):

    st.session_state.patient_interaction_chat_history.append({"role": "user", "content": prompt})

    if st.session_state.response_counter < MAXIMUM_RESPONSES:
    
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant", avatar=avatar_image_path):

            response = client.messages.create(
                max_tokens=st.session_state["max_tokens"],
                model=st.session_state["model"],
                system=st.session_state["patient_interaction_prompt"],
                messages=st.session_state.patient_interaction_chat_history
            )
            st.markdown(response.content[0].text)

        st.session_state.response_counter += 1
        st.session_state.patient_interaction_chat_history.append({"role": "assistant", "content": str(response)})

    else:
        with st.chat_message("user"):
            st.markdown(prompt)
        
        with st.chat_message("assistant", avatar=avatar_image_path):
            message = "Well done, I hope I was of assistance."
            st.markdown(message)
        
        final_message = {"role": "assistant", "content": message}
        st.session_state.patient_interaction_chat_history.append(final_message)
        st.session_state.patient_interaction_finished = True

# Add finish conversation button below chat input
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    if not st.session_state.patient_interaction_finished and st.session_state.patient_interaction_chat_history:
        if st.button("Finish Conversation", key="finish_patient_interaction", use_container_width=True):
            st.session_state.patient_interaction_finished = True
            session_id = log_transcript(
                st.session_state["mongodb_uri"],
                "patient_interaction",
                st.session_state.patient_interaction_chat_history,
                "patient_interaction_transcripts"
            )
            st.session_state.session_id = session_id
            st.rerun()