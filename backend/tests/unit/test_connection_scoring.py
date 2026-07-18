"""Pure scoring logic with hand-built inputs — no models, no I/O.

Every expected number here is computable by hand; that is the point: the scoring
primitives must be defensible line-by-line, and these tests ARE the worked
examples. Real sklearn/scipy run in this tier (normal fast deps, no download);
only spaCy is faked elsewhere — nothing in this module touches NER.
"""

import math

import numpy as np
import pytest

from app.core.config import GraphSettings
from app.graph.combiner import (
    SCORING_FIELDS,
    combine,
    compute_params_hash,
    dominant_signal,
)
from app.graph.entities import EntityOverlap, EntityScorer
from app.graph.semantic import DocVectors, semantic_overlaps
from app.graph.topics import fit_topics, topic_similarity

# --- semantic ---------------------------------------------------------------


def _unit(v: list[float]) -> list[float]:
    arr = np.asarray(v, dtype=np.float32)
    return (arr / float(np.linalg.norm(arr))).tolist()


def _doc(doc_id: str, rows: list[list[float]]) -> DocVectors:
    matrix = (
        np.asarray([_unit(r) for r in rows], dtype=np.float32)
        if rows
        else np.zeros((0, 4), dtype=np.float32)
    )
    return DocVectors(doc_id, [f"{doc_id}-c{i}" for i in range(len(rows))], matrix)


def test_semantic_top_k_mean_and_pairs() -> None:
    # a0 == b0 (cosine 1.0), a1 orthogonal to everything in B (cosine 0.0):
    # top-2 mean = (1.0 + 0.0) / 2 = 0.5 exactly.
    doc_a = _doc("a", [[1, 0, 0, 0], [0, 1, 0, 0]])
    doc_b = _doc("b", [[1, 0, 0, 0]])
    out = semantic_overlaps([doc_a, doc_b], top_k=2, floor=0.0, ceil=1.0)
    overlap = out[("a", "b")]
    assert overlap.raw_mean_cosine == pytest.approx(0.5)
    assert overlap.score == pytest.approx(0.5)
    # Pairs are (chunk_a, chunk_b, cosine), descending; the identical pair wins.
    assert overlap.top_pairs[0][:2] == ("a-c0", "b-c0")
    assert overlap.top_pairs[0][2] == pytest.approx(1.0)
    assert [p[2] for p in overlap.top_pairs] == sorted(
        (p[2] for p in overlap.top_pairs), reverse=True
    )


def test_semantic_k_clamped_to_block_size() -> None:
    # 1x1 block but top_k=10: k clamps to 1, mean is the single cosine.
    out = semantic_overlaps(
        [_doc("a", [[1, 0, 0, 0]]), _doc("b", [[1, 0, 0, 0]])], top_k=10, floor=0.0, ceil=1.0
    )
    overlap = out[("a", "b")]
    assert len(overlap.top_pairs) == 1
    assert overlap.raw_mean_cosine == pytest.approx(1.0)


def test_semantic_empty_doc_scores_zero() -> None:
    out = semantic_overlaps(
        [_doc("a", []), _doc("b", [[1, 0, 0, 0]])], top_k=5, floor=0.0, ceil=1.0
    )
    assert out[("a", "b")].score == 0.0
    assert out[("a", "b")].top_pairs == []


def test_semantic_calibration_clips_both_ends() -> None:
    docs = [_doc("a", [[1, 0, 0, 0]]), _doc("b", [[1, 0, 0, 0]])]
    # raw cosine 1.0 > ceil 0.95 -> clipped to 1.0.
    assert semantic_overlaps(docs, top_k=1, floor=0.5, ceil=0.95)[("a", "b")].score == 1.0
    # Orthogonal: raw 0.0 < floor 0.5 -> clipped to 0.0 (a true zero).
    docs = [_doc("a", [[1, 0, 0, 0]]), _doc("b", [[0, 1, 0, 0]])]
    overlap = semantic_overlaps(docs, top_k=1, floor=0.5, ceil=0.95)[("a", "b")]
    assert overlap.score == 0.0
    assert overlap.raw_mean_cosine == pytest.approx(0.0)  # raw survives uncalibrated


def test_semantic_midrange_affine_rescale() -> None:
    # cos(45 deg) ~ 0.7071 between floor 0.5 and ceil 0.95: (0.7071-0.5)/0.45.
    docs = [_doc("a", [[1, 0, 0, 0]]), _doc("b", [[1, 1, 0, 0]])]
    overlap = semantic_overlaps(docs, top_k=1, floor=0.5, ceil=0.95)[("a", "b")]
    expected = (math.sqrt(0.5) - 0.5) / 0.45
    assert overlap.score == pytest.approx(expected, abs=1e-4)


