import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import streamlit as st

BOT_HOST = "localhost"
BOT_SCRIPT = Path(__file__).resolve().parent / "voice_bot.py"
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"

SESSION_KEY_BOT_PROCESS = "bot_process"
SESSION_KEY_BOT_PORT = "bot_port"
SESSION_KEY_BOT_LOG_PATH = "bot_log_path"
SESSION_KEY_BOT_LOG_FILE = "bot_log_file"
SESSION_KEY_BOT_CONFIG = "bot_config"


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


def stop_voice_bot_process() -> None:
    process = st.session_state.get(SESSION_KEY_BOT_PROCESS)
    if _is_process_running(process):
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()

    log_file = st.session_state.get(SESSION_KEY_BOT_LOG_FILE)
    if log_file is not None and not log_file.closed:
        log_file.close()

    st.session_state[SESSION_KEY_BOT_PROCESS] = None
    st.session_state[SESSION_KEY_BOT_PORT] = None
    st.session_state[SESSION_KEY_BOT_CONFIG] = None
    st.session_state[SESSION_KEY_BOT_LOG_FILE] = None


def _start_voice_bot_process() -> subprocess.Popen:
    port = _find_free_port()
    config = _current_bot_config()

    st.session_state[SESSION_KEY_BOT_PORT] = port
    st.session_state[SESSION_KEY_BOT_CONFIG] = config

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
    env["BOT_MODEL"] = config["model"]
    env["PROMPT_PATH"] = "prompts/supervisor_handover_prompt.txt"
    env["TRANSCRIPT_COLLECTION"] = "supervisor_handover_transcripts"
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
            "webrtc",
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


def _wait_for_voice_bot_ready(port: int, timeout_seconds: int = 20) -> None:
    url = f"http://{BOT_HOST}:{port}/simple"
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
        except urllib.error.URLError as exc:
            last_error = exc
            time.sleep(0.25)

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

    raise RuntimeError(
        message
    ) from last_error


def ensure_voice_bot_process() -> subprocess.Popen:
    process = st.session_state.get(SESSION_KEY_BOT_PROCESS)
    config = _current_bot_config()
    stored_config = st.session_state.get(SESSION_KEY_BOT_CONFIG)

    if _is_process_running(process) and stored_config == config:
        return process

    if _is_process_running(process):
        stop_voice_bot_process()

    process = _start_voice_bot_process()
    try:
        _wait_for_voice_bot_ready(st.session_state[SESSION_KEY_BOT_PORT])
        return process
    except RuntimeError:
        stop_voice_bot_process()
        raise
