import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
import time
from datetime import datetime, timezone, timedelta

import streamlit as st

from utils.mongodb import get_latest_transcript_since

# "localhost" resolves to the IPv6 loopback (::1) first on many Linux
# containers, including Streamlit Community Cloud - which don't have IPv6
# loopback configured, so uvicorn's bind fails with
# "[Errno 99] cannot assign requested address". Use the IPv4 loopback
# explicitly so this works both locally (Windows) and on Streamlit Cloud.
#
# This host/port is only ever dialed from within this same container: by
# this launcher (to request a Daily room and to send /hangup) and by the bot
# process itself. The student's browser never touches it - it's handed a
# Daily room URL instead, since Streamlit Community Cloud doesn't expose
# subprocess ports to the internet (only Streamlit's own port is proxied).
BOT_HOST = "127.0.0.1"
BOT_SCRIPT = Path(__file__).resolve().parent / "voice_bot.py"
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
APP_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

SESSION_KEY_BOT_PROCESS = "bot_process"
SESSION_KEY_BOT_PORT = "bot_port"
SESSION_KEY_BOT_ROOM_URL = "bot_room_url"
SESSION_KEY_BOT_LOG_PATH = "bot_log_path"
SESSION_KEY_BOT_LOG_FILE = "bot_log_file"
SESSION_KEY_BOT_CONFIG = "bot_config"

VOICE_BOT_STAGES = {
    "patient_interaction": {
        "prompt_path": "prompts/patient_interaction_prompt.txt",
        "transcript_collection": "patient_interaction_transcripts",
        "session_state_key": "patient_transcript_id",
        "voice": "onyx", 
    },
    "supervisor_handover": {
        "prompt_path": "prompts/supervisor_handover_prompt.txt",
        "transcript_collection": "supervisor_handover_transcripts",
        "session_state_key": "supervisor_transcript_id",
        "voice": "alloy", 
    },
}


def initialise_voice_bot_page(PAGE_INIT_KEY) -> None:

    if "supervisor_handover_finished" not in st.session_state:
        st.session_state.supervisor_handover_finished = False
    if "patient_interaction_finished" not in st.session_state:
        st.session_state.patient_interaction_finished = False

    if PAGE_INIT_KEY not in st.session_state.initialised_pages:
        
        st.session_state.initialised_pages.add(PAGE_INIT_KEY)
        st.session_state.conversation_active = False

        # Stop any process left running from a previous page/stage before
        # dropping the reference - otherwise it becomes an orphaned process
        # that keeps consuming CPU and competes with the next bot's startup.
        stop_voice_bot_process()

        st.session_state.handover_timer_started_at = None
        st.session_state.handover_timer_duration_seconds = 130
        st.session_state.handover_started_at_utc = None


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((BOT_HOST, 0))
        return sock.getsockname()[1]


def _current_bot_config() -> dict[str, str]:
    return {
        "identifier": st.session_state.get("user_identifier", ""),
        "model": st.session_state.get("model", ""),
        "mongodb_uri": st.session_state.get("mongodb_uri", ""),
        "mongodb_database_name": st.session_state.get("mongodb_database_name", ""),
    }


def _is_process_running(process) -> bool:
    return process is not None and process.poll() is None


def is_voice_bot_running() -> bool:
    return _is_process_running(st.session_state.get(SESSION_KEY_BOT_PROCESS))


def _terminate_process_tree(process: subprocess.Popen) -> None:
    """Kill a process and any children it spawned.

    Windows' Popen.terminate() is TerminateProcess, which only kills the
    direct process - any child processes it spawned (e.g. aiortc/pipecat
    worker subprocesses) survive and become orphans that keep consuming
    CPU, slowing down and sometimes timing out the next bot's startup.
    `taskkill /T` kills the whole tree; fall back to terminate()/kill() if
    that's unavailable (e.g. non-Windows platforms).
    """
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                timeout=5,
            )
            return
        except (OSError, subprocess.TimeoutExpired):
            pass

    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()


def stop_voice_bot_process() -> None:
    process = st.session_state.get(SESSION_KEY_BOT_PROCESS)
    if _is_process_running(process):
        _terminate_process_tree(process)

    log_file = st.session_state.get(SESSION_KEY_BOT_LOG_FILE)
    if log_file is not None and not log_file.closed:
        log_file.close()

    # Delete the per-session voice client HTML written by
    # streamlit_utils.render_voice_client (filename convention duplicated
    # there - can't import it here without a circular import, since that
    # module imports finish_voice_handover from this one).
    port = st.session_state.get(SESSION_KEY_BOT_PORT)
    if port:
        static_file = APP_STATIC_DIR / f"voice_client_{port}.html"
        static_file.unlink(missing_ok=True)

    st.session_state[SESSION_KEY_BOT_PROCESS] = None
    st.session_state[SESSION_KEY_BOT_PORT] = None
    st.session_state[SESSION_KEY_BOT_ROOM_URL] = None
    st.session_state[SESSION_KEY_BOT_CONFIG] = None
    st.session_state[SESSION_KEY_BOT_LOG_FILE] = None


