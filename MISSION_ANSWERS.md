# Day 14 Lab - Mission Answers

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found
1. Hardcoded API key, database URL and password in source code
2. No separate config management
3. Print the whole debug instead of logging
4. Leaked API key to output
5. No agent health check
6. Fixed URL and port

### Exercise 1.3: Comparison table
| Feature | Develop | Production | Why Important? |
|---------|---------|------------|----------------|
| Config | Hardcode | Env vars | Separate configuration from code, keeping sensitive credentials out of source control and letting the same build run across different environments without code changes |
| Health check | None | Liveness probe, Readiness probe | Verifies whether a service is alive, initialized, and able to handle traffic safely |
| Logging | `print()`, including the secret API key and full request/response | Structured JSON via `logging`, level set by `DEBUG`, logs only metadata (question length, client IP), never secrets | Log aggregators (Datadog, Loki, CloudWatch) can parse, filter and alert on JSON fields; log levels cut noise in production; keeping secrets and user data out of logs stops leaks through log storage |
| Shutdown | Sudden: process is killed mid-request, no cleanup | Graceful: `lifespan` hook sets `is_ready = False`, lets in-flight requests finish and closes resources; SIGTERM handler | Platforms send SIGTERM on every deploy, scale-down or restart. Graceful shutdown means users don't get dropped requests or 5xx errors, and DB connections and other resources are released cleanly |
| Host binding | `localhost` | `0.0.0.0` (from `HOST` env var) | Inside a container, `localhost` only accepts connections from the container itself, so the platform's router can't reach the app. `0.0.0.0` listens on all interfaces |
| Port | Hardcoded `8000` | Read from the `PORT` env var | Railway, Render and Cloud Run inject `PORT` at runtime. A hardcoded port can conflict with it or be unreachable |
| Hot reload | `reload=True` always | `reload=settings.debug` (on only in dev) | Reload watches files and restarts the process. In production that wastes CPU, can restart the app unexpectedly and is a security risk |
| Config validation | None | `validate()` fails fast if `AGENT_API_KEY` is missing in production, and warns if `OPENAI_API_KEY` is missing | A misconfiguration crashes at startup, where it's obvious, instead of causing silent failures or an unsecured endpoint at runtime |
| Input validation | No check on `question` (query param) | JSON body, returns 422 if `question` is empty | Bad input is rejected early with a clear error instead of being sent to the LLM (wasting tokens) or causing errors |
| CORS | Not configured | Only origins listed in `ALLOWED_ORIGINS` | Controls which web frontends can call the API from a browser |
| Observability | Only `/` | `/health`, `/ready`, `/metrics` (uptime, version, env) | Monitoring tools (Prometheus, uptime checkers) can track the service, and the version/env fields show exactly what is deployed |

## Part 2: Docker

### Exercise 2.1: Dockerfile questions
1. **Base image:** `python:3.11`, the full Python distribution (about 1 GB). A base image is the starting filesystem a container image is built on, here a Debian OS with Python 3.11, pip and many build tools already installed. Every later instruction adds a layer on top of it. The full image is convenient but large; `python:3.11-slim` or a multi-stage build makes it much smaller.
2. **Working directory:** `/app`. `WORKDIR /app` creates the directory if needed and makes it the current directory for every later `RUN`, `COPY`, `CMD` and `ENTRYPOINT`. That's why `COPY requirements.txt .` and `COPY app.py .` land in `/app`, and why `CMD ["python", "app.py"]` finds the file. It also keeps the app out of the root filesystem.
3. **Why COPY requirements.txt first:** Docker caches each layer and rebuilds a layer only when its inputs change, along with every layer after it. Copying only `requirements.txt` and running `pip install` before copying the code means a change to `app.py` invalidates just the final `COPY` layer, and the slow dependency install comes from cache. If you copied all the code first, every code edit would reinstall all dependencies and builds would be much slower.
4. **CMD vs ENTRYPOINT:**
   - `CMD` sets the **default** command or arguments, and anything passed to `docker run` replaces it. For example, `docker run agent-develop bash` runs `bash` instead of `python app.py`.
   - `ENTRYPOINT` sets the **fixed executable** that always runs. Arguments passed to `docker run` are appended to it instead of replacing it, and you can only change it with `--entrypoint`.
   - Used together, `ENTRYPOINT` is the program and `CMD` gives its default arguments. For example, `ENTRYPOINT ["python", "app.py"]` with `CMD ["--port", "8000"]` runs `python app.py --port 8000` by default, and `docker run img --port 9000` overrides only the arguments.
   - This Dockerfile uses only `CMD`, so the container runs `python app.py` by default but can easily be started with another command for debugging.

