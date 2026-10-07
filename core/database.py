"""
Database layer — async connection pool backed by asyncpg.

Rules:
  - No raw SQL outside this module's helpers or the repository layer.
  - All placeholders use $1, $2 ... (PostgreSQL style).
  - pool is initialized once at FastAPI startup; never re-created.
"""

import asyncpg
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from config.settings import db as db_settings

logger = logging.getLogger(__name__)

# Module-level pool (set by init_pool / torn down by close_pool)
_pool: asyncpg.Pool | None = None


# ─────────────────────────────────────────────
# LIFECYCLE
# ─────────────────────────────────────────────

async def init_pool() -> None:
    """Call once at application startup."""
    global _pool
    # Pass components separately: no password-in-URL escaping problems, and
    # nothing secret ends up in logs.
    _pool = await asyncpg.create_pool(
        host=db_settings.host,
        port=db_settings.port,
        user=db_settings.user,
        password=db_settings.password or None,
        database=db_settings.name,
        min_size=db_settings.pool_min,
        max_size=db_settings.pool_max,
        command_timeout=30,
        server_settings={"application_name": "attendx"},
    )
    logger.info(
        "Database pool initialized (%s@%s:%s/%s)",
        db_settings.user, db_settings.host, db_settings.port, db_settings.name,
    )


async def close_pool() -> None:
    """Call once at application shutdown."""
    global _pool
    if _pool:
        await _pool.close()
        logger.info("Database pool closed")


# ─────────────────────────────────────────────
# CONTEXT MANAGER — use everywhere
# ─────────────────────────────────────────────

@asynccontextmanager
async def get_conn() -> AsyncGenerator[asyncpg.Connection, None]:
    """
    Acquire a connection from the pool.

    Usage:
        async with get_conn() as conn:
            await conn.fetch(...)
    """
    if _pool is None:
        raise RuntimeError("Database pool has not been initialized.")
    async with _pool.acquire() as conn:
        yield conn


@asynccontextmanager
async def transaction() -> AsyncGenerator[asyncpg.Connection, None]:
    """
    Acquire a connection AND open a transaction.
    Rolls back automatically on exception.

    Usage:
        async with transaction() as conn:
            await conn.execute(...)
    """
    async with get_conn() as conn:
        async with conn.transaction():
            yield conn
