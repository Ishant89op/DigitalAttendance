"""
Smart Digital Attendance System — FastAPI application entry point.

Start with:
    python main.py server

Swagger UI:  http://localhost:8000/docs
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import admin, analytics, attendance
from config.settings import api as api_cfg
from core.database import init_pool, close_pool
from core.recognition_manager import stop_all
from migrations.schema import run_migrations
from api.routers import lecture

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──
    logger.info("Starting up AttendX API ...")
    await init_pool()
    await run_migrations()
    logger.info("Database ready.")
    yield
    # ── Shutdown ──
    logger.info("Shutting down — stopping all recognition processes ...")
    await stop_all()
    await close_pool()
    logger.info("Shutdown complete.")


app = FastAPI(
    title=api_cfg.title,
    version=api_cfg.version,
    description=(
        "Backend API for the Smart Digital Attendance System. "
        "Clicking Start Attendance in the UI automatically starts the camera process."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=api_cfg.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(lecture.router)
app.include_router(attendance.router)
app.include_router(analytics.router)
app.include_router(admin.router)


@app.get("/", tags=["Health"])
async def health():
    return {
        "status":  "ok",
        "service": api_cfg.title,
        "version": api_cfg.version,
    }
