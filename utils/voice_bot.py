"""Generic Pipecat voice bot, reused across roleplay stages.

This runs as its own process (a FastAPI + SmallWebRTC server), rather than inside
Streamlit. The student's browser connects to it directly over WebRTC, which is
the only way to reach the microphone. Streamlit (see utils/voice_session.py)
launches this process per stage and embeds a minimal client UI (served at
http://<host>:<port>/simple).

This script has no stage-specific knowledge (no "supervisor" or "patient"
wording) - which prompt to use, which Mongo collection to save to, and who the
student is all come from environment variables, so the same script serves
every voice roleplay stage:

    ANTHROPIC_API_KEY          - required, Claude API key
    BOT_MODEL                  - Claude model id (default: claude-haiku-4-5)
    PROMPT_PATH                - path to the system prompt file for this stage
    TRANSCRIPT_COLLECTION      - Mongo collection to save the transcript into
    STUDENT_IDENTIFIER         - student id, stored with the transcript
    MONGODB_CONNECTION_STRING  - if set, the transcript is saved on hangup
    MONGODB_DATABASE_NAME      - database to write the transcript into

Pipeline: WebRTC in -> Whisper STT (local) -> Claude -> Kokoro TTS -> WebRTC out.
Turn-taking uses Silero VAD + Smart Turn v3, both configured on the user
aggregator (that is where they live in Pipecat 1.4.x).

Transcript saving: Windows' Popen.terminate() is a hard TerminateProcess with no
cleanup, so we can't rely on a disconnect handler running when Streamlit kills
this process. Instead a /hangup HTTP route saves the transcript on request,
independent of process shutdown; the on_client_disconnected handler is kept as
a fallback for the case where the browser disconnects on its own (e.g. tab
closed) rather than via Streamlit's Finish button.
"""

import asyncio
import os
import time
from datetime import datetime, timezone
from pathlib import Path


from loguru import logger
try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv(*args, **kwargs):
        return False

from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.openai.stt import OpenAIRealtimeSTTService
from pipecat.services.openai.tts import OpenAITTSService
from pipecat.services.anthropic.llm import AnthropicLLMService
from pipecat.transcriptions.language import Language
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner

load_dotenv(override=True)


# --- Performance Instrumentation ---
class Timer:
    """Simple context manager for measuring pipeline stage timing."""
    
    def __init__(self, label: str):
        self.label = label
        self.start_ns = None
    
    def __enter__(self):
        self.start_ns = time.perf_counter_ns()
        return self
    
    def __exit__(self, *args):
        elapsed_ms = (time.perf_counter_ns() - self.start_ns) / 1_000_000
        logger.debug(f"[TIMING-{self.label}] {elapsed_ms:.1f}ms")


# --- Configuration (from the environment set by the launching Streamlit page) ---
DEFAULT_MODEL = os.environ.get("BOT_MODEL", "claude-haiku-4-5")
PROMPT_PATH = os.environ.get("PROMPT_PATH")
STUDENT_IDENTIFIER = os.environ.get("STUDENT_IDENTIFIER", "anonymous")
MONGODB_URI = os.environ.get("MONGODB_CONNECTION_STRING")
MONGODB_DB = os.environ.get("MONGODB_DATABASE_NAME")
TRANSCRIPT_COLLECTION = os.environ.get("TRANSCRIPT_COLLECTION", "voice_transcripts")


transport_params = {
    "webrtc": lambda: TransportParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
    ),
}


# --- Minimal browser client -------------------------------------------------
# The Pipecat runner ships a full-featured prebuilt UI at /client/. We don't want
# all its controls, so we register our own bare-bones page at /simple.
SIMPLE_CLIENT_HTML_PATH = Path(__file__).resolve().parent / "simple_bot_client.html"
SIMPLE_CLIENT_HTML_FALLBACK = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" /></head>
<body style="font-family: system-ui, sans-serif; padding: 16px;">
  <p>The embedded voice client failed to load from disk.</p>
  <p>Expected file: utils/simple_bot_client.html</p>
</body>
</html>
"""


def _register_simple_client() -> None:
    """Serve the minimal client at /simple on the runner's FastAPI app."""
    from fastapi.responses import FileResponse, HTMLResponse

    from pipecat.runner.run import app

    @app.get("/simple", include_in_schema=False)
    async def simple_client():
        if SIMPLE_CLIENT_HTML_PATH.exists():
            return FileResponse(SIMPLE_CLIENT_HTML_PATH)

        logger.error(f"Simple client HTML not found at {SIMPLE_CLIENT_HTML_PATH}")
        return HTMLResponse(SIMPLE_CLIENT_HTML_FALLBACK, status_code=500)


_register_simple_client()


# --- Transcript saving ------------------------------------------------------
# Single connection per bot process, so a module-level reference to the active
# context is enough. Guarded so /hangup and on_client_disconnected can't both
# insert the same transcript twice.
_active_context: LLMContext | None = None
_transcript_saved = False


