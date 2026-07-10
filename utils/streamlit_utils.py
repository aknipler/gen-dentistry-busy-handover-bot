import json
import time
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from utils.voice_bot_launcher import finish_voice_handover

DAILY_CLIENT_TEMPLATE_PATH = Path(__file__).resolve().parent / "daily_client_template.html"


def render_voice_client(room_url: str, height: int = 240) -> None:
    """Embed a minimal, custom voice-call UI for the given Daily room.

    Embedding the raw Daily room URL in an iframe pulls in Daily's full
    prebuilt UI (video tiles, chat, participant list, camera/mic controls),
    which is a lot of clutter for a bot that's audio-only. This instead
    injects the room URL into a small HTML/JS page (see
    utils/daily_client_template.html) that joins the room headlessly via the
    Daily JS SDK and renders just a waveform + status line, matching the
    minimal client the app used before moving to Daily.
    """
    template = DAILY_CLIENT_TEMPLATE_PATH.read_text(encoding="utf-8")
    html = template.replace("__ROOM_URL_JSON__", json.dumps(room_url))
    st.iframe(html, height=height)


def render_timer_panel() -> None:
    if st.session_state.supervisor_handover_finished:
        st.markdown("#### Completed")
        return

    if st.session_state.handover_timer_started_at is None:
        st.markdown(f"### ⏱️ {st.session_state.handover_timer_duration_seconds} seconds")
        return

    elapsed = time.time() - st.session_state.handover_timer_started_at
    remaining = max(0, int(st.session_state.handover_timer_duration_seconds - elapsed))
    st.markdown(f"### ⏱️ {remaining} seconds")

    if st.session_state.conversation_active and remaining <= 0:
        finish_voice_handover(stage="supervisor_handover", trigger="timer")
        st.rerun()


def computer_screen_display(content_key: str) -> None:
    
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
        st.write(str(st.session_state.get(content_key, "No medical history provided.")))