def request_voice_bot_hangup(port: int | None, timeout_seconds: float = 0.75) -> None:
    if not port:
        return

    url = f"http://{BOT_HOST}:{port}/hangup"
    request = urllib.request.Request(url=url, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds):
            return
    except (urllib.error.URLError, TimeoutError, OSError):
        return


def request_voice_bot_hangup_async(timeout_seconds: float = 0.5) -> threading.Thread:
    port = st.session_state.get(SESSION_KEY_BOT_PORT)
    thread = threading.Thread(
        target=request_voice_bot_hangup,
        kwargs={"port": port, "timeout_seconds": timeout_seconds},
        daemon=True,
    )
    thread.start()
    return thread


def finish_voice_handover(stage: str = "supervisor_handover", trigger: str = "manual") -> None:
    if stage not in VOICE_BOT_STAGES:
        raise ValueError(
            f"Unknown voice bot stage: {stage}. "
            f"Must be one of: {', '.join(VOICE_BOT_STAGES.keys())}"
        )
    
    stage_config = VOICE_BOT_STAGES[stage]
    transcript_collection = stage_config["transcript_collection"]
    session_state_key = stage_config["session_state_key"]
    
    st.session_state.conversation_active = False

    # Wait for the /hangup request to actually land before killing the process.
    # request_voice_bot_hangup_async() only starts a background thread and
    # returns immediately - without joining it here, stop_voice_bot_process()
    # (which force-kills the whole process tree) can win the race and kill the
    # bot before the hangup handler ever runs, so the transcript never saves.
    # The bot pre-warms its MongoDB connection at startup so the actual insert
    # on /hangup is fast, but this timeout still needs enough slack for a cold
    # connect on the rare chance warm-up hadn't finished yet (a bare MongoClient
    # connect + insert to Atlas was measured at ~4.7s).
    hangup_timeout_seconds = 8.0
    hangup_thread = request_voice_bot_hangup_async(timeout_seconds=hangup_timeout_seconds)
    hangup_thread.join(timeout=hangup_timeout_seconds + 2.0)

    stop_voice_bot_process()

    # Determine the start time for this stage
    if stage == "supervisor_handover":
        start_time = st.session_state.get("handover_started_at_utc") or (datetime.now(timezone.utc) - timedelta(minutes=10))
    else:
        start_time = st.session_state.get("patient_interaction_started_at_utc") or (datetime.now(timezone.utc) - timedelta(minutes=10))

    # Give /hangup a brief chance to persist before reading the transcript.
    transcript = None
    for _ in range(8):
        transcript = get_latest_transcript_since(
            st.session_state["mongodb_uri"],
            st.session_state["mongodb_database_name"],
            transcript_collection,
            st.session_state["user_identifier"],
            start_time,
        )
        if transcript is not None:
            break
        time.sleep(0.25)

    if transcript is not None:
        if stage == "supervisor_handover":
            st.session_state.supervisor_handover_chat_history = transcript.get("messages", [])
            st.session_state.supervisor_handover_finished = True
            st.session_state.handover_timer_started_at = None
            st.session_state.handover_started_at_utc = None
        elif stage == "patient_interaction":
            st.session_state.patient_interaction_chat_history = transcript.get("messages", [])
            st.session_state.patient_interaction_finished = True
        
        st.session_state.session_id = str(transcript["_id"])
        st.session_state[session_state_key] = str(transcript["_id"])
    else:
        st.warning(
            "No transcript was saved yet. Make sure you connected and "
            "spoke before finishing."
        )
        if trigger == "timer":
            st.warning("Time limit reached. Conversation was stopped automatically.")


