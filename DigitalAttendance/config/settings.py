"""
Central configuration — loaded once at startup.
All tuneable constants live here. No magic numbers scattered across files.
"""

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────
@dataclass(frozen=True)
class DatabaseSettings:
    host: str     = field(default_factory=lambda: os.getenv("DB_HOST", "localhost"))
    port: int     = field(default_factory=lambda: int(os.getenv("DB_PORT", "5432")))
    name: str     = field(default_factory=lambda: os.getenv("DB_NAME", "attendance_system"))
    user: str     = field(default_factory=lambda: os.getenv("DB_USER", "postgres"))
    password: str = field(default_factory=lambda: os.getenv("DB_PASSWORD", ""))
    pool_min: int = 2
    pool_max: int = 10

    @property
    def dsn(self) -> str:
        return (
            f"postgresql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.name}"
        )


# ─────────────────────────────────────────────
# FACE RECOGNITION
# ─────────────────────────────────────────────
@dataclass(frozen=True)
class RecognitionSettings:
    model_name: str         = "buffalo_l"        # InsightFace model pack
    det_size: tuple         = (640, 640)
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
