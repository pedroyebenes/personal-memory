from __future__ import annotations

from functools import lru_cache
from math import sqrt

from app.util.hashing import sha256_text

try:
    from sentence_transformers import SentenceTransformer
except Exception:  # pragma: no cover - fallback when dependency is unavailable
    SentenceTransformer = None  # type: ignore[assignment]


@lru_cache(maxsize=4)
def _load_model(model_name: str):
    if SentenceTransformer is None:
        return None
    return SentenceTransformer(model_name)


def _fallback_embedding(text: str, dimensions: int = 32) -> list[float]:
    digest = sha256_text(text)
    values: list[float] = []
    for index in range(dimensions):
        segment = digest[(index * 2) % len(digest):(index * 2) % len(digest) + 2]
        if len(segment) < 2:
            segment = (segment + digest)[:2]
        values.append((int(segment, 16) / 255.0) * 2 - 1)
    return values


def embed_texts(texts: list[str], model_name: str) -> list[list[float]]:
    model = _load_model(model_name)
    if model is None:
        return [_fallback_embedding(text) for text in texts]
    vectors = model.encode(texts, normalize_embeddings=True)
    return [vector.tolist() for vector in vectors]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = sqrt(sum(a * a for a in left))
    right_norm = sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)
