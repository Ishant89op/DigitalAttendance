"""
Face utilities — InsightFace model singleton + known-face loader.

The model is heavy (~300MB). We load it ONCE at process start and reuse it.
Thread-safety: InsightFace's FaceAnalysis.get() is not thread-safe; the
recognizer runs in a single dedicated thread so this is fine.
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from config.settings import recog as cfg
from core.database import get_conn
from core.security import decrypt_face_template, encrypt_face_template

if TYPE_CHECKING:  # heavy import only where the model is actually needed
    from insightface.app import FaceAnalysis

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FaceMatch:
    index: int | None
    score: float
    second_score: float
    margin: float
    accepted: bool

# ─────────────────────────────────────────────
# MODEL SINGLETON
# ─────────────────────────────────────────────
_model: "FaceAnalysis | None" = None


def get_model() -> "FaceAnalysis":
    """Return the loaded InsightFace model, initializing it on first call."""
    global _model
    if _model is None:
        from insightface.app import FaceAnalysis

        logger.info("Loading InsightFace model '%s' ...", cfg.model_name)
        _model = FaceAnalysis(name=cfg.model_name)
        _model.prepare(ctx_id=cfg.ctx_id, det_size=cfg.det_size)
        logger.info("InsightFace model ready.")
    return _model


# ─────────────────────────────────────────────
# KNOWN FACE LOADER
# ─────────────────────────────────────────────

def encode_template(student_id: str, embedding: np.ndarray) -> bytes:
    """float32 embedding -> AES-256-GCM blob bound to this student_id."""
    raw = normalize(np.asarray(embedding, dtype=np.float32)).astype(np.float32).tobytes()
    return encrypt_face_template(student_id, raw)


def decode_template(student_id: str, blob: bytes) -> np.ndarray | None:
    """Stored blob -> normalised embedding, or None if corrupt/tampered."""
    try:
        raw = decrypt_face_template(student_id, bytes(blob))
    except ValueError:
        logger.error("Face template for %s failed its integrity check — ignoring it.", student_id)
        return None
    vec = np.frombuffer(raw, dtype=np.float32).copy()
    if vec.shape[0] != cfg.embedding_dim:
        logger.warning("Skipping %s — unexpected embedding dim %d", student_id, vec.shape[0])
        return None
    return normalize(vec)


async def load_known_faces(
    course_id: str | None = None,
) -> tuple[np.ndarray, list[str], list[str]]:
    """
    Load registered student embeddings from the database.

    When course_id is given, only students enrolled in that course (same
    department + semester) are loaded, so the camera cannot mark anyone else.

    Returns:
        encodings : (N, 512) float32 array — L2-normalised
        names     : list[str] of length N
        ids       : list[str] of length N
    """
    async with get_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT s.student_id, s.name, s.face_encoding
            FROM students s
            WHERE s.face_encoding IS NOT NULL
              AND (
                    $1::TEXT IS NULL
                    OR EXISTS (
                        SELECT 1 FROM courses c
                        WHERE c.course_id = $1
                          AND c.department = s.department
                          AND c.semester = s.semester
                    )
              )
            """,
            course_id,
        )

    encodings, names, ids = [], [], []
    for row in rows:
        vec = decode_template(row["student_id"], row["face_encoding"])
        if vec is None:
            continue
        encodings.append(vec)
        names.append(row["name"])
        ids.append(row["student_id"])

    if not ids:
        logger.warning("No registered faces found%s.", f" for course {course_id}" if course_id else "")
        return np.empty((0, cfg.embedding_dim), dtype=np.float32), [], []

    mat = np.array(encodings, dtype=np.float32)   # (N, 512)
    logger.info("Loaded %d face embeddings from database.", len(ids))
    return mat, names, ids


async def find_duplicate_face(
    embedding: np.ndarray,
    exclude_student_id: str,
    threshold: float,
) -> tuple[str, str, float] | None:
    """
    Return (student_id, name, score) of an already-registered *other* student
    whose face matches this embedding — i.e. one person trying to enrol under
    two IDs (proxy attendance). None when the face is unique.
    """
    matrix, names, ids = await load_known_faces()
    if not ids:
        return None
    query = normalize(np.asarray(embedding, dtype=np.float32))
    scores = matrix @ query
    best = None
    for idx in np.argsort(-scores):
        if ids[idx] == exclude_student_id:
            continue
        if float(scores[idx]) >= threshold:
            best = (ids[idx], names[idx], float(scores[idx]))
        break
    return best


# ─────────────────────────────────────────────
# EMBEDDING HELPERS
# ─────────────────────────────────────────────

def normalize(vec: np.ndarray) -> np.ndarray:
    """L2-normalize a 1-D embedding vector."""
    norm = np.linalg.norm(vec)
    if norm == 0:
        return vec
    return vec / norm


def cosine_match(
    query: np.ndarray,
    known_matrix: np.ndarray,
    threshold: float | None = None,
    min_margin: float | None = None,
) -> FaceMatch:
    """
    Find the best match for `query` in `known_matrix`.

    Args:
        query        : (D,) embedding vector
        known_matrix : (N, D) normalized embeddings
        threshold    : minimum cosine similarity to accept
        min_margin   : required winner-vs-runner-up margin

    Returns:
        FaceMatch with the best score and whether the match is safe to accept.
    """
    if known_matrix.shape[0] == 0:
        return FaceMatch(None, 0.0, 0.0, 0.0, False)

    if threshold is None:
        threshold = (
            cfg.strict_similarity_threshold
            if cfg.strict_confidence_mode
            else cfg.similarity_threshold
        )
    if min_margin is None:
        min_margin = (
            cfg.strict_match_margin
            if cfg.strict_confidence_mode
            else cfg.match_margin
        )

    query = normalize(np.asarray(query, dtype=np.float32))
    similarities = known_matrix @ query          # (N,) dot products
    best_idx = int(np.argmax(similarities))
    best_score = float(similarities[best_idx])
    if similarities.shape[0] > 1:
        second_score = float(np.partition(similarities, -2)[-2])
    else:
        second_score = -1.0
    margin = best_score - second_score

    accepted = best_score >= threshold and (
        similarities.shape[0] == 1 or margin >= min_margin
    )
    return FaceMatch(
        best_idx if accepted else None,
        best_score,
        second_score,
        margin,
        accepted,
    )
