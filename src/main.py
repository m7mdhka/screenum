import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from loguru import logger

from api.setup_middleware import setup_middleware
from api.v1.endpoints.session import router as session_router
from core.config import Config
from services.gemini_client import gemini_client_instance
from services.redis_client import redis_client
from services.session_service import SessionService

google_logger = logging.getLogger("google.generativeai")
google_logger.setLevel(logging.ERROR)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Lifespan context manager for the FastAPI application.
    """
    logger.info("Starting up...")
    Config.validate()
    await redis_client.connect()

    app.state.redis_client = redis_client
    app.state.session_service = SessionService(
        gemini_client=gemini_client_instance, redis_client=redis_client.get_client()
    )
    yield
    logger.info("Shutting down...")

    await gemini_client_instance.close_all_sessions()
    await redis_client.disconnect()


app = FastAPI(
    title="AI Core",
    description="Core application for integrating with Gemini Live API",
    version="0.0.1",
    lifespan=lifespan,
)
setup_middleware(app=app)
app.include_router(session_router, prefix="/api/v1")


@app.get("/")
async def root() -> dict[str, str]:
    """
    Root endpoint for the API.
    """
    return {"message": "AI Core API is running!"}


@app.get("/health")
async def health_check() -> dict[str, str]:
    """
    Health check endpoint for the API.
    """
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    logger.info(f"Starting server on {Config.APP_HOST}:{Config.APP_PORT}")
    uvicorn.run(app, host=Config.APP_HOST, port=Config.APP_PORT, log_level="info")