# --- entities ---------------------------------------------------------------


def _ents(*names: str) -> dict[tuple[str, str], int]:
    return {(name, "ORG"): 1 for name in names}


def test_rare_shared_entity_beats_common() -> None:
    # Symmetric setup: pair X and pair Y both share exactly one entity and carry
    # two distinct filler entities each — the ONLY difference is the shared
    # entity's rarity ("dinov3" df=2 of 5 vs "google" df=3 of 5), so rarity
    # alone must decide the ranking.
    scorer = EntityScorer(
        {
            "d1": _ents("dinov3", "aws"),
            "d2": _ents("dinov3", "azure"),
            "d3": _ents("google", "gcp"),
            "d4": _ents("google", "oracle"),
            "d5": _ents("google", "ibm"),
        }
    )
    idf_rare = math.log(1 + 5 / 2)
    idf_common = math.log(1 + 5 / 3)
    idf_filler = math.log(1 + 5 / 1)
    assert scorer.idf(("dinov3", "ORG")) == pytest.approx(idf_rare)
    assert scorer.idf(("google", "ORG")) == pytest.approx(idf_common)
    x = scorer.score("d1", "d2")
    y = scorer.score("d3", "d4")
    # Weighted Jaccard by hand: shared idf / union idf.
    assert x.score == pytest.approx(idf_rare / (idf_rare + 2 * idf_filler))
    assert y.score == pytest.approx(idf_common / (idf_common + 2 * idf_filler))
    assert x.score > y.score


def test_weighted_jaccard_bounds() -> None:
    scorer = EntityScorer({"d1": _ents("alpha", "beta"), "d2": _ents("alpha", "beta")})
    assert scorer.score("d1", "d2").score == pytest.approx(1.0)  # identical sets
    scorer = EntityScorer({"d1": _ents("alpha"), "d2": _ents("beta")})
    assert scorer.score("d1", "d2").score == 0.0  # disjoint
    scorer = EntityScorer({"d1": {}, "d2": {}})
    assert scorer.score("d1", "d2") == EntityOverlap(0.0, [])  # empty union


def test_smoothed_idf_survives_df_equals_n() -> None:
    # The 2-doc trap: "dinov3" in BOTH docs has df=N. Plain log(N/df) would give
    # idf 0 and a dead entity signal; smoothed log(1 + N/df) gives log 2.
    scorer = EntityScorer({"d1": _ents("dinov3"), "d2": _ents("dinov3")})
    assert scorer.idf(("dinov3", "ORG")) == pytest.approx(math.log(2))
    assert scorer.score("d1", "d2").score == pytest.approx(1.0)


def test_shared_list_idf_desc_with_counts() -> None:
    scorer = EntityScorer(
        {
            "d1": {("rare", "ORG"): 7, ("common", "ORG"): 2},
            "d2": {("rare", "ORG"): 3, ("common", "ORG"): 5},
            "d3": {("common", "ORG"): 1},
        }
    )
    shared = scorer.score("d1", "d2").shared
    assert [s.text for s in shared] == ["rare", "common"]  # idf desc
    assert (shared[0].count_a, shared[0].count_b) == (7, 3)
    assert shared[0].idf > shared[1].idf


# --- topics -----------------------------------------------------------------


def test_topic_similarity_identical_is_one() -> None:
    p = np.array([0.5, 0.3, 0.2])
    assert topic_similarity(p, p) == 1.0


def test_topic_similarity_disjoint_is_zero() -> None:
    # One-hot on different components: JS distance in base 2 is exactly 1.
    assert topic_similarity(np.array([1.0, 0.0]), np.array([0.0, 1.0])) == pytest.approx(0.0)


def test_topic_similarity_guards_zero_and_none() -> None:
    p = np.array([0.5, 0.5])
    assert topic_similarity(None, p) == 0.0
    assert topic_similarity(p, None) == 0.0
    assert topic_similarity(np.zeros(2), p) == 0.0


def test_topic_similarity_bounded() -> None:
    rng = np.random.default_rng(0)
    for _ in range(20):
        p = rng.random(4)
        q = rng.random(4)
        sim = topic_similarity(p / p.sum(), q / q.sum())
        assert 0.0 <= sim <= 1.0


