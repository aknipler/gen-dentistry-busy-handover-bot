"""Generic Pipecat voice bot, reused across roleplay stages.

This runs as its own process (a FastAPI + Daily server), rather than inside
Streamlit. The student's browser connects directly to a Daily room to reach
the microphone - Daily hosts the actual WebRTC media/SFU infrastructure, so
the browser never needs to reach this process or this container over the
network (only Streamlit's own server-to-server calls to localhost do, e.g.
to request a room and to send /hangup). This is required because Streamlit
Community Cloud only exposes Streamlit's own port to the internet; a
self-hosted WebRTC transport (SmallWebRTC/aiortc) bound to a subprocess port
is unreachable from the student's browser there. Streamlit (see
utils/voice_bot_launcher.py) launches this process per stage, requests a
Daily room from it, and embeds that room's URL.

This script has no stage-specific knowledge (no "supervisor" or "patient"
wording) - which prompt to use, which Mongo collection to save to, and who the
student is all come from environment variables, so the same script serves
every voice roleplay stage:

    ANTHROPIC_API_KEY          - required, Claude API key
    BOT_MODEL                  - Claude model id (default: claude-haiku-4-5)
    BOT_VOICE                  - TTS voice (default: alloy)
    PROMPT_PATH                - path to the system prompt file for this stage
    TRANSCRIPT_COLLECTION      - Mongo collection to save the transcript into
    STUDENT_IDENTIFIER         - student id, stored with the transcript
    MONGODB_CONNECTION_STRING  - if set, the transcript is saved on hangup
    MONGODB_DATABASE_NAME      - database to write the transcript into

Pipeline: Daily in -> Whisper STT (local) -> Claude -> Kokoro TTS -> Daily out.
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
from pipecat.transports.base_transport import BaseTransport
from pipecat.transports.daily.transport import DailyParams
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner

load_dotenv(override=True)

# .env/secrets.toml name the key DAILY_CO_API_KEY (to disambiguate from other
# services' API keys); pipecat's Daily transport/runner reads DAILY_API_KEY
# specifically. The launcher already sets DAILY_API_KEY directly when
# spawning this as a subprocess - this fallback only matters when running
# this file directly (e.g. `python utils/voice_bot.py -t daily`) for testing.
os.environ.setdefault("DAILY_API_KEY", os.environ.get("DAILY_CO_API_KEY", ""))


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
DEFAULT_VOICE = os.environ.get("BOT_VOICE", "alloy")  # default voice for TTS
PROMPT_PATH = os.environ.get("PROMPT_PATH")
STUDENT_IDENTIFIER = os.environ.get("STUDENT_IDENTIFIER", "anonymous")
MONGODB_URI = os.environ.get("MONGODB_CONNECTION_STRING")
MONGODB_DB = os.environ.get("MONGODB_DATABASE_NAME")
TRANSCRIPT_COLLECTION = os.environ.get("TRANSCRIPT_COLLECTION", "voice_transcripts")


transport_params = {
    "daily": lambda: DailyParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        camera_out_enabled=False,
    ),
}


# --- Transcript saving ------------------------------------------------------
# Single connection per bot process, so a module-level reference to the active
# context is enough. Guarded so /hangup and on_client_disconnected can't both
# insert the same transcript twice.
_active_context: LLMContext | None = None
_transcript_saved = False

# A fresh MongoClient's first connect (DNS SRV lookup + TLS handshake to Atlas)
# can take 4-5+ seconds. /hangup is called right before Streamlit force-kills
# this process, with only a few seconds of grace - a cold connect started at
# that moment routinely loses the race and gets killed mid-insert, silently
# dropping the transcript. We connect once, eagerly, at bot startup instead
# (see _warm_mongo_client), so by the time /hangup fires the connection is
# already established and the insert itself is fast.
_mongo_client = None


def _warm_mongo_client() -> None:
    """Eagerly establish the MongoDB connection well before /hangup needs it."""
    global _mongo_client
    if not MONGODB_URI or not MONGODB_DB:
        return
    try:
        from pymongo import MongoClient
        from pymongo.server_api import ServerApi

        client = MongoClient(MONGODB_URI, server_api=ServerApi("1"))
        client.admin.command("ping")  # force the connection to actually establish now
        _mongo_client = client
        logger.info("MongoDB connection warmed up and ready.")
    except Exception:
        logger.exception("Failed to warm up MongoDB connection; will retry on save.")


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
    reads config from st.session_state). We connect directly instead, reusing
    the connection _warm_mongo_client() opened at startup so this doesn't pay
    the cold-connect cost while Streamlit's kill timer is already running.
    """
    if not MONGODB_URI or not MONGODB_DB:
        logger.info("MongoDB not configured; skipping transcript save.")
        return

    normalized = _normalize_messages(messages)
    if not normalized:
        logger.info("Empty transcript; nothing to save.")
        return

    global _mongo_client
    client = _mongo_client
    if client is None:
        # Warm-up hadn't finished (or failed) - fall back to connecting now.
        from pymongo import MongoClient
        from pymongo.server_api import ServerApi

        client = MongoClient(MONGODB_URI, server_api=ServerApi("1"))
        _mongo_client = client


    db = client[MONGODB_DB]
    result = db[TRANSCRIPT_COLLECTION].insert_one(
        {
            "timestamp": datetime.now(timezone.utc),
            "messages": normalized,
            "identifier": STUDENT_IDENTIFIER,
        }
    )
    logger.info(f"Saved transcript {result.inserted_id} for {STUDENT_IDENTIFIER} to {TRANSCRIPT_COLLECTION}.")


def _save_transcript_once(messages) -> None:
    """Save the transcript at most once, however saving is triggered."""
    global _transcript_saved
    if _transcript_saved:
        return
    _save_transcript(messages)
    _transcript_saved = True


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments):
    body = getattr(runner_args, "body", None) or {}
    model = body.get("model", DEFAULT_MODEL)
    voice = body.get("voice", DEFAULT_VOICE)
    system_prompt = str(body.get("system_prompt") or _load_system_prompt()) + "Do not describe any actions, thoughts, or movements."

    logger.info(f"[BOT-START] Stage: {TRANSCRIPT_COLLECTION} | Model: {model} | Voice: {voice} | Prompt size: {len(system_prompt)} chars")

    # Fire-and-forget: connect to MongoDB now, in the background, so the
    # connection is already warm by the time /hangup needs to save the
    # transcript (see _warm_mongo_client's docstring for why this matters).
    asyncio.create_task(asyncio.to_thread(_warm_mongo_client))

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
            settings=OpenAITTSService.Settings(model="tts-1", voice=voice),
            # Voice options for older man: Ash or Onyx
            # Voice options for older woman: Alloy
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
