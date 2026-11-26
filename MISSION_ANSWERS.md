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


## Part 3: Cloud Deployment

### Exercise 3.1: Railway deployment
- URL: https://your-app.railway.app
- Screenshot: [Link to screenshot in repo]

## Part 4: API Security

### Exercise 4.1-4.3: Test results
[Paste your test outputs]

### Exercise 4.4: Cost guard implementation
[Explain your approach]

## Part 5: Scaling & Reliability

### Exercise 5.1-5.5: Implementation notes
[Your explanations and test results]