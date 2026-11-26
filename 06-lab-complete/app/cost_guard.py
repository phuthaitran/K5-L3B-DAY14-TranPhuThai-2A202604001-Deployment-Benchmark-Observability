"""
Cost guard (tiêu chí 8).

  • Cộng dồn chi phí LLM (tính theo token) vào Redis, theo ngày và theo tháng (UTC)
  • Tổng chi phí đạt DAILY_BUDGET_USD hoặc MONTHLY_BUDGET_USD → HTTP 402
  • Ngày / tháng nằm trong tên key → tự reset, key cũ tự hết hạn (EXPIRE)
"""
from datetime import datetime, timezone

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

DAY_TTL = 2 * 24 * 3600
MONTH_TTL = 32 * 24 * 3600


def _keys() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return f"cost:daily:{now:%Y-%m-%d}", f"cost:monthly:{now:%Y-%m}"


def estimate_tokens(text: str) -> int:
    """Ước lượng thô: ~4 ký tự / token."""
    return max(1, len(text) // 4)


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    daily_key, monthly_key = _keys()
    try:
        daily, monthly = r.mget(daily_key, monthly_key)
    except redis.RedisError:
        # Fail closed: không đếm được chi phí thì không gọi LLM
        raise HTTPException(status_code=503, detail="Cost guard unavailable")
    daily, monthly = float(daily or 0), float(monthly or 0)

    if daily >= settings.daily_budget_usd:
        raise HTTPException(status_code=402, detail={
            "error": "Daily budget exceeded",
            "used_usd": round(daily, 6), "budget_usd": settings.daily_budget_usd})
    if monthly >= settings.monthly_budget_usd:
        raise HTTPException(status_code=402, detail={
            "error": "Monthly budget exceeded",
            "used_usd": round(monthly, 6), "budget_usd": settings.monthly_budget_usd})


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    cost = (input_tokens / 1000) * PRICE_INPUT_PER_1K + (output_tokens / 1000) * PRICE_OUTPUT_PER_1K
    daily_key, monthly_key = _keys()
    pipe = r.pipeline()  # MULTI/EXEC: cả 4 lệnh chạy atomic
    pipe.incrbyfloat(daily_key, cost)
    pipe.expire(daily_key, DAY_TTL)
    pipe.incrbyfloat(monthly_key, cost)
    pipe.expire(monthly_key, MONTH_TTL)
    pipe.execute()
    return cost
