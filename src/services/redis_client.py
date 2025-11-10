import redis
from loguru import logger
from redis.asyncio import Redis

from core.config import Config


class RedisClient:
    """Manages the asynchronous Redis connection pool."""

    def __init__(self, url: str):
        self._url = url
        self.client: Redis | None = None

    async def connect(self) -> None:
        """Establishes the Redis connection."""
        try:
            self.client = Redis.from_url(
                self._url, encoding="utf-8", decode_responses=True
            )
            if self.client is not None:
                await self.client.ping()

                logger.info("Successfully connected to Redis.")
        except redis.ConnectionError as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise e from e

    async def disconnect(self) -> None:
        """Closes the Redis connection."""
        if self.client:
            await self.client.close()
            logger.info("Redis connection closed.")

    def get_client(self) -> Redis:
        """Returns the active Redis client instance."""
        if not self.client:
            raise RuntimeError("Redis client is not connected. Call connect() first.")
        return self.client


redis_client = RedisClient(Config.REDIS_URL)


def get_redis_client() -> Redis:
    """Dependency that provides the global Redis client instance."""
    return redis_client.get_client()
