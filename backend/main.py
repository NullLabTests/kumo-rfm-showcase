import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from collections import defaultdict

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from settings import settings
from services import get_load_status, start_background_load
from routes import router
from logger import log, set_component, set_request_id, set_request_start

set_component("main")

_BLOCKED_PATH_PATTERNS = [
    re.compile(r"\.env"),
    re.compile(r"\.py$"),
    re.compile(r"\.pyc$"),
    re.compile(r"\.pytest_cache"),
    re.compile(r"__pycache__"),
    re.compile(r"\.git"),
    re.compile(r"\.gitignore$"),
    re.compile(r"\.dockerignore$"),
    re.compile(r"^/backend/"),
    re.compile(r"^/tests/"),
]

_RATE_LIMIT_STORE: dict[str, list[float]] = defaultdict(list)


def _is_blocked(path: str) -> bool:
    for pat in _BLOCKED_PATH_PATTERNS:
        if pat.search(path):
            return True
    return False


def _check_rate_limit(client_ip: str) -> bool:
    if not settings.rate_limit_enabled:
        return True
    now = time.monotonic()
    window = settings.rate_limit_window_seconds
    max_req = settings.rate_limit_max_requests
    timestamps = _RATE_LIMIT_STORE[client_ip]
    cutoff = now - window
    timestamps[:] = [t for t in timestamps if t > cutoff]
    if len(timestamps) >= max_req:
        return False
    timestamps.append(now)
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting KumoRFM Demo server v2.2.0")
    if not settings.kumo_api_key:
        log.warning("KUMO_API_KEY is not set — predictions will fail")
    if not settings.auto_load_dataset:
        log.info("No auto-load dataset configured — waiting for manual load")
    else:
        log.info("Auto-loading dataset: %s", settings.auto_load_dataset)
    start_background_load()
    yield
    log.info("Shutting down.")


app = FastAPI(title="KumoRFM Demo", version="2.2.0", lifespan=lifespan)

allowed_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if "*" in allowed_origins else allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.middleware("http")
async def security_and_logging(request: Request, call_next):
    path = request.url.path

    if _is_blocked(path):
        log.warning("Blocked access to sensitive file: %s", path)
        return JSONResponse({"detail": "Not found"}, status_code=404)

    # Exempt lightweight polling endpoints from rate limiting
    if path not in ("/api/status", "/api/health", "/api/cache-stats"):
        if not _check_rate_limit(request.client.host if request.client else "unknown"):
            log.warning("Rate limit exceeded for %s", request.client.host if request.client else "unknown")
            return JSONResponse(
                {"detail": "Too many requests. Please slow down."}, status_code=429
            )

    rid = uuid.uuid4().hex[:12]
    set_request_id(rid)
    start = time.monotonic()
    set_request_start(start)
    method = request.method

    log.info("→ %s %s", method, path)

    try:
        response = await call_next(request)
    except Exception as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        log.error("! %s %s → 500 (%dms)", method, path, elapsed)
        return JSONResponse({"detail": "Internal server error"}, status_code=500)

    for header_name in ("server", "Server"):
        try:
            del response.headers[header_name]
        except (KeyError, AttributeError):
            pass

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"

    elapsed = int((time.monotonic() - start) * 1000)
    level = "WARNING" if response.status_code >= 400 else "INFO"
    log.log(getattr(logging, level), "← %s %s → %d (%dms)", method, path, response.status_code, elapsed)
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.error("Unhandled exception for %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


dist_dir = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(dist_dir):
    app.mount("/", StaticFiles(directory=dist_dir, html=True), name="frontend")
    log.info("Serving static files from %s", dist_dir)
else:
    log.warning("Frontend dist directory not found: %s", dist_dir)

if __name__ == "__main__":
    import uvicorn

    log.info("Listening on %s:%s", settings.host, settings.port)
    uvicorn.run(app, host=settings.host, port=settings.port, log_config=None)