### Exercise 2.3: Image size comparison
- Develop: 1699.84 MB
- Production: 239.81 MB
- Difference: production is 85.9% smaller than development

### Exercise 2.4: Docker Compose stack

**Architecture diagram**

```
                    Client (browser / curl)
                              │
                              │  HTTP :80 / HTTPS :443  (only ports published to host)
                              ▼
┌──────────────────────────── Docker host ─────────────────────────────┐
│                                                                      │
│   ┌──────────────────────── network: internal (bridge) ───────────┐  │
│   │                                                               │  │
│   │            ┌──────────────────────────────┐                   │  │
│   │            │ nginx  (nginx:alpine)        │                   │  │
│   │            │ reverse proxy/load balancer  │                   │  │
│   │            └──────────────┬───────────────┘                   │  │
│   │                           │ http://agent:8000                 │  │
│   │                           ▼                                   │  │
│   │            ┌──────────────────────────────┐                   │  │
│   │            │ agent  (FastAPI, port 8000)  │                   │  │
│   │            │ built from production        │                   │  │
│   │            │ Dockerfile, target: runtime  │                   │  │
│   │            │ healthcheck: GET /health     │                   │  │
│   │            └───────┬──────────────┬───────┘                   │  │
│   │   redis://redis:6379/0           http://qdrant:6333           │  │
│   │                   ▼              ▼                            │  │
│   │   ┌────────────────────┐   ┌──────────────────────────┐       │  │
│   │   │ redis              │   │ qdrant                   │       │  │
│   │   │ (redis:7-alpine)   │   │ (qdrant/qdrant:v1.9.0)   │       │  │
│   │   │ session cache +    │   │ vector DB for RAG        │       │  │
│   │   │ rate limiting      │   │                          │       │  │
│   │   └─────────┬──────────┘   └────────────┬─────────────┘       │  │
│   └─────────────┼───────────────────────────┼─────────────────────┘  │
│                 ▼                           ▼                        │
│        volume: redis_data           volume: qdrant_data              │
│        (/data)                      (/qdrant/storage)                │
└──────────────────────────────────────────────────────────────────────┘

Startup order (depends_on):
  redis (healthy) ─┐
                   ├──► agent ──► nginx
  qdrant (healthy)─┘
```

**Which services are started?**

`docker compose up` starts 4 services:

| Service | Image | Role | Exposed to host? |
|---------|-------|------|------------------|
| `agent` | Built from `02-docker/production/Dockerfile` (stage `runtime`) | FastAPI AI agent on port 8000. Config comes from env vars plus `.env.local` (secrets, kept out of git). `restart: unless-stopped` | No, reachable only through nginx |
| `redis` | `redis:7-alpine` | Session cache and rate-limit counters, capped at 256 MB with LRU eviction, data kept in the `redis_data` volume | No |
| `qdrant` | `qdrant/qdrant:v1.9.0` | Vector database for RAG, data kept in the `qdrant_data` volume | No |
| `nginx` | `nginx:alpine` | Reverse proxy and load balancer, config mounted read-only from `./nginx/nginx.conf` | Yes, `80:80` and `443:443` |

Compose starts them in dependency order. `redis` and `qdrant` start first, and `agent` waits until both pass their healthchecks (`condition: service_healthy`). `nginx` starts after `agent` has started (plain `depends_on`, so it does not wait for the agent to be healthy).

**How do they communicate?**

- **One private network:** all 4 services are on the `internal` bridge network. Docker's built-in DNS resolves each service name (`agent`, `redis`, `qdrant`) to its container IP, so services use names instead of hardcoded IPs.
- **Client → nginx:** nginx is the only entry point, since only its ports 80 and 443 are published on the host. agent, redis and qdrant publish no ports, so they can't be reached from outside, which reduces the attack surface.
- **nginx → agent:** nginx proxies requests to `http://agent:8000` (defined in `nginx.conf`). If the agent is scaled to several replicas (`docker compose up --scale agent=2`), Docker DNS returns all their IPs and nginx spreads the requests across them.
- **agent → redis:** over the Redis protocol at `REDIS_URL=redis://redis:6379/0`, used for sessions and rate limiting.
- **agent → qdrant:** over HTTP REST at `QDRANT_URL=http://qdrant:6333`, used for vector search.
- **Healthchecks:** Docker checks each service from inside its container: the agent with `GET http://localhost:8000/health`, redis with `redis-cli ping`, and qdrant with a TCP connect to port 6333. These results control startup order, and `restart: unless-stopped` restarts the agent or nginx if its process exits.

## Part 4: API Security

