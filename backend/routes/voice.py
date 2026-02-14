"""
Voice transcription for the extension's microphone button.
Uses MiniMax when MINIMAX_API_KEY (or MINI_MAX_API_KEY) is set, otherwise OpenAI Whisper.
"""
import io
import logging
import os
from fastapi import APIRouter, File, HTTPException, UploadFile

router = APIRouter(prefix="/voice", tags=["voice"])
logger = logging.getLogger(__name__)


def _get_minimax_key() -> str | None:
    return (
        os.getenv("MINIMAX_API_KEY", "").strip()
        or os.getenv("MINI_MAX_API_KEY", "").strip()
        or None
    )


def _get_openai_key() -> str | None:
    return os.getenv("OPENAI_API_KEY", "").strip() or None


@router.post("/transcribe")
async def transcribe_voice(audio: UploadFile = File(...)):
    """
    Accept an audio file (e.g. webm from browser MediaRecorder), transcribe with
    MiniMax (if API key set) or OpenAI Whisper, return text.
    Extension sends recorded blob here and gets back { "text": "..." } to fill the command input.
    """
    try:
        from openai import OpenAI
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="openai package not installed. pip install openai",
        )

    content = await audio.read()
    if not content or len(content) < 100:
        raise HTTPException(status_code=400, detail="Audio file too short or empty.")

    minimax_key = _get_minimax_key()
    openai_key = _get_openai_key()
    if not minimax_key and not openai_key:
        raise HTTPException(
            status_code=503,
            detail="Set MINIMAX_API_KEY or MINI_MAX_API_KEY (MiniMax) or OPENAI_API_KEY (Whisper) in .env for voice transcription.",
        )

    buf = io.BytesIO(content)
    text = None
    try:
        if minimax_key:
            try:
                client = OpenAI(
                    api_key=minimax_key,
                    base_url="https://api.minimax.io/v1",
                )
                transcript = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=buf,
                )
                text = (transcript.text or "").strip()
                logger.info("[voice] MiniMax transcribe ok len=%d", len(text))
            except Exception as e:
                logger.warning("[voice] MiniMax transcribe failed (falling back to Whisper): %s", e)
                text = None

        if text is None and openai_key:
            buf.seek(0)
            client = OpenAI(api_key=openai_key)
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=buf,
            )
            text = (transcript.text or "").strip()
            logger.info("[voice] Whisper transcribe ok len=%d", len(text))

        if text is None:
            raise HTTPException(
                status_code=503,
                detail="Transcription failed. If using MiniMax, ensure the API supports audio/transcriptions; otherwise set OPENAI_API_KEY for Whisper fallback.",
            )
        return {"text": text}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[voice] transcribe failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)[:300])
