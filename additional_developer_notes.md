
## How the voice bots work

The patient and supervisor conversations are real-time voice, not text chat.
Streamlit itself can't reach the microphone, so each stage launches its own
**separate OS process** running [Pipecat](https://github.com/pipecat-ai/pipecat)
(`utils/voice_bot.py`) as a small FastAPI + WebRTC server. The student's
browser connects to that process directly (over `http://localhost:<port>/simple`)
to stream audio; Streamlit only starts/stops the process and polls MongoDB
for the saved transcript once the conversation finishes.

`utils/voice_bot.py` is stage-agnostic — the same script serves both the
patient and supervisor stages. Which prompt to load, which Mongo collection to
save into, which voice to use, etc. are all passed in via environment
variables set by `utils/voice_bot_launcher.py` (see `VOICE_BOT_STAGES` in that
file). The pipeline itself is: WebRTC in → OpenAI Realtime STT → Claude
(Anthropic) → OpenAI TTS → WebRTC out, with Silero VAD + Smart Turn v3 for
turn-taking.

Because Windows' `Popen.terminate()` can't run cleanup code in the bot
process, finishing a conversation POSTs to a `/hangup` route on the bot
(`finish_voice_handover()` in `utils/voice_bot_launcher.py`) to save the
transcript *before* the process is force-killed, rather than relying on a
disconnect handler.