### Exercise 4.1: API key authentication
- Without API key: `401 Unauthorized` `{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}`
- With API key: `200 OK` `{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}`

### Exercise 4.2: JWT Authentication 
- Get JWT token: `200 OK` `{"access_token":"<token>","token_type":"bearer","expires_in_minutes":60,"hint":"Include in header: Authorization: Bearer <token>"}`
- After insert JWT token: `200 OK` `{"question":"Explain JWT","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","usage":{"requests_remaining":8,"budget_remaining_usd":4e-05}}`

### Exercise 4.3: Rate limiter
- **Algorithm:** **Sliding window**, specifically a sliding window **log**, not a token bucket. Each user has a `deque` of request timestamps. On every request, timestamps older than `now - window_seconds` are removed from the front. If `max_requests` or more timestamps remain, the request is rejected with **429 Too Many Requests**, with `Retry-After` (computed from the oldest timestamp) and `X-RateLimit-*` headers. Otherwise the current timestamp is appended. Because the window moves with time instead of resetting at fixed minute boundaries, a user can't send 2× the limit by bursting at the edge of a window. A token bucket would instead refill tokens at a steady rate and allow bursts up to the bucket size.
- **Limit:** `window_seconds=60`, so limits are per minute:
   - Normal user (`rate_limiter_user`): **10 requests/minute**
   - Admin (`rate_limiter_admin`): **100 requests/minute**

   The 11th request from a user within 60 seconds gets a 429.
- **Bypassing the limit for admin:** The limiter is chosen per request from the JWT role (`04-api-gateway/production/app.py`):
   ```python
   limiter = rate_limiter_admin if role == "admin" else rate_limiter_user
   ```
   Logging in as an account with `role: "admin"` (for example `teacher`) gives a token that uses the 100 req/min limiter, which is 10× higher. The role comes from the signed JWT, so a user can't fake it. To remove the limit for admins completely, skip the check for that role:
   ```python
   if role != "admin":
       rate_info = rate_limiter_user.check(username)
   ```
   Even so, keeping a high limit for admins is safer than none, because it still protects the service if an admin token leaks.

- **Response when the rate limit is reached:** `429 Too Many Requests` `{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":32}}`

### Exercise 4.4: Cost guard implementation

**How the provided `cost_guard.py` works**
- Each user gets a `UsageRecord` that counts input and output tokens and requests for the current day. Cost is calculated from GPT-4o-mini prices ($0.15 per 1M input tokens, $0.60 per 1M output tokens).
- `check_budget()` runs **before** the LLM call:
  - If the **global** daily spend (all users) reaches $10, it returns **503**, which protects the whole bill.
  - If the **user's** daily spend reaches $1, it returns **402 Payment Required**, with `used_usd`, `budget_usd` and `resets_at`.
  - At 80% of the budget, it logs a warning.
- `record_usage()` runs **after** the LLM call and adds the real token cost.
- A new day automatically starts a fresh record, because `record.day != today`.
- **Limitation:** everything is stored in an in-memory `dict`. A restart resets every budget, and each replica or worker keeps its own count, so with N instances a user could spend N× the budget. That's why the exercise asks to move the state to Redis.

**My implementation: $10 per user per month, stored in Redis**

```python
import redis
from datetime import datetime, timezone

r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))

MONTHLY_BUDGET_USD = 10.0

# Atomic "check and reserve": runs entirely inside Redis, so two concurrent
# requests can't both read the same old value and overspend together.
_RESERVE_LUA = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
local cost    = tonumber(ARGV[1])
local budget  = tonumber(ARGV[2])
if current + cost > budget then
    return 0
end
redis.call('INCRBYFLOAT', KEYS[1], cost)
redis.call('EXPIRE', KEYS[1], ARGV[3])
return 1
"""
_reserve = r.register_script(_RESERVE_LUA)


def check_budget(user_id: str, estimated_cost: float) -> bool:
    """
    Return True if the user still has budget (and reserve estimated_cost),
    False if this request would exceed $10 for the current month.
    """
    month_key = datetime.now(timezone.utc).strftime("%Y-%m")   # e.g. 2026-11
    key = f"budget:{user_id}:{month_key}"
    ttl = 32 * 24 * 3600                                       # > 1 month → auto-cleanup
    return bool(_reserve(keys=[key], args=[estimated_cost, MONTHLY_BUDGET_USD, ttl]))
```

Using it in `/ask`:
```python
if not check_budget(username, estimated_cost=0.001):
    raise HTTPException(status_code=402, detail="Monthly budget exceeded")
answer = ask(body.question)
```

**Design decisions**

