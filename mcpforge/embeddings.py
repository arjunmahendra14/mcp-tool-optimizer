"""Semantic retrieval for tool descriptions.

Backend priority (first available wins):
  1. Voyage AI  — VOYAGE_API_KEY set + voyageai installed
  2. sentence-transformers — package installed (all-MiniLM-L6-v2, 80MB, local)
  3. TF-IDF keyword fallback — always available, no dependencies

Call embed() to get vectors; rank_tools() to retrieve top-K relevant tools.
"""

import hashlib
import json
import logging
import math
import re
import threading

logger = logging.getLogger(__name__)

_backend: str | None = None
_voyage_client = None
_st_model = None
_init_lock = threading.Lock()


def _init_backend() -> None:
    global _backend, _voyage_client, _st_model
    import os
    with _init_lock:
        if _backend is not None:
            return

        voyage_key = os.environ.get("VOYAGE_API_KEY")
        if voyage_key:
            try:
                import voyageai
                _voyage_client = voyageai.Client(api_key=voyage_key)
                _backend = "voyage"
                logger.info("Semantic retrieval: Voyage AI (voyage-3-lite)")
                return
            except ImportError:
                logger.debug("voyageai not installed, trying sentence-transformers")

        try:
            from sentence_transformers import SentenceTransformer
            _st_model = SentenceTransformer("all-MiniLM-L6-v2")
            _backend = "sentence-transformers"
            logger.info("Semantic retrieval: sentence-transformers (all-MiniLM-L6-v2)")
            return
        except ImportError:
            logger.debug("sentence-transformers not installed, using TF-IDF fallback")

        _backend = "tfidf"
        logger.info("Semantic retrieval: TF-IDF keyword fallback (install sentence-transformers or set VOYAGE_API_KEY for semantic embeddings)")


def _tfidf_vec(text: str, dim: int = 512) -> list[float]:
    tokens = re.findall(r"\w+", text.lower())
    vec = [0.0] * dim
    for token in tokens:
        vec[int(hashlib.md5(token.encode()).hexdigest(), 16) % dim] += 1.0
    mag = math.sqrt(sum(x * x for x in vec))
    return [x / mag for x in vec] if mag > 0 else vec


def embed(texts: list[str]) -> list[list[float]]:
    """Return one embedding vector per text string."""
    if _backend is None:
        _init_backend()

    if _backend == "voyage":
        result = _voyage_client.embed(texts, model="voyage-3-lite")
        return result.embeddings

    if _backend == "sentence-transformers":
        vecs = _st_model.encode(texts, show_progress_bar=False)
        return [v.tolist() for v in vecs]

    return [_tfidf_vec(t) for t in texts]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(y * y for y in b))
    return dot / (mag_a * mag_b) if mag_a > 0 and mag_b > 0 else 0.0


def tool_description_text(server: str, name: str, description: str, input_schema: dict) -> str:
    """Canonical text representation of a tool for embedding."""
    params = []
    for param_name, prop in (input_schema.get("properties") or {}).items():
        desc = prop.get("description", "")
        params.append(f"{param_name}: {desc}" if desc else param_name)
    param_str = "; ".join(params) if params else "no parameters"
    return f"{server}/{name}: {description}. Parameters: {param_str}"


def rank_tools(
    query: str,
    tool_embeddings: dict[tuple[str, str], list[float]],
    top_k: int = 10,
) -> list[tuple[str, str, float]]:
    """Return (server, tool, score) sorted descending by semantic relevance to query."""
    if not tool_embeddings:
        return []

    query_vec = embed([query])[0]
    scores = [
        (server, tool, cosine(query_vec, emb))
        for (server, tool), emb in tool_embeddings.items()
    ]
    scores.sort(key=lambda x: x[2], reverse=True)
    return scores[:top_k]
