import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    """Configuration class for the application."""

    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "")

    APP_HOST: str = os.getenv("APP_HOST", "0.0.0.0")
    APP_PORT: int = int(os.getenv("APP_PORT", "8000"))

    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")

    INPUT_RATE: int = int(os.getenv("INPUT_RATE", "16000"))
    OUTPUT_RATE: int = int(os.getenv("OUTPUT_RATE", "24000"))

    @classmethod
    def validate(cls) -> None:
        """Validate the configuration."""
        if cls.GEMINI_API_KEY.strip() == "":
            raise ValueError("GEMINI_API_KEY is not set.")
        if cls.GEMINI_MODEL.strip() == "":
            raise ValueError("GEMINI_MODEL is not set.")
        if cls.REDIS_URL.strip() == "":
            raise ValueError("REDIS_URL is not set.")
