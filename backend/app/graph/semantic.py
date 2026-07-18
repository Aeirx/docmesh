"""Semantic overlap: mean of the top-k cross-document chunk cosine similarities.

WHY chunk pairs and not one embedding per document: averaging all of a document's
chunk embeddings into a single centroid is a low-pass filter — it keeps the
dominant theme and washes out localized overlap. Two documents can share one
intense section (a security survey and a vision paper both covering
model-extraction attacks) while differing broadly; their centroids diverge even
though specific passages are near-identical. The mean of the top-k
cross-document chunk similarities finds exactly those overlapping passages, and
averaging over k (rather than taking the single max) keeps one freak pair from
manufacturing an edge. The winning pairs are retained as evidence for the UI and
the Phase 4 LLM explainer — a centroid cosine has no evidence to show.

Vectors come from FAISS reconstruct (IndexIDMap2 keeps id->vector exactly), never
from re-embedding — a full model pass over the corpus per recompute would cost
minutes of CPU for vectors the index already holds.
"""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class DocVectors:
    doc_id: str
    chunk_ids: list[str]  # row-aligned with `matrix`
    matrix: np.ndarray  # (n_chunks, dim) float32, rows L2-normalized


@dataclass(frozen=True)
class SemanticOverlap:
    score: float  # calibrated to [0, 1] via the floor/ceil rescale (see combiner)
    raw_mean_cosine: float  # mean of the top-k cosines, uncalibrated
    top_pairs: list[tuple[str, str, float]]  # (chunk_id_a, chunk_id_b, cosine), desc


def semantic_overlaps(
    docs: list[DocVectors], *, top_k: int, floor: float, ceil: float
) -> dict[tuple[str, str], SemanticOverlap]:
    """Score every unordered document pair. Keys are (doc_id_i, doc_id_j) in
    input order for every i < j.

    ``floor``/``ceil`` are measured calibration knobs, not constants of nature:
    bge-family cosines between *unrelated* passages sit around 0.4-0.6 (the
    embedding space is anisotropic — vectors occupy a narrow cone), so raw cosine
    has no true zero. The affine rescale maps the model's empirical range onto
    [0, 1] so a semantic 0 means "as unrelated as this model ever reports".
    """
    out: dict[tuple[str, str], SemanticOverlap] = {}
    if not docs:
        return out

    # One big similarity matrix, block-sliced per pair: rows are L2-normalized,
    # so the inner product IS the cosine. C ~ 1000 chunks -> S is ~4 MB. A doc
    # whose chunks were all dedup'd away contributes an empty block (score 0).
    mats = [d.matrix for d in docs]
    dim = next((m.shape[1] for m in mats if m.size), 1)
    stacked = np.vstack([m if m.size else m.reshape(0, dim) for m in mats]).astype(np.float32)
    sims = stacked @ stacked.T
    offsets = np.concatenate(([0], np.cumsum([m.shape[0] for m in mats])))

    for i in range(len(docs)):
        for j in range(i + 1, len(docs)):
            block = sims[offsets[i] : offsets[i + 1], offsets[j] : offsets[j + 1]]
            if block.size == 0:
                # A document with zero indexed chunks (every chunk was a duplicate
                # of another doc's canonical copy — upload-level sha256 dedup
                # blocks exact re-uploads, so this only occurs for heavily
                # overlapping distinct files). Semantic reads 0; entity/topic
                # still fire because they score the doc's own text.
                out[(docs[i].doc_id, docs[j].doc_id)] = SemanticOverlap(0.0, 0.0, [])
                continue
            k = min(top_k, block.size)
            flat = block.ravel()
            # argpartition is O(na*nb) — no full sort; only the k winners get sorted.
            top = np.argpartition(flat, -k)[-k:]
            top = top[np.argsort(flat[top])[::-1]]
            raw = float(flat[top].mean())
            # A raveled index p maps back to (row, col) = (p // nb, p % nb).
            nb = block.shape[1]
            pairs = [
                (
                    docs[i].chunk_ids[int(p) // nb],
                    docs[j].chunk_ids[int(p) % nb],
                    round(float(flat[p]), 4),
                )
                for p in top
            ]
            score = min(1.0, max(0.0, (raw - floor) / (ceil - floor)))
            out[(docs[i].doc_id, docs[j].doc_id)] = SemanticOverlap(score, raw, pairs)
    return out
