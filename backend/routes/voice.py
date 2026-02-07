"""
Voice transcription using OpenAI Whisper for the extension's microphone button.
"""
import logging
import os
from fastapi import APIRouter, File, HTTPException, UploadFile

router = APIRouter(prefix="/voice", tags=["voice"])
logger = logging.getLogger(__name__)


@router.post("/transcribe")
async def transcribe_voice(audio: UploadFile = File(...)):
    """
    Accept an audio file (e.g. webm from browser MediaRecorder), transcribe with OpenAI Whisper, return text.
    Extension sends recorded blob here and gets back { "text": "..." } to fill the command input.
    """
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not set. Add it to .env to use voice transcription.",
        )
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
    import tempfile
    suffix = os.path.splitext(audio.filename or "")[1] or ".webm"
    path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(content)
            f.flush()
            path = f.name
        client = OpenAI(api_key=key)
        with open(path, "rb") as fp:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=fp,
            )
        text = (transcript.text or "").strip()
        logger.info("[voice] transcribe ok len=%d", len(text))
        return {"text": text}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[voice] transcribe failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)[:300])
    finally:
        if path and os.path.isfile(path):
            try:
                os.unlink(path)
            except Exception:
                pass
