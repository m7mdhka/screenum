from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, status
from fastapi.websockets import WebSocketDisconnect
from loguru import logger

from schemas.session import (
    SdpAnswerRequest,
    SessionCreateRequest,
    SessionCreateResponse,
    StatusResponse,
)
from services.connection_manager import manager as connection_manager
from services.session_service import SessionService

router = APIRouter()


def get_session_service(request: Request) -> SessionService:
    return request.app.state.session_service


@router.post(
    "/session",
    response_model=SessionCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_new_session(
    request: SessionCreateRequest,
    session_service: SessionService = Depends(get_session_service),
) -> SessionCreateResponse:
    """
    Creates a new AI assistant session.

    This initializes the connection with the Gemini Live API and generates a
    WebRTC offer to be sent to the client SDK.
    """
    logger.info("Received request to create a new session.")
    session_id, offer = await session_service.create_session(request)
    return SessionCreateResponse(session_id=session_id, offer=offer)


@router.post("/session/{session_id}/answer", response_model=StatusResponse)
async def receive_webrtc_answer(
    session_id: str,
    request: SdpAnswerRequest,
    session_service: SessionService = Depends(get_session_service),
) -> StatusResponse:
    """
    Receives the client's SDP answer to establish the WebRTC data channels.
    """
    logger.info(f"Received WebRTC answer for session: {session_id}")
    await session_service.set_webrtc_answer(session_id, request)
    return StatusResponse(
        status="success", message="WebRTC answer received and connection established."
    )


@router.delete("/session/{session_id}", response_model=StatusResponse)
async def terminate_session(
    session_id: str,
    session_service: SessionService = Depends(get_session_service),
) -> StatusResponse:
    """
    Gracefully closes the session and cleans up all resources.
    """
    logger.info(f"Received request to terminate session: {session_id}")
    closed = await session_service.close_session(session_id)
    if not closed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found."
        )
    return StatusResponse(status="success", message="Session terminated.")


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str) -> None:
    """Handles the WebSocket lifecycle for audio streaming."""
    try:
        queue = await connection_manager.connect(session_id, websocket)
        await connection_manager.consumer_task(session_id, queue, websocket)
    except WebSocketDisconnect:
        connection_manager.disconnect(session_id)
        logger.info(f"WebSocket disconnected by client for session {session_id}.")