| Requirement | How it's handled |
|-------------|------------------|
| $10 per user per month | `MONTHLY_BUDGET_USD = 10.0`, compared against `current + estimated_cost`, so a request that **would** go over the budget is blocked before the LLM is called |
| Track spending in Redis | One key per user per month, `budget:<user_id>:<YYYY-MM>`, incremented with `INCRBYFLOAT`. It's shared by every replica and worker and survives app restarts |
| Reset at the start of the month | The month is part of the key. On the 1st (UTC), a new key `budget:alice:2026-12` starts at 0, so no cron job or manual reset is needed. `EXPIRE 32 days` deletes old keys automatically |
| Concurrency | The reference solution does `GET`, compares, then `INCRBYFLOAT` as separate steps, so two parallel requests can both pass the check and overspend. The Lua script runs all three steps **atomically** inside Redis, which fixes that race |
| UTC | `datetime.now(timezone.utc)`, so every instance switches month at the same moment regardless of server timezone |

**Possible improvements**
- Reserve an **estimated** cost first, then after the LLM call correct it with the real token cost (`INCRBYFLOAT key (actual - estimated)`), as `record_usage()` does.
- Keep the **global** cap as well (`budget:global:<YYYY-MM>`) and return 503 when it's reached, so one bug or many users can't exceed the company-wide bill.
- Warn at 80% (log or alert), as the original `warn_at_pct` does.
- If Redis is down, **fail closed**: return 503 instead of letting the request through unbudgeted.

## Part 5: Scaling & Reliability

### Exercise 5.1: Health check
- Verify Liveness probe: `200 OK` `{"status":"ok","uptime_seconds":132.4,"version":"1.0.0","environment":"development","timestamp":"2026-11-26T15:07:03.831266+00:00","checks":{"memory":{"status":"ok","used_percent":5.1}}}`
- Verify Readiness probe: `200 OK` `{"ready":true,"in_flight_requests":1}`

### Exercise 5.2: Graceful shutdown
- Command for sending SIGTERM: `kill -TERM $PID`

- Server after receiving SIGTERM: 
```
INFO:     127.0.0.1:55440 - "POST /ask HTTP/1.1" 422 Unprocessable Entity
INFO:     Waiting for application shutdown.
2026-11-26 22:17:22,680 INFO 🔄 Graceful shutdown initiated...
2026-11-26 22:17:22,680 INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
INFO:     Finished server process [3184]
2026-11-26 22:17:22,681 INFO Received signal 15 — uvicorn will handle graceful shutdown
```
- Request when calling SIGTERM immediately after calling the request: `422 Unprocessable Entity` `{"detail":[{"type":"missing","loc":["query","question"],"msg":"Field required","input":null}]}`

###  Exercise 5.3: Stateless design
**Why move state to Redis?** When the agent scales to several instances behind a load balancer, each request from the same user can go to a different instance. If session or conversation history is kept in an in-memory `dict`:
- **State is split:** request 1 is saved in instance A's memory, request 2 goes to instance B, which has no record of the session, so the conversation context is lost.
- **State is lost on restart:** every deploy, crash or scale-down wipes the memory of that instance, and its users' sessions with it.
- **No safe scaling:** you can't add or remove instances freely, and you'd need sticky sessions, which spread load unevenly and still fail when an instance dies.

Moving the state to Redis makes every agent instance **stateless**. Each request loads the session from Redis (`session:<id>`), updates it and saves it back, so any instance can serve any request. Redis is shared by all instances, survives app restarts, and `SETEX` gives each session a TTL so old sessions expire automatically.

###  Exercise 5.4: Load balancing
- Services after running:
| Service | Instances | Status |
|---|---|---|
| Agent | 3 | Up (healthy) |
| Redis | 1 | Up (healthy) |
| Nginx | 1 | Up |
- Observations: Nginx recive the request at port 8080 and evenly distributed to 3 agents.

###  Exercise 5.5: Test stateless
- Output of `python test_stateless.py` (3 agent replicas behind Nginx):
```
Session ID: f8143a1a-06d4-4036-9e6f-dd36cd70debe

Request 1: [instance-408426]   Q: What is Docker?
Request 2: [instance-7f2ef4]   Q: Why do we need containers?
Request 3: [instance-6ad612]   Q: What is Kubernetes?
Request 4: [instance-408426]   Q: How does load balancing work?
Request 5: [instance-7f2ef4]   Q: What is Redis used for?

Total requests: 5
Instances used: {'instance-408426', 'instance-7f2ef4', 'instance-6ad612'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
  ... (5 user + 5 assistant messages, in order)
✅ Session history preserved across all instances via Redis!
```
- Observations:
  - Nginx distributed the 5 requests **round-robin** across all 3 instances (408426 → 7f2ef4 → 6ad612 → 408426 → 7f2ef4), so consecutive requests of the same session were served by different instances.
  - Even so, all 5 requests used the **same session ID**, and the history endpoint (served by whichever instance received it) returned all **10 messages** (5 questions + 5 answers) in the correct order.
  - This shows no instance keeps the conversation in its own memory: each instance reads and writes the session in the shared Redis, so the agent is stateless and can be scaled up or down without losing user sessions.

