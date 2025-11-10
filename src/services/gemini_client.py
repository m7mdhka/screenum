import asyncio
import io
import time
from contextlib import AsyncExitStack
from typing import Any, Awaitable, Callable, TypedDict
from warnings import deprecated

import PIL.Image
import websockets
from aiortc import RTCDataChannel, RTCPeerConnection, RTCSessionDescription
from google import genai
from google.genai import types
from google.genai.live import AsyncSession
from loguru import logger

from core.config import Config

type SessionID = str
type OnAudioCallback = Callable[[bytes], None] | Callable[[bytes], Awaitable[None]]
type OnTextCallback = Callable[[str], None] | Callable[[str], Awaitable[None]]
type OnErrorCallback = (
    Callable[[Exception], None] | Callable[[Exception], Awaitable[None]]
)


class CallbackDict(TypedDict, total=False):
    """Dictionary for storing callbacks.

    The `total=False` parameter makes all fields optional, allowing partial dictionaries
    to be created. This means you can provide only the callbacks you need without
    being forced to provide all possible callback functions.
    """

    on_audio: OnAudioCallback | None
    on_text: OnTextCallback | None
    on_error: OnErrorCallback | None


class WebRTCManager:
    """Manages a single WebRTC peer connection with optimized frame handling."""

    def __init__(
        self,
        on_video_frame: Callable[[bytes], Awaitable[None]],
        on_audio_frame: Callable[[bytes], Awaitable[None]],
    ):
        self.pc = RTCPeerConnection()
        self._on_video_frame = on_video_frame
        self._on_audio_frame = on_audio_frame
        self._video_channel: RTCDataChannel | None = None
        self._audio_channel: RTCDataChannel | None = None

        self._last_frame_hash: str | None = None
        self._last_frame_time: float = 0
        self._frame_rate_limit: float = 3.0
        self._max_image_size: tuple[int, int] = (
            512,
            512,
        )

        @self.pc.on("connectionstatechange")
        async def on_connection_state_change() -> None:
            logger.info(
                f"WebRTC connection state changed to: {self.pc.connectionState}"
            )

        @self.pc.on("iceconnectionstatechange")
        async def on_ice_connection_state_change() -> None:
            logger.info(
                f"ICE connection state changed to: {self.pc.iceConnectionState}"
            )

        @self.pc.on("datachannel")
        def on_datachannel(channel: RTCDataChannel) -> None:
            logger.info(
                f"Remote DataChannel '{channel.label}' received with state: {channel.readyState}"
            )

    @deprecated("Gemini Live API now handles image optimization automatically")
    def _optimize_image(self, image_data: bytes) -> bytes | None:
        """Optimize image for API transmission."""
        try:
            img = PIL.Image.open(io.BytesIO(image_data))
            img.thumbnail(self._max_image_size, PIL.Image.Resampling.LANCZOS)

            processed_img: PIL.Image.Image
            if img.mode in ("RGBA", "LA", "P"):
                background = PIL.Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "P":
                    converted_img = img.convert("RGBA")
                    background.paste(converted_img, mask=converted_img.split()[-1])
                else:
                    background.paste(
                        img,
                        mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None,
                    )
                processed_img = background
            elif img.mode != "RGB":
                processed_img = img.convert("RGB")
            else:
                processed_img = img

            buffer = io.BytesIO()
            processed_img.save(buffer, format="JPEG", quality=60, optimize=True)
            optimized_data = buffer.getvalue()

            logger.debug(
                f"Image optimized: {len(image_data)} -> {len(optimized_data)} bytes"
            )
            return optimized_data

        except Exception as e:
            logger.error(f"Error optimizing image: {e}")
            return None

    def _handle_message_sync(self, channel_type: str, message: bytes | str) -> None:
        """Synchronous wrapper to handle async message processing with optimization."""
        try:
            if channel_type == "video" and isinstance(message, bytes):
                asyncio.ensure_future(self._on_video_frame(message))
            elif channel_type == "audio" and isinstance(message, bytes):
                logger.debug(f"Handling audio message: {len(message)} bytes")
                asyncio.ensure_future(self._on_audio_frame(message))
            elif isinstance(message, str):
                logger.info(f"Received text message on {channel_type}: {message}")
            else:
                logger.warning(
                    f"Unexpected message type on {channel_type}: {type(message)}"
                )
        except Exception as e:
            logger.error(f"Error handling {channel_type} message: {e}", exc_info=True)

    async def create_offer(self) -> RTCSessionDescription:
        """Creates an SDP offer to initiate the connection."""
        self._video_channel = self.pc.createDataChannel("video", ordered=True)
        self._audio_channel = self.pc.createDataChannel("audio", ordered=True)

        assert self._video_channel is not None
        assert self._audio_channel is not None

        logger.info(
            f"Created video channel: {self._video_channel.label}, state: {self._video_channel.readyState}"
        )
        logger.info(
            f"Created audio channel: {self._audio_channel.label}, state: {self._audio_channel.readyState}"
        )

        @self._video_channel.on("open")
        def on_video_open() -> None:
            logger.info(
                f"Video channel opened, ready state: {getattr(self._video_channel, 'readyState', 'unknown')}"
            )

        @self._video_channel.on("close")
        def on_video_close() -> None:
            logger.info("Video channel closed")

        @self._video_channel.on("error")
        def on_video_error(error: Exception) -> None:
            logger.error(f"Video channel error: {error}")

        @self._video_channel.on("message")
        def on_video_message(message: bytes | str) -> None:
            logger.info(
                f"Video message received: type={type(message).__name__}, size={len(message) if isinstance(message, bytes | str) else 'unknown'}"
            )
            if (
                not self._video_channel
                or getattr(self._video_channel, "readyState", None) != "open"
            ):
                logger.warning(
                    f"Video channel not open, state: {getattr(self._video_channel, 'readyState', 'unknown')}"
                )
                return
            self._handle_message_sync("video", message)

        @self._audio_channel.on("open")
        def on_audio_open() -> None:
            logger.info(
                f"Audio channel opened, ready state: {getattr(self._audio_channel, 'readyState', 'unknown')}"
            )

        @self._audio_channel.on("close")
        def on_audio_close() -> None:
            logger.info("Audio channel closed")

        @self._audio_channel.on("error")
        def on_audio_error(error: Exception) -> None:
            logger.error(f"Audio channel error: {error}")

        @self._audio_channel.on("message")
        def on_audio_message(message: bytes | str) -> None:
            logger.info(
                f"Audio message received: type={type(message).__name__}, size={len(message) if isinstance(message, bytes | str) else 'unknown'}"
            )
            if (
                not self._audio_channel
                or getattr(self._audio_channel, "readyState", None) != "open"
            ):
                logger.warning(
                    f"Audio channel not open, state: {getattr(self._audio_channel, 'readyState', 'unknown')}"
                )
                return
            self._handle_message_sync("audio", message)

        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)

        logger.info(f"Created offer with {len(self.pc.localDescription.sdp)} bytes SDP")

        logger.info(
            f"After offer - Video channel state: {getattr(self._video_channel, 'readyState', 'unknown')}"
        )
        logger.info(
            f"After offer - Audio channel state: {getattr(self._audio_channel, 'readyState', 'unknown')}"
        )

        return self.pc.localDescription

    async def set_answer(self, answer: RTCSessionDescription) -> None:
        """Sets the SDP answer received from the client."""
        logger.info(f"Setting answer with {len(answer.sdp)} bytes SDP")
        await self.pc.setRemoteDescription(answer)
        logger.info(f"Answer set, connection state: {self.pc.connectionState}")

        if self._video_channel:
            logger.info(
                f"After answer - Video channel state: {getattr(self._video_channel, 'readyState', 'unknown')}"
            )
        if self._audio_channel:
            logger.info(
                f"After answer - Audio channel state: {getattr(self._audio_channel, 'readyState', 'unknown')}"
            )

    async def close(self) -> None:
        """Closes the WebRTC peer connection."""
        logger.info("Closing WebRTC connection")
        if self._video_channel:
            self._video_channel.close()
        if self._audio_channel:
            self._audio_channel.close()
        await self.pc.close()


