"""Signal combination: weighted sum over per-signal calibrated scores.

DECISION — fixed per-signal calibration, NOT per-batch min-max normalization.
Three reasons, each fatal to min-max on its own:

1. Min-max makes every score relative to the current corpus. Adding one document
   changes the batch min/max, rescaling EVERY edge — including pairs not
   involving the new doc — and edges flip across the threshold
   nondeterministically. The threshold stops meaning "this related" and starts
   meaning "top fraction of whatever is currently uploaded".
2. It degenerates at exactly the scale this app lives at. Two documents = one
   pair -> max == min -> 0/0. Three documents -> per signal, one pair is forced
   to 0 and one to 1 regardless of actual relatedness.
3. Stored scores stay reproducible without it. With calibrated-raw,
   combined = w_s*semantic + w_e*entity + w_t*topic holds over the STORED
   columns — verifiable by hand from a DB dump. With batch normalization the
   stored raw columns cannot reproduce the stored combined score unless the
   batch statistics are stored too.

Comparability is instead achieved per signal, each with a true zero: entity
weighted-Jaccard and 1-JS are naturally [0, 1] where 0 means "nothing shared";
the one offender — dense cosine, whose empirical floor for bge-family models is
~0.5 — gets a fixed affine recalibration (semantic_floor/semantic_ceil in
config, both inside the params hash). This is the direct answer to the "your
weights don't mean what you think" trap: after calibration, a weight IS the
signal's share of a fully-confident edge.
"""

import hashlib
import json
from typing import Literal

from app.core.config import GraphSettings

SignalName = Literal["semantic", "entity", "topic"]

# Every setting that affects scoring. Changing any of these changes the hash,
# which marks all stored edges/analysis stale (repaired on the next recompute
# trigger or at startup). Display-only knobs (top_entities_per_node) are
# deliberately absent.
SCORING_FIELDS: tuple[str, ...] = (
    "semantic_weight",
    "entity_weight",
    "topic_weight",
    "edge_threshold",
    "top_k_pairs",
    "n_topics",
    "entity_labels",
    "min_entity_len",
    "semantic_floor",
    "semantic_ceil",
    "spacy_model",
    "random_state",
)


def compute_params_hash(g: GraphSettings) -> str:
    """sha256 hex (64 chars — exactly the column width) of the sorted-key JSON of
    every scoring-relevant setting."""
    payload = {field: getattr(g, field) for field in SCORING_FIELDS}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def combine(semantic: float, entity: float, topic: float, g: GraphSettings) -> float:
    """w_s*sem + w_e*ent + w_t*top. Weights need not sum to 1 — they are relative
    importances; the default edge_threshold is calibrated against the default
    0.5/0.3/0.2 weights, which happen to sum to 1 and keep combined in [0, 1]."""
    return (
        g.semantic_weight * semantic + g.entity_weight * entity + g.topic_weight * topic
    )


def dominant_signal(
    semantic: float, entity: float, topic: float, g: GraphSettings
) -> SignalName:
    """Argmax of the WEIGHTED contributions (w*score), not the raw scores: the
    question it answers is "which signal drove this edge's combined score", and
    a raw entity 0.9 at weight 0.3 contributes less than a semantic 0.6 at 0.5.
    Ties break semantic > entity > topic (listed order wins in max())."""
    contributions: list[tuple[SignalName, float]] = [
        ("semantic", g.semantic_weight * semantic),
        ("entity", g.entity_weight * entity),
        ("topic", g.topic_weight * topic),
    ]
    best = max(contributions, key=lambda c: c[1])
    return best[0]
