"""Reciprocal Rank Fusion — a pure function over two rankings.

RRF (Cormack et al., 2009) deliberately discards raw scores and fuses on ranks:
cosine and BM25 live on incommensurable scales, and any per-query normalization
is distribution-sensitive. ``score(c) = w * 1/(k + dense_rank) + (1-w) * 1/(k +
bm25_rank)``; k flattens the reciprocal curve near the top so consensus across
rankers — not one ranker's #1 — decides.
"""

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class FusedHit:
    chunk_id: str
    fused_score: float
    dense_rank: int | None  # 1-based rank in the dense list, None if absent
    dense_score: float | None  # raw cosine, None if absent
    bm25_rank: int | None
    bm25_score: float | None


def _by_rank(ranking: Sequence[tuple[str, float]]) -> dict[str, tuple[int, float]]:
    """chunk_id -> (1-based rank, raw score); a repeated id keeps its best rank."""
    out: dict[str, tuple[int, float]] = {}
    for rank, (chunk_id, score) in enumerate(ranking, start=1):
        out.setdefault(chunk_id, (rank, score))
    return out


def rrf_fuse(
    dense: Sequence[tuple[str, float]],  # ranked best-first: (chunk_id, cosine)
    sparse: Sequence[tuple[str, float]],  # ranked best-first: (chunk_id, bm25 score)
    *,
    k: int,
    dense_weight: float,
) -> list[FusedHit]:
    """A chunk absent from a list contributes 0 for that term (rank treated as
    infinity — the standard RRF convention). Sorted by fused_score DESC, ties
    broken by chunk_id ASC, so the output is fully deterministic."""
    dense_by_id = _by_rank(dense)
    sparse_by_id = _by_rank(sparse)

    hits: list[FusedHit] = []
    for chunk_id in dense_by_id.keys() | sparse_by_id.keys():
        d = dense_by_id.get(chunk_id)
        s = sparse_by_id.get(chunk_id)
        fused = 0.0
        if d is not None:
            fused += dense_weight / (k + d[0])
        if s is not None:
            fused += (1.0 - dense_weight) / (k + s[0])
        hits.append(
            FusedHit(
                chunk_id=chunk_id,
                fused_score=fused,
                dense_rank=d[0] if d else None,
                dense_score=d[1] if d else None,
                bm25_rank=s[0] if s else None,
                bm25_score=s[1] if s else None,
            )
        )
    hits.sort(key=lambda h: (-h.fused_score, h.chunk_id))
    return hits