def _start_voice_bot_process(stage: str = "supervisor_handover") -> subprocess.Popen:
    if stage not in VOICE_BOT_STAGES:
        raise ValueError(
            f"Unknown voice bot stage: {stage}. "
            f"Must be one of: {', '.join(VOICE_BOT_STAGES.keys())}"
        )
    
    stage_config = VOICE_BOT_STAGES[stage]
    port = _find_free_port()
    config = _current_bot_config()

    st.session_state[SESSION_KEY_BOT_PORT] = port
    st.session_state[SESSION_KEY_BOT_CONFIG] = config

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"  # stream logs live instead of buffering to the log file
    env["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
    env["OPENAI_API_KEY"] = st.secrets["OPENAI_API_KEY"]
    # Pipecat's Daily transport/runner reads the key from DAILY_API_KEY
    # specifically, regardless of what it's named in secrets.toml.
    env["DAILY_API_KEY"] = st.secrets["DAILY_CO_API_KEY"]
    env["BOT_MODEL"] = config["model"]
    env["BOT_VOICE"] = stage_config["voice"]
    env["PROMPT_PATH"] = stage_config["prompt_path"]
    env["TRANSCRIPT_COLLECTION"] = stage_config["transcript_collection"]
    env["STUDENT_IDENTIFIER"] = config["identifier"]
    env["MONGODB_CONNECTION_STRING"] = config["mongodb_uri"]
    env["MONGODB_DATABASE_NAME"] = config["mongodb_database_name"]

    log_dir = LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"voice_bot_{port}.log"
    st.session_state[SESSION_KEY_BOT_LOG_PATH] = str(log_path)
    log_file = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            str(BOT_SCRIPT),
            "-t",
            "daily",
            "--host",
            BOT_HOST,
            "--port",
            str(port),
        ],
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )

    st.session_state[SESSION_KEY_BOT_PROCESS] = process
    st.session_state[SESSION_KEY_BOT_LOG_FILE] = log_file
    return process


def _raise_unreachable(url: str, last_error: Exception | None) -> None:
    log_path = st.session_state.get(SESSION_KEY_BOT_LOG_PATH)
    log_excerpt = ""
    if log_path:
        try:
            with open(log_path, "r", encoding="utf-8") as log_file:
                lines = log_file.readlines()
            if lines:
                log_excerpt = "".join(lines[-6:]).strip()
        except OSError:
            log_excerpt = ""

    message = f"Voice bot did not become reachable at {url}. Check bot logs at {log_path}."
    if log_excerpt:
        message = f"{message}\nRecent bot log output:\n{log_excerpt}"

    raise RuntimeError(message) from last_error


def _wait_for_voice_bot_ready(port: int, timeout_seconds: int = 45) -> None:
    """Wait for the bot's local FastAPI server to come up.

    Polls /status (always mounted, regardless of transport) rather than
    anything Daily-specific - this only confirms the process/server is alive,
    not that a Daily room has been created yet (that's a separate step, see
    _request_daily_room).
    """
    url = f"http://{BOT_HOST}:{port}/status"
    deadline = time.monotonic() + timeout_seconds
    last_error = None

    while time.monotonic() < deadline:
        process = st.session_state.get(SESSION_KEY_BOT_PROCESS)
        if process is not None and process.poll() is not None:
            break
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            time.sleep(0.25)

    _raise_unreachable(url, last_error)


def _request_daily_room(port: int, timeout_seconds: float = 15.0) -> str:
    """Ask the bot process to create a Daily room and join it, returning the room URL.

    Calls the bot's own /start endpoint (POST, server-to-server over
    localhost) rather than having the browser hit it, since the browser can't
    reach this container's ports on Streamlit Community Cloud. The bot joins
    the room as a background task; the room is created and returned
    synchronously, so the student's browser can be pointed at it immediately
    even if the bot is still connecting.
    """
    url = f"http://{BOT_HOST}:{port}/start"
    payload = json.dumps(
        {
            "transport": "daily",
            "createDailyRoom": True,
            "dailyRoomProperties": {
                # Audio-only roleplay - skip the camera permission prompt and
                # cap the room to the student + bot.
                "start_video_off": True,
                "max_participants": 2,
            },
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        url=url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        _raise_unreachable(url, exc)

    room_url = body.get("dailyRoom")
    if not room_url:
        raise RuntimeError(f"Bot did not return a Daily room URL. Response: {body}")
    return room_url


def ensure_voice_bot_process(stage: str = "supervisor_handover") -> subprocess.Popen:
    process = st.session_state.get(SESSION_KEY_BOT_PROCESS)
    config = _current_bot_config()
    stored_config = st.session_state.get(SESSION_KEY_BOT_CONFIG)

    if _is_process_running(process) and stored_config == config:
        return process

    if _is_process_running(process):
        stop_voice_bot_process()

    process = _start_voice_bot_process(stage=stage)
    try:
        port = st.session_state[SESSION_KEY_BOT_PORT]
        _wait_for_voice_bot_ready(port)
        st.session_state[SESSION_KEY_BOT_ROOM_URL] = _request_daily_room(port)
        return process
    except RuntimeError:
        stop_voice_bot_process()
        raise
