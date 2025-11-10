import json
import uuid

from aiortc import RTCSessionDescription
from fastapi import HTTPException, status
from loguru import logger
from redis.asyncio import Redis

from schemas.session import SdpAnswerRequest, SdpPayload, SessionCreateRequest
from services.connection_manager import manager as connection_manager
from services.gemini_client import GeminiLiveClient


class SessionService:
    """Orchestrates session creation, connection, and termination."""

    def __init__(self, gemini_client: GeminiLiveClient, redis_client: Redis) -> None:
        self.gemini_client = gemini_client
        self.redis_client = redis_client

    async def create_session(
        self, request: SessionCreateRequest
    ) -> tuple[str, SdpPayload]:
        """Creates a new Gemini session and returns the session ID and SDP offer."""
        session_id = str(uuid.uuid4())

        async def on_audio_received(audio_data: bytes) -> None:
            await connection_manager.broadcast(session_id, audio_data)

        async def on_error_callback(error: Exception) -> None:
            logger.error(f"An error occurred in session {session_id}: {error}")

        webrtc_manager = await self.gemini_client.create_webrtc_session(
            session_id=session_id,
            system_instruction=request.system_instruction,
            audio_speaker_name=request.audio_speaker_name,
            on_audio=on_audio_received,
            on_error=on_error_callback,
        )

        if not webrtc_manager:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to initialize Gemini and WebRTC session.",
            )

        session_data = {
            "status": "pending",
            "system_instruction": request.system_instruction,
        }
        await self.redis_client.set(
            f"session:{session_id}", json.dumps(session_data), ex=300
        )

        offer = await webrtc_manager.create_offer()

        # The connection will not be fully active until the client's answer is received.
        # We return the offer here and wait for the /answer endpoint to be called.
        return session_id, SdpPayload(type="offer", sdp=offer.sdp)

    async def set_webrtc_answer(
        self, session_id: str, answer_request: SdpAnswerRequest
    ) -> None:
        """Sets the client's SDP answer to establish the WebRTC connection."""
        session_key = f"session:{session_id}"
        session_data_str = await self.redis_client.get(session_key)

        if not session_data_str:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found or expired.",
            )
        webrtc_manager = self.gemini_client.stores.webrtc_managers.get(session_id)
        if not webrtc_manager:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Session not found."
            )

        answer_payload = answer_request.answer
        answer_desc = RTCSessionDescription(
            sdp=answer_payload.sdp, type=answer_payload.type
        )
        try:
            await webrtc_manager.set_answer(answer_desc)
            logger.info(f"Successfully set WebRTC answer for session {session_id}")
        except Exception as e:
            logger.error(f"Failed to set WebRTC answer for session {session_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid SDP answer provided: {e}",
            )

        session_data = json.loads(session_data_str)
        session_data["status"] = "active"
        await self.redis_client.set(session_key, json.dumps(session_data))
        logger.info(f"Session {session_id} is now active.")

    async def close_session(self, session_id: str) -> bool:
        """Closes a session and cleans up all associated resources."""
        closed_locally = await self.gemini_client.close_session(session_id)
        deleted_from_redis = await self.redis_client.delete(f"session:{session_id}")
        return closed_locally or (deleted_from_redis > 0)
