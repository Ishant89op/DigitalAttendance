"""
Central configuration — loaded once at startup.
All tuneable constants live here. No magic numbers scattered across files.
"""

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


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

    def __repr__(self) -> str:   # keep the password out of logs/tracebacks
        return f"DatabaseSettings(host={self.host!r}, port={self.port}, name={self.name!r}, user={self.user!r})"


# ─────────────────────────────────────────────
# FACE RECOGNITION
# ─────────────────────────────────────────────
@dataclass(frozen=True)
class RecognitionSettings:
    model_name: str         = "buffalo_l"        # InsightFace model pack
    det_size: tuple         = (640, 640)
    ctx_id: int             = -1                 # -1 = CPU, 0+ = GPU index
    similarity_threshold: float = 0.50           # cosine similarity cutoff
    match_margin: float     = 0.05               # winner must clearly beat the runner-up
    min_detection_score: float = 0.60            # ignore weak / partial detections
    strict_confidence_mode: bool = field(
        default_factory=lambda: _env_bool("ATTENDX_STRICT_CONFIDENCE", True)
    )
    strict_similarity_threshold: float = field(
        default_factory=lambda: float(os.getenv("ATTENDX_STRICT_SIMILARITY", "0.60"))
    )
    strict_match_margin: float = field(
        default_factory=lambda: float(os.getenv("ATTENDX_STRICT_MARGIN", "0.08"))
    )
    enable_liveness_check: bool = field(
        default_factory=lambda: _env_bool("ATTENDX_ENABLE_LIVENESS", True)
    )
    liveness_min_motion_px: float = field(
        default_factory=lambda: float(os.getenv("ATTENDX_LIVENESS_MIN_MOTION_PX", "2.0"))
    )
    liveness_required_frames: int = field(
        default_factory=lambda: int(os.getenv("ATTENDX_LIVENESS_REQUIRED_FRAMES", "4"))
    )
    liveness_motion_accum_px: float = field(
        default_factory=lambda: float(os.getenv("ATTENDX_LIVENESS_MOTION_ACCUM_PX", "5.0"))
    )
    liveness_scale_delta: float = field(
        default_factory=lambda: float(os.getenv("ATTENDX_LIVENESS_SCALE_DELTA", "0.07"))
    )
    liveness_signature_delta: float = field(
        default_factory=lambda: float(os.getenv("ATTENDX_LIVENESS_SIGNATURE_DELTA", "0.04"))
    )
    require_blink_liveness: bool = field(
        default_factory=lambda: _env_bool("ATTENDX_REQUIRE_BLINK_LIVENESS", True)
    )
    min_blink_count: int = field(
        default_factory=lambda: int(os.getenv("ATTENDX_MIN_BLINK_COUNT", "1"))
    )
    blink_min_closed_frames: int = field(
        default_factory=lambda: int(os.getenv("ATTENDX_BLINK_MIN_CLOSED_FRAMES", "1"))
    )
    blink_closed_ratio: float = field(
        default_factory=lambda: float(os.getenv("ATTENDX_BLINK_CLOSED_RATIO", "0.78"))
    )
    blink_open_ratio: float = field(
        default_factory=lambda: float(os.getenv("ATTENDX_BLINK_OPEN_RATIO", "0.80"))
    )
    blink_closed_min_ear: float = field(
        default_factory=lambda: float(os.getenv("ATTENDX_BLINK_CLOSED_MIN_EAR", "0.14"))
    )
    blink_open_min_ear: float = field(
        default_factory=lambda: float(os.getenv("ATTENDX_BLINK_OPEN_MIN_EAR", "0.18"))
    )
    cooldown_seconds: int   = 30                 # prevent duplicate marks
    max_faces_per_frame: int = 6
    samples_required: int   = 20                 # for registration
    embedding_dim: int      = 512


# ─────────────────────────────────────────────
# API
# ─────────────────────────────────────────────
def _env_list(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class APISettings:
    title: str    = "AttendX API"
    version: str  = "3.0.0"
    host: str     = field(default_factory=lambda: os.getenv("ATTENDX_HOST", "127.0.0.1"))
    port: int     = field(default_factory=lambda: int(os.getenv("ATTENDX_PORT", "8000")))
    # The UI is served by the API itself (same origin), so cross-origin access is
    # off unless explicitly allowed. Never combine "*" with credentials.
    cors_origins: list = field(default_factory=lambda: _env_list("ATTENDX_CORS_ORIGINS"))
    allowed_hosts: list = field(
        default_factory=lambda: _env_list("ATTENDX_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]")
    )
    enable_docs: bool = field(default_factory=lambda: _env_bool("ATTENDX_ENABLE_DOCS", False))
    max_body_bytes: int = 6 * 1024 * 1024


# ─────────────────────────────────────────────
# SECURITY
# ─────────────────────────────────────────────
@dataclass(frozen=True)
class SecuritySettings:
    # Where generated secrets live when they are not provided via env.
    instance_dir: str = field(
        default_factory=lambda: os.getenv(
            "ATTENDX_INSTANCE_DIR",
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "instance"),
        )
    )
    session_cookie: str = "attendx_session"
    # "auto" = Secure flag only when the request arrived over HTTPS.
    cookie_secure: str = field(default_factory=lambda: os.getenv("ATTENDX_COOKIE_SECURE", "auto"))
    session_idle_minutes: int = field(
        default_factory=lambda: int(os.getenv("ATTENDX_SESSION_IDLE_MINUTES", "30"))
    )
    session_absolute_hours: int = field(
        default_factory=lambda: int(os.getenv("ATTENDX_SESSION_ABSOLUTE_HOURS", "12"))
    )
    # Classroom kiosks stay signed in for a teaching day.
    classroom_idle_minutes: int = 12 * 60
    max_sessions_per_user: int = 5

    password_min_length: int = 10
    password_max_length: int = 128
    pin_min_length: int = 6
    pin_max_length: int = 12

    # Account lockout: 5 failures -> 1 min lock, doubling up to 15 min.
    lockout_threshold: int = 5
    lockout_base_seconds: int = 60
    lockout_max_seconds: int = 15 * 60

    # Per-IP limits (sliding window).
    login_rate_per_ip: int = 20          # login attempts per window
    login_rate_window_s: int = 300
    api_rate_per_ip: int = 600           # all requests per minute
    temp_password_ttl_hours: int = 72

    # Face-match score above which a new registration is treated as a
    # duplicate of another student (proxy enrolment).
    duplicate_face_threshold: float = 0.60


# ─────────────────────────────────────────────
# UPLOADS
# ─────────────────────────────────────────────
@dataclass(frozen=True)
class UploadSettings:
    max_evidence_bytes: int = 5 * 1024 * 1024
    max_csv_bytes: int      = 2 * 1024 * 1024
    max_csv_rows: int       = 5000


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
db        = DatabaseSettings()
recog     = RecognitionSettings()
api       = APISettings()
security  = SecuritySettings()
uploads   = UploadSettings()
analytics = AnalyticsSettings()
