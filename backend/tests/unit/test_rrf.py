"""RRF fusion unit tests — pure function, hand-computable expectations."""

import pytest

from app.search.fusion import rrf_fuse


class TestRrfFuse:
    def test_exact_formula_chunk_in_both_lists(self):
        fused = rrf_fuse([("a", 0.9)], [("a", 7.5)], k=60, dense_weight=0.5)
        assert len(fused) == 1
        assert fused[0].fused_score == pytest.approx(0.5 / 61 + 0.5 / 61)

    def test_hand_computed_two_item_case(self):
        # dense: a=1st, b=2nd; sparse: b=1st, a absent. k=60, w=0.6.
        fused = rrf_fuse([("a", 0.9), ("b", 0.8)], [("b", 5.0)], k=60, dense_weight=0.6)
        by_id = {f.chunk_id: f for f in fused}
        assert by_id["a"].fused_score == pytest.approx(0.6 / 61)
        assert by_id["b"].fused_score == pytest.approx(0.6 / 62 + 0.4 / 61)
        # b wins: 0.6/62 + 0.4/61 > 0.6/61
        assert fused[0].chunk_id == "b"

    def test_only_in_one_list(self):
        fused = rrf_fuse([("d", 0.7)], [("s", 3.0)], k=10, dense_weight=0.5)
        by_id = {f.chunk_id: f for f in fused}
        assert by_id["d"].fused_score == pytest.approx(0.5 / 11)
        assert by_id["d"].bm25_rank is None and by_id["d"].bm25_score is None
        assert by_id["s"].fused_score == pytest.approx(0.5 / 11)
        assert by_id["s"].dense_rank is None and by_id["s"].dense_score is None

    def test_degenerate_weights_reproduce_single_ranker(self):
        dense = [("a", 0.9), ("b", 0.8), ("c", 0.7)]
        sparse = [("c", 9.0), ("a", 8.0), ("b", 7.0)]
        dense_only = rrf_fuse(dense, sparse, k=60, dense_weight=1.0)
        assert [f.chunk_id for f in dense_only] == ["a", "b", "c"]
        sparse_only = rrf_fuse(dense, sparse, k=60, dense_weight=0.0)
        assert [f.chunk_id for f in sparse_only] == ["c", "a", "b"]

    def test_k_compresses_top_rank_gap(self):
        def gap_ratio(k: int) -> float:
            ranking = [(f"c{i}", 1.0 - i * 0.01) for i in range(10)]
            fused = rrf_fuse(ranking, [], k=k, dense_weight=1.0)
            return fused[0].fused_score / fused[9].fused_score

        # Larger k flattens the reciprocal curve: rank 1 vs rank 10 gets closer.
        assert gap_ratio(60) < gap_ratio(1)

    def test_tie_break_by_chunk_id(self):
        # Symmetric ranks at equal weight -> identical scores; order by id asc.
        fused = rrf_fuse([("z", 0.9), ("a", 0.8)], [("a", 5.0), ("z", 4.0)], k=60, dense_weight=0.5)
        assert fused[0].fused_score == pytest.approx(fused[1].fused_score)
        assert [f.chunk_id for f in fused] == ["a", "z"]

    def test_empty_inputs(self):
        assert rrf_fuse([], [], k=60, dense_weight=0.5) == []
        one_sided = rrf_fuse([("a", 0.9), ("b", 0.8)], [], k=60, dense_weight=0.5)
        assert [f.chunk_id for f in one_sided] == ["a", "b"]

    def test_raw_score_passthrough(self):
        fused = rrf_fuse([("a", 0.91), ("b", 0.82)], [("b", 6.5)], k=60, dense_weight=0.5)
        by_id = {f.chunk_id: f for f in fused}
        assert by_id["a"].dense_rank == 1 and by_id["a"].dense_score == 0.91
        assert by_id["b"].dense_rank == 2 and by_id["b"].dense_score == 0.82
        assert by_id["b"].bm25_rank == 1 and by_id["b"].bm25_score == 6.5
