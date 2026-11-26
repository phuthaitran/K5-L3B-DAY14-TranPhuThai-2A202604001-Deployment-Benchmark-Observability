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
1. Base image: [Your answer]
2. Working directory: [Your answer]
...

### Exercise 2.3: Image size comparison
- Develop: [X] MB
- Production: [Y] MB
- Difference: [Z]%

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