class SessionStores:
    def __init__(self) -> None:
        self.sessions: dict[SessionID, AsyncSession] = {}
        self.callbacks: dict[SessionID, CallbackDict] = {}
        self.response_listeners: dict[SessionID, asyncio.Task[Any]] = {}

        self.send_processor: dict[SessionID, dict[str, asyncio.Task[Any]]] = {}
        self.audio_send_queues: dict[SessionID, asyncio.Queue] = {}
        self.media_send_queues: dict[SessionID, asyncio.Queue] = {}

        self.contexts: dict[SessionID, AsyncExitStack] = {}
        self.webrtc_managers: dict[SessionID, WebRTCManager] = {}

        self.session_stats: dict[SessionID, dict[str, int]] = {}

    def clear_session(self, session_id: SessionID) -> None:
        """Remove all resources associated with a session_id."""
        for _store_name, store in self.__dict__.items():
            if isinstance(store, dict) and session_id in store:
                del store[session_id]


class GeminiLiveClient:
    """Client for the Gemini Live API with quota optimization."""

    def __init__(self) -> None:
        """
        Initialize the Gemini Live client.
        """
        self.client: genai.Client | None = None
        self.stores: SessionStores = SessionStores()

    def _get_client(self) -> genai.Client:
        """The main entry point for interacting with the Gemini API."""
        if self.client is None:
            if not Config.GEMINI_API_KEY:
                raise ValueError("GEMINI_API_KEY is not set.")
            self.client = genai.Client(
                api_key=Config.GEMINI_API_KEY,
                vertexai=False,
                project=None,
                location=None,
                http_options={"api_version": "v1alpha"},
            )
        return self.client

    def _build_config(
        self, system_instruction: str, audio_speaker_name: str = "Zephyr"
    ) -> types.LiveConnectConfig:
        """Build the Gemini Live config."""
        return types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            system_instruction=system_instruction,
            media_resolution=types.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=audio_speaker_name
                    )
                ),
            ),
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    disabled=False,
                    start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_HIGH,  # Detects speech more aggressively
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,  # Optional: Faster end detection for turn completion
                    prefix_padding_ms=10,  # Lower for reduced delay (try 0-20ms; too low risks false positives)
                    silence_duration_ms=200,  # Adjust based on expected silence gaps (higher allows longer pauses without ending turn)
                ),
            ),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            enable_affective_dialog=True,
        )

    async def create_webrtc_session(
        self,
        session_id: SessionID,
        system_instruction: str,
        audio_speaker_name: str,
        on_audio: OnAudioCallback | None = None,
        on_text: OnTextCallback | None = None,
        on_error: OnErrorCallback | None = None,
    ) -> WebRTCManager | None:
        """
        Creates a new session with full WebRTC, Gemini, and processing capabilities.
        Returns the WebRTCManager instance to handle the signaling (offer/answer).
        """
        if session_id in self.stores.sessions:
            await self.close_session(session_id)

        try:
            config = self._build_config(system_instruction, audio_speaker_name)
            client = self._get_client()
            stack = AsyncExitStack()
            self.stores.contexts[session_id] = stack
            try:
                session = await stack.enter_async_context(
                    client.aio.live.connect(config=config, model=Config.GEMINI_MODEL)
                )
            except websockets.exceptions.InvalidStatus as e:
                logger.error(f"Failed to create session {session_id}: {e}")
                raise e from e
            self.stores.sessions[session_id] = session
            self.stores.callbacks[session_id] = {
                "on_audio": on_audio,
                "on_text": on_text,
                "on_error": on_error,
            }

            self.stores.audio_send_queues[session_id] = asyncio.Queue(maxsize=50)
            self.stores.media_send_queues[session_id] = asyncio.Queue(maxsize=1)

            self.stores.session_stats[session_id] = {
                "audio_sent": 0,
                "images_sent": 0,
                "images_skipped": 0,
                "audio_received": 0,
            }

            self.stores.response_listeners[session_id] = asyncio.create_task(
                self._listen_for_responses(session_id)
            )

            self.stores.send_processor[session_id] = {}
            self.stores.send_processor[session_id]["audio"] = asyncio.create_task(
                self._process_audio_queue(session_id)
            )
            self.stores.send_processor[session_id]["media"] = asyncio.create_task(
                self._process_media_queue(session_id)
            )

            async def handle_video_frame(frame_data: bytes) -> None:
                """Handles an incoming video frame from the WebRTC connection with optimization."""
                success = await self.queue_image(
                    session_id, frame_data, mime_type="image/jpeg"
                )
                stats = self.stores.session_stats.get(session_id, {})
                if success:
                    stats["images_sent"] = stats.get("images_sent", 0) + 1
                else:
                    stats["images_skipped"] = stats.get("images_skipped", 0) + 1

            async def handle_audio_frame(audio_data: bytes) -> None:
                """Handles an incoming audio frame from the WebRTC connection."""
                success = await self.queue_audio(session_id, audio_data)
                if success:
                    stats = self.stores.session_stats.get(session_id, {})
                    stats["audio_sent"] = stats.get("audio_sent", 0) + 1

            webrtc_manager = WebRTCManager(
                on_video_frame=handle_video_frame, on_audio_frame=handle_audio_frame
            )
            self.stores.webrtc_managers[session_id] = webrtc_manager

            logger.info(
                f"Successfully created session {session_id} with WebRTC support."
            )
            return webrtc_manager

        except (ValueError, RuntimeError, KeyError) as e:
            logger.error(f"Failed to create WebRTC session {session_id}: {e}")
            await self._handle_error(session_id, e)
            return None

    async def _call_callback(self, callback: Any, *args: Any) -> None:
        """Helper to call either sync or async callbacks safely."""
        if callback is None:
            return
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(*args)
            else:
                callback(*args)
        except Exception as e:
            logger.error(f"Error executing callback: {e}")

    async def _handle_error(self, session_id: SessionID, error: Exception) -> None:
        """Centralized error handling to invoke the on_error callback."""
        callbacks = self.stores.callbacks.get(session_id, {})
        on_error = callbacks.get("on_error")
        if on_error:
            await self._call_callback(on_error, error)

    async def _process_audio_queue(self, session_id: SessionID) -> None:
        """Process audio and text queue in dedicated loop to prevent media starvation."""
        session = self.stores.sessions.get(session_id)
        audio_queue = self.stores.audio_send_queues.get(session_id)
        stats = self.stores.session_stats.get(session_id, {})

        if not session or not audio_queue:
            logger.error(f"Missing components for audio processing in {session_id}")
            return

        logger.info(f"Starting audio/text send processor for session {session_id}")
        items_sent = 0
        last_stats_log = time.time()

        try:
            while session_id in self.stores.sessions:
                try:
                    item = await audio_queue.get()
                    if isinstance(item, str):
                        logger.info(f"Sending text to Gemini: '{item[:50]}...'")
                        await session.send_client_content(
                            turns=[{"role": "user", "parts": [{"text": item}]}],
                            turn_complete=True,
                        )
                        items_sent += 1
                    elif isinstance(item, dict) and "audio" in item["mime_type"]:
                        logger.debug(
                            f"Sending audio to Gemini: {len(item['data'])} bytes"
                        )
                        blob = types.Blob(
                            data=item["data"], mime_type=item["mime_type"]
                        )
                        await session.send_realtime_input(audio=blob)
                        items_sent += 1
                        stats["audio_sent"] = stats.get("audio_sent", 0) + 1
                except Exception as e:
                    logger.error(f"Failed to send audio/text for {session_id}: {e}")
                    await self._handle_error(session_id, e)
                finally:
                    audio_queue.task_done()

                current_time = time.time()
                if current_time - last_stats_log > 30:
                    audio_size = audio_queue.qsize()
                    logger.info(
                        f"Session {session_id} audio stats - "
                        f"Queue size: {audio_size}, Items sent: {items_sent}, "
                        f"Audio sent: {stats.get('audio_sent', 0)}"
                    )
                    last_stats_log = current_time

                await asyncio.sleep(0)
        except asyncio.CancelledError:
            logger.info(f"Audio processor cancelled for {session_id}")
        finally:
            logger.info(
                f"Stopping audio processor for {session_id}. Items sent: {items_sent}"
            )

    async def _process_media_queue(self, session_id: SessionID) -> None:
        """Process media queue in dedicated loop to prevent starvation by audio."""
        session = self.stores.sessions.get(session_id)
        media_queue = self.stores.media_send_queues.get(session_id)
        stats = self.stores.session_stats.get(session_id, {})

        if not session or not media_queue:
            logger.error(f"Missing components for media processing in {session_id}")
            return

        logger.info(f"Starting media send processor for session {session_id}")
        items_sent = 0
        last_stats_log = time.time()

        try:
            while session_id in self.stores.sessions:
                try:
                    item = await media_queue.get()
                    if isinstance(item, dict) and "image" in item["mime_type"]:
                        logger.info(
                            f"Sending image to Gemini: {len(item['data'])} bytes"
                        )
                        blob = types.Blob(
                            data=item["data"], mime_type=item["mime_type"]
                        )
                        await session.send_realtime_input(video=blob)
                        items_sent += 1
                        stats["images_sent"] = stats.get("images_sent", 0) + 1
                except Exception as e:
                    logger.error(f"Failed to send media for {session_id}: {e}")
                    await self._handle_error(session_id, e)
                finally:
                    media_queue.task_done()

                current_time = time.time()
                if current_time - last_stats_log > 30:
                    media_size = media_queue.qsize()
                    logger.info(
                        f"Session {session_id} media stats - "
                        f"Queue size: {media_size}, Items sent: {items_sent}, "
                        f"Images sent: {stats.get('images_sent', 0)}, "
                        f"Images skipped: {stats.get('images_skipped', 0)}"
                    )
                    last_stats_log = current_time

                await asyncio.sleep(0)
        except asyncio.CancelledError:
            logger.info(f"Media processor cancelled for {session_id}")
        finally:
            logger.info(
                f"Stopping media processor for {session_id}. Items sent: {items_sent}"
            )

    async def _listen_for_responses(self, session_id: SessionID) -> None:
        session = self.stores.sessions.get(session_id)
        if session is None:
            return

        callbacks = self.stores.callbacks.get(session_id, {})
        stats = self.stores.session_stats.get(session_id, {})
        logger.info(f"Starting response listener for session {session_id}")

        on_audio_callback = callbacks.get("on_audio")
        if on_audio_callback:
            logger.info(f"✅ Audio callback is registered for session {session_id}.")
        else:
            logger.error(
                f"❌ CRITICAL: No audio callback registered for session {session_id}."
            )

        try:
            while session_id in self.stores.sessions:
                turn = session.receive()
                async for response in turn:
                    server_content = getattr(response, "server_content", None)
                    if server_content is not None and getattr(
                        server_content, "interrupted", False
                    ):
                        continue
                    audio_data = getattr(response, "data", None)
                    if audio_data:
                        logger.info(f"✅ FOUND AUDIO DATA: {len(audio_data)} bytes.")
                        await self._call_callback(on_audio_callback, audio_data)
                        stats["audio_received"] = stats.get("audio_received", 0) + 1

                    if response.text:
                        await self._call_callback(
                            callbacks.get("on_text"), response.text
                        )

        except asyncio.CancelledError:
            logger.info(f"Response listener cancelled for session {session_id}")
        except Exception as e:
            logger.error(
                f"Error in response listener for {session_id}: {e}", exc_info=True
            )
        finally:
            logger.info(f"Stopping response listener for session {session_id}")

    async def queue_audio(
        self,
        session_id: SessionID,
        audio_data: bytes,
        sample_rate: int = Config.INPUT_RATE,
    ) -> bool:
        """Queue audio data with configurable sample rate for better performance.

        Args:
            session_id: The session identifier
            audio_data: Raw audio bytes
            sample_rate: Sample rate in Hz (default 16000 for input, matches Google example)
        """
        queue = self.stores.audio_send_queues.get(session_id)
        if not queue:
            logger.warning(f"No audio queue for session {session_id}")
            return False
        try:
            queue.put_nowait({"data": audio_data, "mime_type": "audio/pcm"})
            logger.debug(
                f"Queued audio data: {len(audio_data)} bytes @ {sample_rate}Hz for session {session_id}. Queue size: {queue.qsize()}"
            )
            return True
        except asyncio.QueueFull:
            logger.warning(f"Audio queue full for {session_id}. Dropping audio.")
            return False

    async def queue_text(self, session_id: SessionID, text: str) -> bool:
        queue = self.stores.audio_send_queues.get(session_id)
        if not queue:
            logger.warning(f"No text queue for session {session_id}")
            return False
        try:
            queue.put_nowait(text)
            logger.debug(f"Queued text: '{text[:50]}...' for session {session_id}")
            return True
        except asyncio.QueueFull:
            logger.warning(f"Text queue full for {session_id}. Dropping text.")
            return False

    async def queue_image(
        self, session_id: SessionID, image_data: bytes, mime_type: str = "image/jpeg"
    ) -> bool:
        queue = self.stores.media_send_queues.get(session_id)
        if not queue:
            logger.warning(f"No media queue for session {session_id}")
            return False

        try:
            queue.put_nowait({"data": image_data, "mime_type": mime_type})
            logger.debug(
                f"Queued optimized image: {len(image_data)} bytes for session {session_id}. Queue size: {queue.qsize()}"
            )
            return True
        except asyncio.QueueFull:
            logger.warning(f"Image queue full for {session_id}. Dropping image.")
            return False

    async def close_session(self, session_id: SessionID) -> bool:
        if session_id not in self.stores.sessions:
            return False

        logger.info(f"Closing session {session_id}...")

        stats = self.stores.session_stats.get(session_id, {})
        logger.info(
            f"Session {session_id} final stats - "
            f"Audio sent: {stats.get('audio_sent', 0)}, "
            f"Images sent: {stats.get('images_sent', 0)}, "
            f"Images skipped: {stats.get('images_skipped', 0)}, "
            f"Audio received: {stats.get('audio_received', 0)}"
        )

        try:
            if webrtc_manager := self.stores.webrtc_managers.get(session_id):
                await webrtc_manager.close()
                logger.info(f"Closed WebRTC connection for {session_id}")

            if task := self.stores.response_listeners.get(session_id):
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            if processors := self.stores.send_processor.get(session_id):
                for task in processors.values():
                    if task:
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass

            if context := self.stores.contexts.get(session_id):
                await context.aclose()

            self.stores.clear_session(session_id)

            logger.info(f"Successfully closed session {session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to cleanly close session {session_id}: {e}")
            self.stores.clear_session(session_id)
            return False

    async def close_all_sessions(self) -> None:
        """Close all active sessions."""
        session_ids = list(self.stores.sessions.keys())
        await asyncio.gather(*(self.close_session(sid) for sid in session_ids))
        logger.info("Closed all sessions")

    def get_active_sessions(self) -> list[SessionID]:
        """Get all active sessions."""
        return list(self.stores.sessions.keys())

    def get_session_stats(self, session_id: SessionID) -> dict[str, int] | None:
        """Get statistics for a specific session."""
        return self.stores.session_stats.get(session_id)


gemini_client_instance = GeminiLiveClient()