def _register_hangup_route() -> None:
    """Serve /hangup: save the transcript on request, independent of shutdown.

    Streamlit calls this right before it kills the bot process, since a hard
    kill (Windows Popen.terminate()) gives the process no chance to run its
    own cleanup handlers.
    """
    from pipecat.runner.run import app

    @app.post("/hangup", include_in_schema=False)
    async def hangup():
        if _active_context is not None:
            try:
                await asyncio.to_thread(_save_transcript_once, _active_context.get_messages())
            except Exception:
                logger.exception("Failed to save transcript via /hangup.")
        return {"status": "ok"}


_register_hangup_route()


def _load_system_prompt() -> str:
    """Read this stage's system prompt from disk, with a safe fallback."""
    if PROMPT_PATH:
        try:
            return Path(PROMPT_PATH).read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning(f"Could not read prompt at {PROMPT_PATH}: {exc}")
    else:
        logger.warning("PROMPT_PATH not set; using a generic fallback prompt.")
    return "You are a helpful assistant taking part in a roleplay exercise."


def _normalize_messages(messages) -> list[dict]:
    """Flatten LLMContext messages into simple {role, content} dicts.

    Context content can be a plain string or a list of content parts; we keep
    only the text so the stored transcript matches the shape the rest of the app
    (and the feedback stage) expects.
    """
    normalized = []
    for message in messages:
        role = message.get("role")
        if role == "system":
            continue
        content = message.get("content")
        if isinstance(content, list):
            content = "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict)
            )
        normalized.append({"role": role, "content": content or ""})
    return normalized



def _save_transcript(messages) -> None:
    """Persist the conversation to MongoDB on hangup, keyed by student id.

    Runs in this standalone process, so it cannot use utils.mongodb (that helper
    reads config from st.session_state). We connect directly instead.
    """
    if not MONGODB_URI or not MONGODB_DB:
        logger.info("MongoDB not configured; skipping transcript save.")
        return

    normalized = _normalize_messages(messages)
    if not normalized:
        logger.info("Empty transcript; nothing to save.")
        return

    from pymongo import MongoClient
    from pymongo.server_api import ServerApi

    client = MongoClient(MONGODB_URI, server_api=ServerApi("1"))
    try:
        db = client[MONGODB_DB]
        result = db[TRANSCRIPT_COLLECTION].insert_one(
            {
                "timestamp": datetime.now(timezone.utc),
                "messages": normalized,
                "identifier": STUDENT_IDENTIFIER,
            }
        )
        logger.info(f"Saved transcript {result.inserted_id} for {STUDENT_IDENTIFIER} to {TRANSCRIPT_COLLECTION}.")
    finally:
        client.close()


def _save_transcript_once(messages) -> None:
    """Save the transcript at most once, however saving is triggered."""
    global _transcript_saved
    if _transcript_saved:
        return
    _transcript_saved = True
    _save_transcript(messages)


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments):
    body = getattr(runner_args, "body", None) or {}
    model = body.get("model", DEFAULT_MODEL)
    system_prompt = body.get("system_prompt") or _load_system_prompt()

    logger.info(f"[BOT-START] Stage: {TRANSCRIPT_COLLECTION} | Model: {model} | Prompt size: {len(system_prompt)} chars")
    
    runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)

    with Timer("STT-init"):
        stt = OpenAIRealtimeSTTService(
            api_key=os.environ["OPENAI_API_KEY"],
            settings=OpenAIRealtimeSTTService.Settings(
                model="gpt-realtime-whisper",
                language=Language.EN,
            ),
        )
    
    # Optimize LLM settings per stage
    # Patient interaction: shorter responses for interview Q&A = lower max_tokens
    # Supervisor handover: longer responses for detailed feedback = higher max_tokens
    max_tokens = 256 if TRANSCRIPT_COLLECTION == "patient_interaction_transcripts" else 1024
    
    with Timer("LLM-init"):
        llm = AnthropicLLMService(
            api_key=os.environ["ANTHROPIC_API_KEY"],
            settings=AnthropicLLMService.Settings(
                model=model,
                system_instruction=system_prompt,
                max_tokens=max_tokens,
                enable_prompt_caching=True,  # caches the long handover prompt
            ),
        )
    
    with Timer("TTS-init"):
        tts = OpenAITTSService(
            api_key=os.environ["OPENAI_API_KEY"],
            settings=OpenAITTSService.Settings(model="tts-1", voice="alloy"),
        )

    # Shared context accumulates both sides of the conversation; we read it back
    # out on hangup to store the transcript. Published to the module level so
    # the /hangup route can reach it.
    global _active_context
    context = LLMContext()
    _active_context = context
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            user_turn_strategies=UserTurnStrategies(
                stop=[
                    TurnAnalyzerUserTurnStopStrategy(
                        turn_analyzer=LocalSmartTurnAnalyzerV3()
                    )
                ]
            ),
            vad_analyzer=SileroVADAnalyzer(),
        ),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,
            llm,
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )

    agent = PipelineWorker(
        pipeline,
        name="assistant",
        params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
    )

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        try:
            _save_transcript(context.get_messages())
        except Exception:  # never let a save error block shutdown
            logger.exception("Failed to save handover transcript.")
        await runner.cancel()

    await runner.add_workers(agent)
    await runner.run()


async def bot(runner_args: RunnerArguments):
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
