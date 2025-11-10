import asyncio

from fastapi import WebSocket
from loguru import logger


class ConnectionManager:
    """Manages active WebSocket connections using in-memory queues."""

    def __init__(self) -> None:
        """Initializes the ConnectionManager."""
        self.active_connections: dict[str, tuple[WebSocket, asyncio.Queue]] = {}

    async def connect(self, session_id: str, websocket: WebSocket) -> asyncio.Queue:
        """Accepts a WebSocket connection and sets up its dedicated audio queue."""
        await websocket.accept()
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self.active_connections[session_id] = (websocket, queue)
        logger.info(f"WebSocket connected for session {session_id}")
        return queue

    def disconnect(self, session_id: str) -> None:
        """Cleans up a disconnected session."""
        if session_id in self.active_connections:
            del self.active_connections[session_id]
            logger.info(f"WebSocket for session {session_id} cleaned up.")

    async def broadcast(self, session_id: str, data: bytes) -> None:
        """Puts audio data directly into the queue for a specific session."""
        if session_id in self.active_connections:
            _websocket, queue = self.active_connections[session_id]
            try:
                queue.put_nowait(data)
            except asyncio.QueueFull:
                logger.warning(
                    f"Audio queue full for session {session_id}. Dropping packet."
                )
        else:
            logger.debug(f"Attempted to broadcast to non-existent session {session_id}")

    async def consumer_task(
        self, session_id: str, queue: asyncio.Queue, websocket: WebSocket
    ) -> None:
        """
        A long-running task for each connection.
        It pulls audio from the queue and sends it to the client.

        Args:
            session_id (str): The ID of the session.
            queue (asyncio.Queue): The queue to pull audio from.
            websocket (WebSocket): The WebSocket connection to send audio to.
        """
        try:
            while True:
                data = await queue.get()
                await websocket.send_bytes(data)
                queue.task_done()
        except Exception as e:
            logger.error(f"Error in consumer task for session {session_id}: {e}")
        finally:
            self.disconnect(session_id)


manager = ConnectionManager()
