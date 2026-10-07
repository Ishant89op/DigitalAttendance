"""
AttendX — FastAPI application entry point.

Start with:
    python main.py server        → http://localhost:8000

The web UI (ui/) is served by this app, so the browser talks to a single
origin: cookies stay SameSite=Strict, CORS stays closed and the CSP can be
'self'-only.

Request pipeline (outermost first):
    TrustedHost → security headers → body-size cap → per-IP rate limit → routes
"""

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from api.routers import admin, analytics, attendance, auth, lecture
from config.settings import api as api_cfg
from core.auth import api_limiter, client_ip, purge_expired_sessions
from core.database import close_pool, init_pool
from core.recognition_manager import cleanup_dead_sessions, stop_all
from core.security import data_key, secret_key
from migrations.schema import run_migrations

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

UI_DIR = Path(__file__).resolve().parent.parent / "ui"

CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self' data:",
    "font-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])
DOCS_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; "
    "frame-ancestors 'none'"
)


async def _session_janitor() -> None:
    while True:
        await asyncio.sleep(3600)
        with contextlib.suppress(Exception):
            removed = await purge_expired_sessions()
            if removed:
                logger.info("Purged %d expired session(s).", removed)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting AttendX API ...")
    # Load (or create) keys up front so a misconfiguration fails fast.
    secret_key()
    data_key()
    await init_pool()
    await run_migrations()
    await cleanup_dead_sessions()
    janitor = asyncio.create_task(_session_janitor())
    logger.info("Database ready. UI at http://%s:%s/", api_cfg.host, api_cfg.port)
    yield
    janitor.cancel()
    logger.info("Shutting down — stopping all recognition processes ...")
    await stop_all()
    await close_pool()
    logger.info("Shutdown complete.")


app = FastAPI(
    title=api_cfg.title,
    version=api_cfg.version,
    description="AttendX — face-recognition attendance with role-based access control.",
    lifespan=lifespan,
    docs_url="/docs" if api_cfg.enable_docs else None,
    redoc_url=None,
    openapi_url="/openapi.json" if api_cfg.enable_docs else None,
)


# ─────────────────────────────────────────────
# MIDDLEWARE (registered innermost first)
# ─────────────────────────────────────────────

@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if request.url.path.startswith(("/css/", "/js/", "/fonts/", "/img/")):
        return await call_next(request)
    key = client_ip(request)
    if not api_limiter.hit(key):
        return JSONResponse(
            {"detail": "Too many requests. Slow down."},
            status_code=429,
            headers={"Retry-After": str(api_limiter.retry_after(key))},
        )
    return await call_next(request)


@app.middleware("http")
async def body_size_cap(request: Request, call_next):
    length = request.headers.get("content-length")
    if length is not None:
        try:
            too_big = int(length) > api_cfg.max_body_bytes
        except ValueError:
            return JSONResponse({"detail": "Invalid Content-Length."}, status_code=400)
        if too_big:
            return JSONResponse({"detail": "Request body too large."}, status_code=413)
    elif request.method in {"POST", "PUT", "PATCH"} and "chunked" in request.headers.get("transfer-encoding", ""):
        return JSONResponse({"detail": "Chunked uploads are not accepted."}, status_code=411)
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    headers = response.headers
    is_docs = path.startswith(("/docs", "/openapi.json"))
    headers.setdefault("Content-Security-Policy", DOCS_CSP if is_docs else CONTENT_SECURITY_POLICY)
    headers.setdefault("X-Content-Type-Options", "nosniff")
    headers.setdefault("X-Frame-Options", "DENY")
    headers.setdefault("Referrer-Policy", "no-referrer")
    headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()",
    )
    if request.url.scheme == "https":
        headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
    is_static = path.startswith(("/css/", "/js/", "/fonts/", "/img/"))
    if not is_static:
        # API data and HTML shells must never be cached or shared.
        headers.setdefault("Cache-Control", "no-store")
    return response


if api_cfg.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=api_cfg.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
    )

# Outermost: reject requests for unknown Host headers (DNS-rebinding defence).
app.add_middleware(TrustedHostMiddleware, allowed_hosts=api_cfg.allowed_hosts or ["localhost"])


# ─────────────────────────────────────────────
# ERROR HANDLING — never leak internals
# ─────────────────────────────────────────────

@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    fields = []
    for err in exc.errors()[:5]:
        loc = ".".join(str(p) for p in err.get("loc", []) if p not in ("body", "query", "path"))
        fields.append(f"{loc}: {err.get('msg', 'invalid')}" if loc else err.get("msg", "invalid"))
    return JSONResponse({"detail": "Invalid input — " + "; ".join(fields)}, status_code=422)


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        raise exc
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "Something went wrong on our side."}, status_code=500)


# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────

app.include_router(auth.router)
app.include_router(lecture.router)
app.include_router(attendance.router)
app.include_router(analytics.router)
app.include_router(admin.router)


@app.get("/health", tags=["Health"], include_in_schema=False)
async def health():
    return {"status": "ok", "service": api_cfg.title, "version": api_cfg.version}


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse("/login.html", status_code=307)


# Static UI last so API routes always win.
app.mount("/", StaticFiles(directory=str(UI_DIR), html=True), name="ui")