## Part 6: Final Project

Run from WSL (Ubuntu, Python 3.12, Docker 29.9.3), full mode including the Docker build:
```bash
cd 06-lab-complete
python check_production_ready.py
```

### Checklist Deliverable
| # | Criterion | Result | Evidence from the checker |
|---|-----------|--------|---------------------------|
| 1 | Dockerfile (multi-stage, < 500 MB) | ✅ | 2 `FROM` stages, final stage `python:3.11-slim`, non-root user, `HEALTHCHECK`, image **273 MB**, container serves `GET /health` → 200 |
| 2 | docker-compose.yml (agent + redis) | ✅ | Services `agent` (built from Dockerfile) and `redis` (`redis:7-alpine`); agent has `REDIS_URL=redis://redis:6379/0` and `depends_on: redis` |
| 3 | .dockerignore | ✅ | Excludes `.env`, `__pycache__`, `venv` |
| 4 | Health check endpoint (`GET /health`) | ✅ | 200 with `uvicorn --workers 2` |
| 5 | Readiness endpoint (`GET /ready`) | ✅ | 200 when Redis is up; **503** when Redis is unreachable while `/health` stays 200 |
| 6 | API Key authentication | ✅ | Missing or wrong `X-API-Key` → 401; correct key → 200 |
| 7 | Rate limiting | ✅ | 429 after 5 successful requests (`RATE_LIMIT_PER_MINUTE=5`); still 429 after restarting the agent, so the state lives in Redis |
| 8 | Cost guard | ✅ | Budget `0.000001` USD → 402 on the 1st request |
| 9 | Config from environment variables | ✅ | `app/config.py` reads env vars, `.env.example` lists all variables, `.env` is git-ignored, no hard-coded secrets; the agent uses the random `AGENT_API_KEY` and `RATE_LIMIT_PER_MINUTE` passed by the checker |
| 10 | Structured logging | ✅ | Every app log line is valid JSON (17 lines) |
| 11 | Graceful shutdown | ✅ | SIGTERM during a request → the request still returns 200, process exits with code 0; `docker stop` → exit code 0 in **0.8 s** |
| 12 | Public URL ready (Railway / Render config) | ✅ | `railway.toml` (`builder = "DOCKERFILE"`, `healthcheckPath = "/health"`) and `render.yaml` (`type: web`, `healthCheckPath: /health`, `AGENT_API_KEY` uses `generateValue`); CMD listens on `${PORT:-8000}` |

**Result: 12/12 criteria · 43/43 checks passed — 🎉 PASS 12/12 — PRODUCTION READY!**

### What each piece reuses from Parts 1–5
| File | Built from |
|------|------------|
| `app/config.py` | Part 1: 12-factor config, every setting read from env vars with safe local defaults |
| `app/logging_config.py` | Part 1: structured JSON logs; the request middleware logs method, path, status and latency, never headers or secrets |
| `app/auth.py` | Part 4.1: `X-API-Key` header, compared with `secrets.compare_digest`, fails closed (401) if no key is configured |
| `app/rate_limiter.py` | Part 4.3 + 5.3: the sliding-window log algorithm, moved from an in-memory `deque` to a Redis sorted set inside one atomic Lua script, so all workers share it and it survives restarts. Returns `Retry-After` |
| `app/cost_guard.py` | Part 4.4: daily and monthly cost counters in Redis keyed by `YYYY-MM-DD` / `YYYY-MM` (automatic reset, `EXPIRE` cleans old keys). Checked before the LLM call (402), recorded after it, fails closed (503) if Redis is down |
| `app/main.py` | Part 5.1 + 5.2: `/health` liveness (always 200), `/ready` readiness (503 when Redis is down or shutting down), `lifespan` cleanup and uvicorn's own SIGTERM handling for graceful shutdown |
| `Dockerfile` | Part 2: multi-stage build with a venv copied into a slim runtime, non-root user, `HEALTHCHECK`, `exec uvicorn` so uvicorn is PID 1 and receives SIGTERM |
| `docker-compose.yml` | Part 2.4 + 5.4: agent + Redis with a healthcheck, `depends_on: condition: service_healthy`, optional `.env` |

