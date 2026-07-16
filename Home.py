import streamlit as st
from anthropic import Anthropic
from utils.mongodb import check_identifier
from utils.voice_bot_launcher import ensure_voice_bot_process, is_voice_bot_running
from utils.streamlit_utils import initialise_streamlit_session_state

def is_identifier_valid():
    identifier = st.session_state.get("user_identifier", "").strip()
    if not identifier:
        return False
    return check_identifier(st.session_state["mongodb_uri"], identifier)

def setup():

    # Initialize Streamlit session state variables (there are a lot!)
    initialise_streamlit_session_state()

    # Set up Anthropic API client
    client = Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])

    return client

def init_page():
    setup()
    
    st.title("Rapid Handover to Busy Clinical Supervisor")
    st.markdown(
    """
    You are a student clinician in a busy Dental Teaching Clinic. You are seeing a patient who previously had a comprehensive examination with another student clinician. You must assess your patient and communicate relevant information to your clinical supervisor, to get approval to commence treatment.
    The clinic is running behind schedule, and your supervisor is assisting several other students. You will have a limited opportunity to provide a briefing before the supervisor moves on to another patient.
    This activity is designed to help you practise gathering relevant information, identifying key clinical issues, and delivering a clear and concise handover under realistic time pressures. \n
    **Disclaimer: This is experimental and may not work perfectly, so apply your clinical judgement and common sense to the interactions and feedback. If you have any questions or concerns, please contact your supervisor.**
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
        "\n**Note: Please ensure you have a stable internet connection, a quiet environment and a suitable microphone to prevent any issues from occurring.**"
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
            st.success("✅ Identifier validated successfully. You can now proceed to the Patient Interaction page.")
        else:
            st.error("❌ Invalid identifier. Please enter a valid identifier.")
            st.session_state["user_identifier"] = ""
    else:
        st.warning("⚠️ Please enter your identifier before starting any conversations.")

    # if is_voice_bot_running():
    #     st.caption("TEST: Voice models are preparing in the background.")

if __name__ == "__main__":
    init_page()
