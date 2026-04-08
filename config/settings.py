"""
Central configuration — loaded once at startup.
All tuneable constants live here. No magic numbers scattered across files.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

# Load the project-local .env regardless of the current working directory.
load_dotenv(dotenv_path=ENV_FILE, override=False)


def _resolve_db_path() -> str:
    raw = os.getenv("DB_PATH")
    if not raw:
        return str(PROJECT_ROOT / "attendance_system.db")
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return str(path)


# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────
@dataclass(frozen=True)
class DatabaseSettings:
    engine: str   = field(default_factory=lambda: os.getenv("DB_ENGINE", "sqlite").lower())
    host: str     = field(default_factory=lambda: os.getenv("DB_HOST", "localhost"))
    port: int     = field(default_factory=lambda: int(os.getenv("DB_PORT", "5432")))
    name: str     = field(default_factory=lambda: os.getenv("DB_NAME", "attendance_system"))
    user: str     = field(default_factory=lambda: os.getenv("DB_USER", "postgres"))
    password: str = field(default_factory=lambda: os.getenv("DB_PASSWORD", ""))
    path: str     = field(default_factory=_resolve_db_path)
    pool_min: int = 2
    pool_max: int = 10

    @property
    def dsn(self) -> str:
        if self.engine == "sqlite":
            return self.path
        return (
            f"postgresql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.name}"
        )

    @property
    def is_sqlite(self) -> bool:
        return self.engine == "sqlite"

    @property
    def is_postgres(self) -> bool:
        return self.engine == "postgresql"


# ─────────────────────────────────────────────
# FACE RECOGNITION
# ─────────────────────────────────────────────
@dataclass(frozen=True)
class RecognitionSettings:
    model_name: str         = "buffalo_l"        # InsightFace model pack
    det_size: tuple         = (320, 320)          # 320×320 is ~4× faster on CPU; same accuracy at <3m range
    ctx_id: int             = -1                 # -1 = CPU, 0+ = GPU index
    similarity_threshold: float = 0.50           # cosine similarity cutoff
    cooldown_seconds: int   = 30                 # prevent duplicate marks
    max_faces_per_frame: int = 6
    samples_required: int   = 20                 # for registration
    embedding_dim: int      = 512


# ─────────────────────────────────────────────
# API
# ─────────────────────────────────────────────
@dataclass(frozen=True)
class APISettings:
    title: str    = "Smart Attendance API"
    version: str  = "2.0.0"
    cors_origins: list = field(default_factory=lambda: ["*"])


# ─────────────────────────────────────────────
# ANALYTICS
# ─────────────────────────────────────────────
@dataclass(frozen=True)
class AnalyticsSettings:
    low_attendance_threshold: float = 75.0       # % below which alert fires
    critical_threshold: float       = 60.0       # % — critical warning


# ─────────────────────────────────────────────
# SINGLETON ACCESS
# ─────────────────────────────────────────────
db      = DatabaseSettings()
recog   = RecognitionSettings()
api     = APISettings()
analytics = AnalyticsSettings()