def test_fit_topics_deterministic() -> None:
    # Every content word appears in >= 2 chunks so min_df=2 (6 texts >= 5)
    # cannot zero out a document's vocabulary.
    doc_chunks = {
        "d1": ["neural networks deep learning", "neural networks optimization training"],
        "d2": ["cell mitochondria energy biology", "mitochondria cell energy metabolism"],
        "d3": ["deep learning training optimization", "deep learning neural optimization"],
    }
    m1 = fit_topics(doc_chunks, n_topics=4, random_state=42)
    m2 = fit_topics(doc_chunks, n_topics=4, random_state=42)
    assert m1 is not None and m2 is not None
    assert m1.n_components == m2.n_components
    for doc_id in doc_chunks:
        np.testing.assert_allclose(
            m1.doc_distributions[doc_id], m2.doc_distributions[doc_id]
        )
    assert m1.topic_terms == m2.topic_terms
    # Distributions are probability vectors.
    for dist in m1.doc_distributions.values():
        assert dist.sum() == pytest.approx(1.0)


def test_fit_topics_degenerate_corpus_returns_none() -> None:
    assert fit_topics({}, n_topics=4, random_state=42) is None
    # Stop-words only -> empty vocabulary -> None (all topic scores become 0).
    assert (
        fit_topics({"d1": ["the and of", "a an the"]}, n_topics=4, random_state=42) is None
    )


def test_fit_topics_single_chunk_corpus() -> None:
    # One doc, one chunk: k clamps to 1 (nndsvda demands k <= min(samples,
    # features) — a floor of 2 here would crash the very first ingestion).
    model = fit_topics({"d1": ["mitochondria energy biology"]}, n_topics=8, random_state=42)
    assert model is not None
    assert model.n_components == 1
    assert model.doc_distributions["d1"].sum() == pytest.approx(1.0)


# --- combiner ---------------------------------------------------------------


def _graph_settings(**overrides: object) -> GraphSettings:
    return GraphSettings(**overrides)  # type: ignore[arg-type]


def test_combine_arithmetic() -> None:
    g = _graph_settings()
    assert combine(0.8, 0.5, 0.2, g) == pytest.approx(0.5 * 0.8 + 0.3 * 0.5 + 0.2 * 0.2)
    assert combine(0.0, 0.0, 0.0, g) == 0.0
    assert combine(1.0, 1.0, 1.0, g) == pytest.approx(1.0)  # default weights sum to 1


def test_threshold_boundary_is_inclusive() -> None:
    # The service keeps combined >= threshold; equality keeps the edge.
    g = _graph_settings(edge_threshold=0.35)
    combined = combine(0.7, 0.0, 0.0, g)  # 0.5 * 0.7 == 0.35 exactly
    assert combined == pytest.approx(g.edge_threshold)
    assert combined >= g.edge_threshold


def test_dominant_signal_uses_weighted_contributions() -> None:
    g = _graph_settings()
    # Raw entity 0.9 x weight 0.3 = 0.27 loses to semantic 0.6 x 0.5 = 0.30.
    assert dominant_signal(0.6, 0.9, 0.0, g) == "semantic"
    assert dominant_signal(0.1, 0.9, 0.0, g) == "entity"
    assert dominant_signal(0.0, 0.0, 0.9, g) == "topic"


def test_dominant_signal_tie_break_order() -> None:
    # Equal weighted contributions: semantic > entity > topic.
    g = _graph_settings(semantic_weight=1.0, entity_weight=1.0, topic_weight=1.0)
    assert dominant_signal(0.5, 0.5, 0.5, g) == "semantic"
    assert dominant_signal(0.0, 0.5, 0.5, g) == "entity"


def test_params_hash_changes_with_any_scoring_field() -> None:
    base = compute_params_hash(_graph_settings())
    assert len(base) == 64  # sha256 hex == column width
    changed = {
        "semantic_weight": 0.6,
        "entity_weight": 0.4,
        "topic_weight": 0.3,
        "edge_threshold": 0.5,
        "top_k_pairs": 5,
        "n_topics": 6,
        "entity_labels": ["ORG"],
        "min_entity_len": 4,
        "semantic_floor": 0.4,
        "semantic_ceil": 0.9,
        "spacy_model": "en_core_web_lg",
        "random_state": 7,
    }
    assert set(changed) == set(SCORING_FIELDS)  # keep this test honest vs. the list
    for field, value in changed.items():
        assert compute_params_hash(_graph_settings(**{field: value})) != base, field
    # Stability: same settings -> same hash (sorted-key JSON, no dict-order luck).
    assert compute_params_hash(_graph_settings()) == base
    # Display-only knob does NOT invalidate the graph.
    assert compute_params_hash(_graph_settings(top_entities_per_node=99)) == base
