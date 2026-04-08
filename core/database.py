"""
Database layer — async helpers with PostgreSQL and SQLite backends.

The app now defaults to SQLite for local development, so the project works
without PostgreSQL installed. PostgreSQL is still supported by setting:

    DB_ENGINE=postgresql
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator, Sequence

import aiosqlite
import asyncpg

from config.settings import db as db_settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


class SQLiteConnection:
    """Small asyncpg-like wrapper over aiosqlite for local development."""

    def __init__(self, conn: aiosqlite.Connection):
        self._conn = conn

    async def execute(self, query: str, *args: Any) -> str:
        sql, params = _translate_sqlite_query(query, args)
        cursor = await self._conn.execute(sql, params)
        affected = max(cursor.rowcount, 0)
        command = _leading_sql_keyword(sql)
        await cursor.close()
        return f"{command} {affected}"

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        sql, params = _translate_sqlite_query(query, args)
        cursor = await self._conn.execute(sql, params)
        rows = await cursor.fetchall()
        await cursor.close()
        return [_sqlite_row_to_dict(row) for row in rows]

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        rows = await self.fetch(query, *args)
        return rows[0] if rows else None

    async def fetchval(self, query: str, *args: Any) -> Any:
        row = await self.fetchrow(query, *args)
        if not row:
            return None
        return next(iter(row.values()))

    async def executescript(self, script: str) -> None:
        await self._conn.executescript(script)


def using_sqlite() -> bool:
    return db_settings.is_sqlite


async def init_pool() -> None:
    """Initialize the configured database backend."""
    global _pool

    if db_settings.is_sqlite:
        db_path = Path(db_settings.path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            await conn.execute("PRAGMA journal_mode = WAL")
            await conn.commit()
        logger.info("SQLite database ready (%s)", db_path)
        return

    _pool = await asyncpg.create_pool(
        dsn=db_settings.dsn,
        min_size=db_settings.pool_min,
        max_size=db_settings.pool_max,
        command_timeout=30,
    )
    logger.info(
        "Database pool initialized (host=%s port=%s db=%s user=%s)",
        db_settings.host,
        db_settings.port,
        db_settings.name,
        db_settings.user,
    )


async def close_pool() -> None:
    """Close the configured database backend."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed")


@asynccontextmanager
async def get_conn() -> AsyncGenerator[Any, None]:
    """Acquire a connection-like object for the configured backend."""
    if db_settings.is_sqlite:
        async with aiosqlite.connect(db_settings.path) as conn:
            conn.row_factory = sqlite3.Row
            await conn.execute("PRAGMA foreign_keys = ON")
            yield SQLiteConnection(conn)
        return

    if _pool is None:
        raise RuntimeError("Database pool has not been initialized.")

    async with _pool.acquire() as conn:
        yield conn


@asynccontextmanager
async def transaction() -> AsyncGenerator[Any, None]:
    """Acquire a connection and wrap it in a transaction."""
    if db_settings.is_sqlite:
        async with aiosqlite.connect(db_settings.path) as conn:
            conn.row_factory = sqlite3.Row
            await conn.execute("PRAGMA foreign_keys = ON")
            await conn.execute("BEGIN")
            wrapped = SQLiteConnection(conn)
            try:
                yield wrapped
            except Exception:
                await conn.rollback()
                raise
            else:
                await conn.commit()
        return

    async with get_conn() as conn:
        async with conn.transaction():
            yield conn


def _translate_sqlite_query(query: str, args: Sequence[Any]) -> tuple[str, list[Any]]:
    """Translate a PostgreSQL-flavoured query into SQLite-compatible SQL."""
    sql = query

    # Common PostgreSQL function/type rewrites used by this codebase.
    sql = re.sub(r"([A-Za-z0-9_\.]+)\s*::\s*DATE\b", r"DATE(\1)", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bjsonb_build_object\s*\(", "json_object(", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bNOW\(\)", "CURRENT_TIMESTAMP", sql, flags=re.IGNORECASE)
    sql = re.sub(
        r"CURRENT_TIMESTAMP\s*-\s*INTERVAL\s*'([0-9]+)\s+days'",
        lambda match: f"datetime('now', '-{match.group(1)} days')",
        sql,
        flags=re.IGNORECASE,
    )
    sql = re.sub(r"::\s*(TEXT|TIME|INT|INTEGER|NUMERIC|JSONB)\b", "", sql, flags=re.IGNORECASE)

    params: list[Any] = []

    def repl(match: re.Match[str]) -> str:
        index = int(match.group(1)) - 1
        params.append(_normalize_sqlite_param(args[index]))
        return "?"

    sql = re.sub(r"\$(\d+)", repl, sql)
    return sql, params


def _normalize_sqlite_param(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    if isinstance(value, bool):
        return int(value)
    return value


def _sqlite_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = {key: row[key] for key in row.keys()}
    detail = data.get("detail")
    if isinstance(detail, str):
        try:
            data["detail"] = json.loads(detail)
        except json.JSONDecodeError:
            pass
    return data


def _leading_sql_keyword(sql: str) -> str:
    stripped = sql.lstrip()
    if not stripped:
        return "UNKNOWN"
    return stripped.split(None, 1)[0].upper()
