# routes/stt_routes.py
"""STT API routes — multi-provider (local Whisper, API endpoint, browser)."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
import logging

from src.upload_limits import read_upload_limited, STT_MAX_AUDIO_BYTES
from src.upload_body_limits import parse_limited_multipart_form, uploaded_values

logger = logging.getLogger(__name__)


def setup_stt_routes(stt_service):
    """Setup STT routes with the provided STT service"""
    router = APIRouter(prefix="/api/stt", tags=["stt"])

    @router.get("/stats")
    async def get_stt_stats():
        """Get STT service statistics"""
        try:
            return stt_service.get_stats()
        except Exception as e:
            logger.error(f"Failed to get STT stats: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/transcribe")
    async def transcribe_audio(request: Request, file: Any = None):
        """Transcribe uploaded audio file to text"""
        try:
            if file is None:
                form = await parse_limited_multipart_form(request, max_files=1)
                uploads = uploaded_values(form, "file")
                file = uploads[0] if len(uploads) == 1 else None
            if not hasattr(file, "read"):
                raise HTTPException(status_code=400, detail={"message": "No audio file uploaded"})

            if not stt_service.available:
                raise HTTPException(
                    status_code=503,
                    detail={"message": "STT service not available or set to browser mode"}
                )

            audio_bytes = await read_upload_limited(file, STT_MAX_AUDIO_BYTES, "Audio file")
            if not audio_bytes:
                raise HTTPException(status_code=400, detail={"message": "Empty audio file"})

            text = stt_service.transcribe(audio_bytes)
            if text is None:
                raise HTTPException(
                    status_code=500,
                    detail={"message": "Transcription failed"}
                )

            return {"text": text}

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Transcription error: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail={"message": f"Transcription failed: {str(e)}"}
            )

    return router
