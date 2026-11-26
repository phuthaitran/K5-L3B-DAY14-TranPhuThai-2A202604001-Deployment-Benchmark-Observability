"""
Production AI Agent — Part 6 Final Project

Kết hợp Part 1–5:
  • Config từ env (12-factor)            • API key auth (401)
  • Structured JSON logging              • Rate limit sliding window trong Redis (429)
  • /health (liveness), /ready (readiness) • Cost guard trong Redis (402)
  • Graceful shutdown qua lifespan       • Stateless: mọi state nằm trong Redis

Chạy:  uvicorn app.main:app --workers 2
Chấm:  python check_production_ready.py
"""
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, estimate_tokens, record_cost
from app.logging_config import setup_logging
from app.rate_limiter import check_rate_limit
from app.redis_client import r, redis_healthy
from utils.mock_llm import ask as llm_ask

logger = setup_logging(settings.log_level)

START_TIME = time.time()
_state = {"ready": False, "in_flight": 0}


# ──────────────────────────────────────────────────────────
# Lifespan — startup / graceful shutdown (tiêu chí 11)
# Uvicorn bắt SIGTERM: ngừng nhận kết nối mới, chờ request đang chạy xong,
# rồi chạy phần sau `yield` và thoát với exit code 0. Không tự đăng ký
# signal handler để khỏi đè handler của uvicorn.
# ──────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup", extra={
        "environment": settings.environment,
        "port": settings.port,
        "rate_limit_per_minute": settings.rate_limit_per_minute,
        "redis_connected": redis_healthy(),
    })
    if not settings.agent_api_key:
        logger.warning("AGENT_API_KEY is not set: every /ask request will be rejected with 401")
    _state["ready"] = True
    yield
    _state["ready"] = False
    logger.info("shutdown_started", extra={"in_flight_requests": _state["in_flight"]})
    try:
        r.close()
    except Exception:
        pass
    logger.info("shutdown_complete")


app = FastAPI(title="Production AI Agent", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """1 dòng log JSON cho mỗi request (không log header → không lộ API key)."""
    start = time.perf_counter()
    _state["in_flight"] += 1
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("unhandled_error", extra={"path": request.url.path})
        response = JSONResponse(status_code=500, content={"detail": "Internal server error"})
    finally:
        _state["in_flight"] -= 1
    logger.info("request", extra={
        "method": request.method,
        "path": request.url.path,
        "status": response.status_code,
        "ms": round((time.perf_counter() - start) * 1000, 1),
    })
    return response


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = None


# ──────────────────────────────────────────────────────────
# Health / readiness (tiêu chí 4, 5)
# ──────────────────────────────────────────────────────────
@app.get("/health")
def health():
    """Liveness: luôn 200 khi process còn sống, kể cả khi Redis mất kết nối."""
    return {
        "status": "ok",
        "version": app.version,
        "environment": settings.environment,
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "redis_connected": redis_healthy(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready")
def ready():
    """Readiness: 503 khi đang tắt hoặc Redis không kết nối được → LB ngừng gửi traffic."""
    if not _state["ready"]:
        return JSONResponse(status_code=503, content={"ready": False, "reason": "shutting down"})
    if not redis_healthy():
        return JSONResponse(status_code=503, content={"ready": False, "reason": "redis unavailable"})
    return {"ready": True, "in_flight_requests": _state["in_flight"]}


# ──────────────────────────────────────────────────────────
# Agent endpoint (tiêu chí 6, 7, 8)
# ──────────────────────────────────────────────────────────
@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    rate = check_rate_limit(api_key)   # 429 khi vượt giới hạn
    check_budget()                     # 402 khi hết budget — trước khi tốn tiền gọi LLM

    answer = llm_ask(body.question)

    cost = record_cost(estimate_tokens(body.question), estimate_tokens(answer))
    logger.info("llm_call", extra={
        "user_id": body.user_id,
        "question_len": len(body.question),
        "cost_usd": round(cost, 8),
    })
    return {
        "question": body.question,
        "answer": answer,
        "usage": {"requests_remaining": rate["remaining"], "cost_usd": round(cost, 8)},
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.port, reload=settings.debug)
