"""
Rate limiting (tiêu chí 7) — sliding window log trong Redis.

  • Mỗi API key tối đa RATE_LIMIT_PER_MINUTE request trong 60 giây
  • Vượt giới hạn → HTTP 429 + header Retry-After
  • State nằm trong Redis (sorted set) → mọi worker / instance dùng chung,
    vẫn còn sau khi restart agent
"""
import hashlib
import math
import time
import uuid

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60

# Atomic: xoá timestamp cũ → đếm → nếu còn chỗ thì thêm. Chạy trọn trong Redis
# nên 2 worker song song không thể cùng lọt qua khi chỉ còn 1 slot.
_SLIDING_WINDOW_LUA = """
local key    = KEYS[1]
local now    = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit  = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    return {0, count, tostring(oldest[2])}
end
redis.call('ZADD', key, now, ARGV[4])
redis.call('EXPIRE', key, window + 1)
return {1, count + 1, '0'}
"""
_sliding_window = r.register_script(_SLIDING_WINDOW_LUA)


def check_rate_limit(key: str) -> dict:
    """Trả về info về quota; vượt giới hạn → HTTPException 429."""
    limit = settings.rate_limit_per_minute
    # Không lưu API key gốc trong Redis — chỉ lưu hash
    bucket = "ratelimit:" + hashlib.sha256(key.encode()).hexdigest()[:16]
    now = time.time()
    try:
        allowed, count, oldest = _sliding_window(
            keys=[bucket], args=[now, WINDOW_SECONDS, limit, f"{now}-{uuid.uuid4().hex[:8]}"]
        )
    except redis.RedisError:
        raise HTTPException(status_code=503, detail="Rate limiter unavailable")

    if not int(allowed):
        retry_after = max(1, math.ceil(float(oldest) + WINDOW_SECONDS - now))
        raise HTTPException(
            status_code=429,
            detail={"error": "Rate limit exceeded", "limit": limit,
                    "window_seconds": WINDOW_SECONDS, "retry_after_seconds": retry_after},
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
            },
        )
    return {"limit": limit, "remaining": limit - int(count)}
