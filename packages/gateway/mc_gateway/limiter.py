from datetime import UTC, datetime

from redis.asyncio import Redis

from mc_shared.errors import PlatformError
from mc_shared.settings import get_settings

_memory: dict[str, int] = {}
_client: Redis | None = None


def _redis() -> Redis | None:
    global _client
    url = get_settings().redis_url
    if not url:
        return None
    if _client is None:
        _client = Redis.from_url(url, decode_responses=True)
    return _client


async def _add(key: str, amount: int, ttl: int) -> int:
    client = _redis()
    if client is None:
        _memory[key] = _memory.get(key, 0) + amount
        return _memory[key]
    count = await client.incrby(key, amount)
    if count == amount:
        await client.expire(key, ttl)
    return int(count)


async def enforce_limits(
    *,
    key_id: str,
    project_id: str,
    rpm: int,
    tpm: int,
    daily: int,
    monthly: int,
    tokens: int,
) -> None:
    now = datetime.now(UTC)
    minute = now.strftime("%Y%m%d%H%M")
    day = now.strftime("%Y%m%d")
    month = now.strftime("%Y%m")
    scopes = (f"key:{key_id}", f"project:{project_id}")
    for scope in scopes:
        if await _add(f"rl:rpm:{scope}:{minute}", 1, 120) > rpm:
            raise PlatformError("rate_limit_exceeded", "Request rate limit exceeded.", 429)
        if await _add(f"rl:day:{scope}:{day}", 1, 172800) > daily:
            raise PlatformError("rate_limit_exceeded", "Daily request limit exceeded.", 429)
        if await _add(f"rl:month:{scope}:{month}", 1, 3456000) > monthly:
            raise PlatformError("rate_limit_exceeded", "Monthly request limit exceeded.", 429)
        if await _add(f"rl:tpm:{scope}:{minute}", max(1, tokens), 120) > tpm:
            raise PlatformError("rate_limit_exceeded", "Token rate limit exceeded.", 429)


def reset_memory_limits() -> None:
    _memory.clear()
