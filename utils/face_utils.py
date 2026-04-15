"""
Face utilities — InsightFace model singleton + known-face loader.

The model is heavy (~300MB). We load it ONCE at process start and reuse it.
Thread-safety: InsightFace's FaceAnalysis.get() is not thread-safe; the
recognizer runs in a single dedicated thread so this is fine.
"""

import logging
from dataclasses import dataclass

import numpy as np
from insightface.app import FaceAnalysis

from config.settings import recog as cfg
from core.database import get_conn

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
_model: FaceAnalysis | None = None


def get_model() -> FaceAnalysis:
    """Return the loaded InsightFace model, initializing it on first call."""
    global _model
    if _model is None:
        logger.info("Loading InsightFace model '%s' ...", cfg.model_name)
        _model = FaceAnalysis(name=cfg.model_name)
        _model.prepare(ctx_id=cfg.ctx_id, det_size=cfg.det_size)
        logger.info("InsightFace model ready.")
    return _model


# ─────────────────────────────────────────────
# KNOWN FACE LOADER
# ─────────────────────────────────────────────

async def load_known_faces() -> tuple[np.ndarray, list[str], list[str]]:
    """
    Load all registered student embeddings from the database.

    Returns:
        encodings : (N, 512) float32 array — L2-normalised
        names     : list[str] of length N
        ids       : list[str] of length N
    """
    async with get_conn() as conn:
        rows = await conn.fetch(
            "SELECT student_id, name, face_encoding FROM students "
            "WHERE face_encoding IS NOT NULL"
        )

    if not rows:
        logger.warning("No registered faces found in database.")
        return np.empty((0, cfg.embedding_dim), dtype=np.float32), [], []

    encodings, names, ids = [], [], []
    for row in rows:
        raw = row["face_encoding"]           # bytes from BYTEA column
        vec = np.frombuffer(raw, dtype=np.float32).copy()
        if vec.shape[0] != cfg.embedding_dim:
            logger.warning("Skipping %s — unexpected embedding dim %d",
                           row["student_id"], vec.shape[0])
            continue
        encodings.append(normalize(vec))
        names.append(row["name"])
        ids.append(row["student_id"])

    mat = np.array(encodings, dtype=np.float32)   # (N, 512)
    logger.info("Loaded %d face embeddings from database.", len(ids))
    return mat, names, ids


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
