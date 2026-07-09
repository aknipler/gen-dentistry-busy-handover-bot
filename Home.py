import streamlit as st
from anthropic import Anthropic
from utils.mongodb import check_identifier
from utils.voice_bot_launcher import ensure_voice_bot_process, is_voice_bot_running

def is_identifier_valid():
    identifier = st.session_state.get("user_identifier", "").strip()
    if not identifier:
        return False
    return check_identifier(st.session_state["mongodb_uri"], identifier)

def setup():

    if "patient_interaction_prompt" not in st.session_state: 
        with open("./prompts/patient_interaction_prompt.txt", "r", encoding="utf-8") as file:
            patient_interaction_prompt = file.read()

        st.session_state["patient_interaction_prompt"] = patient_interaction_prompt
        
    if "supervisor_handover_prompt" not in st.session_state: 
        with open("./prompts/supervisor_handover_prompt.txt", "r", encoding="utf-8") as file:
            supervisor_handover_prompt = file.read()

        st.session_state["supervisor_handover_prompt"] = supervisor_handover_prompt
        
    if "feedback_prompt" not in st.session_state: 
        with open("./prompts/feedback_prompt.txt", "r", encoding="utf-8") as file:
            feedback_prompt = file.read()

        st.session_state["feedback_prompt"] = feedback_prompt

    if "patient_medical_history" not in st.session_state:
        with open("./prompts/patient_medical_history.txt", "r", encoding="utf-8") as file:
            patient_medical_history = file.read()

        st.session_state["patient_medical_history"] = patient_medical_history

    if "model" not in st.session_state:
        st.session_state["model"] = "claude-haiku-4-5"
        
    if "max_tokens" not in st.session_state:
        st.session_state["max_tokens"] = 1024

    if "patient_interaction_chat_history" not in st.session_state:
        st.session_state["patient_interaction_chat_history"] = []
        
    if "supervisor_handover_chat_history" not in st.session_state:
        st.session_state["supervisor_handover_chat_history"] = []
        
    if "feedback_chat_history" not in st.session_state:
        st.session_state["feedback_chat_history"] = []

    if "response_counter" not in st.session_state:
        st.session_state["response_counter"] = 0

    if "mongodb_uri" not in st.session_state:
        st.session_state["mongodb_uri"] = st.secrets["MONGODB_CONNECTION_STRING"]

    if "mongodb_database_name" not in st.session_state:
        st.session_state["mongodb_database_name"] = st.secrets["MONGODB_DATABASE_NAME"]

    if "patient_interaction_finished" not in st.session_state:
        st.session_state["patient_interaction_finished"] = False

    if "supervisor_handover_finished" not in st.session_state:
        st.session_state["supervisor_handover_finished"] = False

    if "session_id" not in st.session_state:
        st.session_state["session_id"] = None

    if "patient_transcript_id" not in st.session_state:
        st.session_state["patient_transcript_id"] = None

    if "supervisor_transcript_id" not in st.session_state:
        st.session_state["supervisor_transcript_id"] = None

    if "user_identifier" not in st.session_state:
        st.session_state["user_identifier"] = ""

    if "initialised_pages" not in st.session_state:
        st.session_state["initialised_pages"] = set()

    # Set up Anthropic API client
    client = Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])

    return client

def init_page():
    setup()
    # if "home_prewarm_started" not in st.session_state:
    #     st.session_state["home_prewarm_started"] = False

    # if (not st.session_state["home_prewarm_started"]) or (not is_voice_bot_running()):
    #     try:
    #         st.session_state["bot_process"] = ensure_voice_bot_process()
    #         st.session_state["home_prewarm_started"] = True
    #     except RuntimeError as exc:
    #         st.warning(str(exc))
    #         st.session_state["home_prewarm_started"] = False

    st.title("Rapid Handover to Busy Clinical Supervisor")
    st.markdown(
    """
    You are a student clinician in a busy Dental Teaching Clinic. You are seeing a patient who previously had a comprehensive examination with another student clinician. You must assess your patient and communicate relevant information to your clinical supervisor, to get approval to commence treatment.
    The clinic is running behind schedule, and your supervisor is assisting several other students. You will have a limited opportunity to provide a briefing before the supervisor moves on to another patient.
    This activity is designed to help you practise gathering relevant information, identifying key clinical issues, and delivering a clear and concise handover under realistic time pressures.
    """
    )


    st.markdown(
    """
    ## Your Task
    -	Review the available patient information.
    -	Conduct a patient interview to gather any additional information required.
    -	Prepare a brief handover for your clinical supervisor.
    -	Communicate any relevant findings, concerns, and management considerations.
    -	Respond to any questions from the supervisor.
    """
    )
    
    st.markdown(
    """
    ## Success Criteria

    You will receive feedback assessed on your ability to:
    -	Communicate effectively with the patient.
    -	Gather and interpret relevant information.
    -	Identify and prioritise important clinical findings.
    -	Deliver a clear and concise handover.
    -	Communicate professionally under time pressure.
    -	Respond appropriately to supervisor questions.
    """)
    st.markdown(
        "## Instructions\n"
        "1. Enter your unique identifier below. This will be used to associate your conversation records with you.\n"
        "2. In the Patient Interaction - GPT tab, conduct a patient assessment. Only when you are finished the conversation click the `finish` button. You will not be able to undo this submission.\n"
        "3. In the Supervisor Handover - GPT tab, complete the patient handover within the time limit provided.\n"
        "4. In the Feedback - GPT tab, review your performance. If you have any additional questions about your feedback or performance, please contact your supervisor.\n"
        "\nNote: Please ensure you have a stable internet connection to prevent any issues from occurring."
    )

    # Add identifier input after welcome message
    identifier = st.text_input(
        "Please enter your unique identifier:",
        key="identifier_input",
        value=st.session_state.get("user_identifier", ""),
        help="This identifier will be stored with your conversation records"
    )

    if identifier:
        if check_identifier(st.session_state["mongodb_uri"], identifier):
            st.session_state["user_identifier"] = identifier
            st.success("✅ Identifier validated successfully. You can now proceed to the conversation page.")
        else:
            st.error("❌ Invalid identifier. Please enter a valid identifier.")
            st.session_state["user_identifier"] = ""
    else:
        st.warning("⚠️ Please enter your identifier before starting any conversations.")

    # if is_voice_bot_running():
    #     st.caption("TEST: Voice models are preparing in the background.")

if __name__ == "__main__":
    init_page()
